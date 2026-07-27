"""Shared pieces for the P4 capacity harness (P4-11, plan/05/04 §P4-11).

The harness drives a **real running Central over a real socket**. Nothing here is
in-process or mocked: `fake_nodes.py` speaks the actual daemon WSS protocol including
the Ed25519 challenge, and `terminal_clients.py` opens the actual browser terminal
WebSocket with a real ws-ticket. What it fakes is only the *far side of the daemon* —
no tmux, no PTY — because that is what lets 100 nodes fit on one machine, and because
the real PTY behaviour is already covered by the P2/P3 integration tests.

Two deliberate choices worth stating:

* **Boundedness is asserted, not just reported.** Every scenario returns `Check`
  results with an explicit pass/fail, and the orchestrator exits non-zero if any
  fails. A harness that only prints numbers rots into decoration within one release.
* **Only `websockets` is used for the client side**, which arrives with
  `uvicorn[standard]` and is therefore already a backend dependency. Adding a load
  tool to the dependency set to measure the product would be its own regression.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:  # pragma: no cover - import shape differs across websockets versions
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # pragma: no cover
    from websockets.client import connect as ws_connect  # type: ignore[no-redef]

import urllib.error
import urllib.request

DOMAIN = b"cliora-node-auth-v1\n"
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass
class Check:
    """One boundedness or budget assertion, with the number it was judged on.

    `limit` and `observed` are recorded even when the check passes: a run that is
    barely inside its budget is information the next release needs, and a bare
    `"pass"` throws it away.
    """

    name: str
    requirement: str
    passed: bool
    observed: float | int | str
    limit: float | int | str
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "requirement": self.requirement,
            "status": "pass" if self.passed else "FAIL",
            "observed": self.observed,
            "limit": self.limit,
            "detail": self.detail,
        }


@dataclass
class Scenario:
    name: str
    checks: list[Check] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def check(
        self,
        name: str,
        requirement: str,
        *,
        passed: bool,
        observed: float | int | str,
        limit: float | int | str,
        detail: str = "",
    ) -> Check:
        result = Check(name, requirement, passed, observed, limit, detail)
        self.checks.append(result)
        return result

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_json(self) -> dict[str, Any]:
        return {
            "scenario": self.name,
            "status": "pass" if not self.failed else "FAIL",
            "checks": [c.to_json() for c in self.checks],
            "measurements": self.measurements,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# Distributions and process sampling
# --------------------------------------------------------------------------- #


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
    return ordered[k]


def distribution(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "p50_ms": round(percentile(values, 50), 3),
        "p95_ms": round(percentile(values, 95), 3),
        "p99_ms": round(percentile(values, 99), 3),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


class RssSampler:
    """Samples another process's resident set size from `/proc/<pid>/statm`.

    Reads the *Central* process rather than the harness, because the claim under test
    is that Central stays bounded under load — the harness's own footprint is
    irrelevant and would mask it. Linux-only by construction; a missing `/proc` is
    reported as an explicit note rather than silently producing zeros, since a
    memory-boundedness proof that quietly measured nothing is worse than none.
    """

    def __init__(self, pid: int | None, interval: float = 0.25) -> None:
        self.pid = pid
        self.interval = interval
        self.samples: list[float] = []
        self.available = pid is not None and Path(f"/proc/{pid}/statm").exists()
        self._task: asyncio.Task[None] | None = None
        self._page = os.sysconf("SC_PAGE_SIZE")

    def read_mib(self) -> float | None:
        if not self.available:
            return None
        try:
            fields = Path(f"/proc/{self.pid}/statm").read_text().split()
        except OSError:
            return None
        return int(fields[1]) * self._page / (1024 * 1024)

    async def _loop(self) -> None:
        while True:
            value = self.read_mib()
            if value is not None:
                self.samples.append(value)
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self.available:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"available": False}
        half = len(self.samples) // 2
        return {
            "available": True,
            "pid": self.pid,
            "samples": len(self.samples),
            "start_mib": round(self.samples[0], 1),
            "peak_mib": round(max(self.samples), 1),
            "final_mib": round(self.samples[-1], 1),
            # Growth across the two halves of the run. A queue that leaks shows up
            # here as a rising second half even when the peak looks acceptable.
            "first_half_mean_mib": round(sum(self.samples[:half]) / max(1, half), 1),
            "second_half_mean_mib": round(
                sum(self.samples[half:]) / max(1, len(self.samples) - half), 1
            ),
        }


# --------------------------------------------------------------------------- #
# Central HTTP client (stdlib; the harness must not depend on test-only extras)
# --------------------------------------------------------------------------- #


class CentralError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class Central:
    """Thin HTTP client for the endpoints the harness needs.

    Synchronous on purpose: the HTTP calls are setup and teardown, not the thing being
    measured. The measured paths (daemon WSS, terminal WSS) are all async.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method
        )
        if data is not None:
            request.add_header("content-type", "application/json")
        if auth and self.token:
            request.add_header("authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise CentralError(error.code, error.read().decode()) from None

    def login(self, username: str, password: str) -> None:
        body = self._request(
            "POST",
            "/api/auth/login",
            {"username": username, "password": password},
            auth=False,
        )
        self.token = body["tokens"]["access_token"]

    def enrollment_token(self, *, max_uses: int) -> str:
        body = self._request(
            "POST",
            "/api/enrollment-tokens",
            {"ttl_seconds": 3600, "max_uses": max_uses},
        )
        return body["token"]

    def register_node(
        self, token: str, *, name: str, public_key: str, roots: list[str]
    ) -> str:
        body = self._request(
            "POST",
            "/api/nodes/register",
            {
                "token": token,
                "name": name,
                "hostname": f"{name}.load",
                "os": "linux",
                "os_version": "6.0",
                "architecture": "amd64",
                "daemon_version": "0.0.0-load",
                "run_user": "agentd",
                "public_key": public_key,
                "runtimes": [{"runtime": "claude", "available": True}],
                "workspace_roots": [{"path": p, "is_enabled": True} for p in roots],
            },
            auth=False,
        )
        return body["node_id"]

    def create_session(
        self, node_id: str, *, name: str, workspace: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/sessions",
            {
                "node_id": node_id,
                "runtime": "claude",
                "name": name,
                "workspace": workspace,
                "rows": 24,
                "columns": 80,
            },
        )

    def terminate_session(self, session_id: str) -> None:
        """Stop a running session.

        `POST /terminate` ends it; `DELETE` only removes an *already ended* row and
        answers 409 for a running one. The harness used DELETE first and swallowed the
        409, so every churn cycle left its sessions running and the leak checks
        reported a leak that was entirely the harness's own doing.
        """
        self._request("POST", f"/api/sessions/{session_id}/terminate")

    def delete_session_row(self, session_id: str) -> None:
        self._request("DELETE", f"/api/sessions/{session_id}")

    def attach_ticket(self, session_id: str) -> str:
        return self._request("POST", f"/api/sessions/{session_id}/attach")["ticket"]

    def timed(self, method: str, path: str) -> tuple[float, Any]:
        """Wall-clock a read endpoint, for the NFR-001 page-level budgets."""
        started = time.perf_counter()
        body = self._request(method, path)
        return (time.perf_counter() - started) * 1000.0, body

    def ws_url(self, path: str) -> str:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}{path}"


def ssl_context_for(url: str) -> ssl.SSLContext | None:
    """Only used against a local https deployment; verification stays on."""
    return ssl.create_default_context() if url.startswith("wss://") else None


# --------------------------------------------------------------------------- #
# Protocol-level fake daemon
# --------------------------------------------------------------------------- #


def new_ulid_like() -> str:
    return "".join(ULID_ALPHABET[b % 32] for b in os.urandom(26))


def frame(type_: str, node_id: str, request_id: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": type_,
            "request_id": request_id,
            "node_id": node_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "success": True,
            "payload": payload,
        }
    )


def encode_binary(kind: int, session_id: str, payload: bytes) -> bytes:
    return bytes((1, kind)) + uuid.UUID(session_id).bytes + payload


def decode_binary(raw: bytes) -> tuple[int, str, bytes]:
    return raw[1], str(uuid.UUID(bytes=raw[2:18])), raw[18:]


@dataclass
class DaemonCounters:
    heartbeats_sent: int = 0
    requests_handled: int = 0
    sessions_started: int = 0
    sessions_stopped: int = 0
    unknown_requests: int = 0
    reconnects: int = 0
    # Browser -> daemon input frames. Only the writer's bytes may arrive, so this is
    # how the harness can assert that a flooding viewer produced no node traffic.
    inputs_received: int = 0


class FakeDaemon:
    """A daemon as far as Central can tell: real WSS, real Ed25519, no tmux.

    Handles the request types Central initiates during a load run and answers them
    with well-formed correlated responses. Anything unrecognised is counted rather
    than dropped silently — an unanswered request would look like a Central timeout
    and quietly invalidate the timeout measurements.
    """

    def __init__(
        self,
        central: Central,
        *,
        name: str,
        roots: list[str],
        heartbeat_interval: float = 5.0,
    ) -> None:
        self.central = central
        self.name = name
        self.roots = roots
        self.heartbeat_interval = heartbeat_interval
        self.private_key = Ed25519PrivateKey.generate()
        self.node_id: str = ""
        self.counters = DaemonCounters()
        self.sessions: set[str] = set()
        self.websocket: Any = None
        # Set by terminal scenarios: called with (session_id, payload) for each input
        # frame the browser sends, so a fake daemon can echo output back.
        self.on_input: Callable[[str, bytes], Awaitable[None]] | None = None
        self._stopping = False
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return base64.b64encode(raw).decode()

    def register_http(self, token: str) -> str:
        self.node_id = self.central.register_node(
            token, name=self.name, public_key=self.public_key_b64, roots=self.roots
        )
        return self.node_id

    def _sign(self, challenge_id: str, nonce: str) -> str:
        message = DOMAIN + f"{self.node_id}\n{challenge_id}\n{nonce}".encode()
        return base64.b64encode(self.private_key.sign(message)).decode()

    async def connect(self) -> None:
        url = self.central.ws_url(f"/ws/nodes/{self.node_id}")
        self.websocket = await ws_connect(
            url, ssl=ssl_context_for(url), max_size=8 * 1024 * 1024, open_timeout=30
        )
        challenge = json.loads(await self.websocket.recv())
        if challenge["type"] != "node.challenge":
            raise RuntimeError(f"expected node.challenge, got {challenge['type']}")
        challenge_id = challenge["request_id"]
        nonce = challenge["payload"]["nonce"]
        await self.websocket.send(
            frame(
                "node.auth",
                self.node_id,
                challenge_id,
                {
                    "challenge_id": challenge_id,
                    "signature": self._sign(challenge_id, nonce),
                },
            )
        )
        authenticated = json.loads(await self.websocket.recv())
        if authenticated["type"] != "node.authenticated":
            raise RuntimeError(f"auth rejected: {authenticated}")
        await self.websocket.send(
            frame(
                "node.register",
                self.node_id,
                new_ulid_like(),
                {
                    "name": self.name,
                    "hostname": f"{self.name}.load",
                    "os": "linux",
                    "os_version": "6.0",
                    "architecture": "amd64",
                    "daemon_version": "0.0.0-load",
                    "run_user": "agentd",
                    "runtimes": [{"runtime": "claude", "available": True}],
                    "workspace_roots": [
                        {"path": p, "is_enabled": True} for p in self.roots
                    ],
                },
            )
        )

    def start_serving(self) -> None:
        """Begin heartbeating and answering control requests in the background."""
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._control_loop()),
        ]

    async def _heartbeat_loop(self) -> None:
        while not self._stopping:
            try:
                await self.websocket.send(
                    frame(
                        "node.heartbeat",
                        self.node_id,
                        new_ulid_like(),
                        {
                            "active_sessions": len(self.sessions),
                            "resources": {
                                "cpu_usage": 5.0,
                                "memory_usage": 20.0,
                                "load_average": 0.5,
                                "disk_usage": 30.0,
                                "uptime_seconds": 60,
                            },
                        },
                    )
                )
                self.counters.heartbeats_sent += 1
            except Exception:  # noqa: BLE001 - the socket closing is a normal stop
                return
            await asyncio.sleep(self.heartbeat_interval)

    async def _control_loop(self) -> None:
        while not self._stopping:
            try:
                message = await self.websocket.recv()
            except Exception:  # noqa: BLE001 - normal on close
                return
            if isinstance(message, bytes):
                kind, session_id, payload = decode_binary(message)
                # kind 1 is browser -> daemon input. Echo it back as output so the
                # terminal scenario can measure a genuine round trip through both
                # relay legs rather than only the outbound half.
                if kind == 1:
                    self.counters.inputs_received += 1
                    if self.on_input is not None:
                        await self.on_input(session_id, payload)
                continue
            await self._handle_control(json.loads(message))

    async def _handle_control(self, message: dict[str, Any]) -> None:
        type_ = message.get("type")
        request_id = message.get("request_id", new_ulid_like())
        payload = message.get("payload", {})
        session_id = payload.get("session_id", "")
        self.counters.requests_handled += 1

        if type_ == "session.start":
            self.sessions.add(session_id)
            self.counters.sessions_started += 1
            await self._reply(
                "session.started", request_id, {"session_id": session_id, "pid": 4242}
            )
        elif type_ == "session.attach":
            await self._reply(
                "session.attached", request_id, {"session_id": session_id}
            )
        elif type_ == "session.stop":
            self.sessions.discard(session_id)
            self.counters.sessions_stopped += 1
            await self._reply(
                "session.stopped",
                request_id,
                {"session_id": session_id, "exit_code": 0},
            )
        elif type_ == "session.list":
            await self._reply(
                "session.list_result", request_id, {"sessions": sorted(self.sessions)}
            )
        elif type_ == "filesystem.list":
            await self._reply(
                "filesystem.entries",
                request_id,
                {
                    "session_id": session_id,
                    "entries": [],
                    "next_cursor": None,
                    "truncated": False,
                },
            )
        elif type_ in ("terminal.resize", "terminal.detach", "node.registered"):
            pass  # fire-and-forget from Central; nothing to answer
        else:
            self.counters.unknown_requests += 1

    async def _reply(
        self, type_: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        await self.websocket.send(frame(type_, self.node_id, request_id, payload))

    def silence(self) -> None:
        """Stop answering and stop heartbeating, without closing the socket.

        This is what a hung daemon looks like from Central: the connection is still
        established, so Central keeps treating it as live and keeps allocating pending
        slots — which is exactly the condition the pending bound exists for. Closing
        the socket instead would test the disconnect path, not the bound.
        """
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        self._tasks = []

    async def send_output(self, session_id: str, payload: bytes) -> None:
        await self.websocket.send(encode_binary(2, session_id, payload))

    async def stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:  # noqa: BLE001
                pass


async def bring_up_fleet(
    central: Central,
    *,
    nodes: int,
    roots: list[str],
    heartbeat_interval: float,
    concurrency: int = 25,
) -> list[FakeDaemon]:
    """Register and connect `nodes` fake daemons.

    Registration is HTTP and bounded in concurrency so the harness measures Central
    under a realistic connect rate rather than a thundering herd it would never see;
    the *steady-state* connection count is what NFR-003 is about.
    """
    token = central.enrollment_token(max_uses=nodes + 1)
    daemons = [
        FakeDaemon(
            central,
            name=f"load-{i:03d}",
            roots=roots,
            heartbeat_interval=heartbeat_interval,
        )
        for i in range(nodes)
    ]
    semaphore = asyncio.Semaphore(concurrency)

    async def start(daemon: FakeDaemon) -> None:
        async with semaphore:
            await asyncio.to_thread(daemon.register_http, token)
            await daemon.connect()

    await asyncio.gather(*(start(d) for d in daemons))
    for daemon in daemons:
        daemon.start_serving()
    return daemons


async def tear_down_fleet(daemons: list[FakeDaemon]) -> None:
    await asyncio.gather(*(d.stop() for d in daemons), return_exceptions=True)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def print_scenario(scenario: Scenario) -> None:
    print(f"\n=== {scenario.name} ===")
    for check in scenario.checks:
        mark = "ok  " if check.passed else "FAIL"
        print(f"  [{mark}] {check.name}: observed={check.observed} limit={check.limit}")
        if check.detail:
            print(f"         {check.detail}")
    for note in scenario.notes:
        print(f"  note: {note}")
