"""Online nginx limits; use a disposable compose/staging stack, never a busy origin.

Run via verify-edge.sh --online BASE OUT. Requires admin credentials for 51 enrollments
and 50 authenticated, registered, heartbeating node sockets. Public enrollment takes about
five minutes at the approved 10 r/min.
EDGE_SETUP_BASE may use a private Central tunnel for setup; WS always uses the edge.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

BASE = os.environ["EDGE_BASE"].rstrip("/")
SETUP = os.environ.get("EDGE_SETUP_BASE", BASE).rstrip("/")
CONTEXT = ssl.create_default_context()
if os.environ.get("CLIORA_VERIFY_INSECURE") == "1":
    CONTEXT.check_hostname = False
    CONTEXT.verify_mode = ssl.CERT_NONE  # only the local self-signed compose probe


def request(
    base: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    method: str | None = None,
) -> tuple[int, dict]:
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path,
        headers=headers,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, context=CONTEXT, timeout=20) as response:
            data = response.read()
            return response.status, json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, {}


HEARTBEAT_INTERVAL_SECONDS = 5.0


def frame(kind: str, node: str, payload: dict) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": kind,
            "request_id": "".join(
                "0123456789ABCDEFGHJKMNPQRSTVWXYZ"[b % 32] for b in os.urandom(26)
            ),
            "node_id": node,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": payload,
        }
    )


async def authenticate_and_register(
    socket, node: str, key: Ed25519PrivateKey, payload: dict
) -> None:
    challenge = json.loads(await asyncio.wait_for(socket.recv(), 5))
    assert challenge["type"] == "node.challenge", challenge["type"]
    ident, nonce = challenge["request_id"], challenge["payload"]["nonce"]
    signature = base64.b64encode(
        key.sign(b"cliora-node-auth-v1\n" + f"{node}\n{ident}\n{nonce}".encode())
    ).decode()
    auth = json.loads(frame("node.auth", node, {"challenge_id": ident, "signature": signature}))
    auth["request_id"] = ident
    await socket.send(json.dumps(auth))
    authenticated = json.loads(await asyncio.wait_for(socket.recv(), 5))
    assert authenticated["type"] == "node.authenticated", authenticated["type"]
    registration = frame("node.register", node, payload)
    await socket.send(registration)
    registered = json.loads(await asyncio.wait_for(socket.recv(), 10))
    # Central commits registration before this acknowledgement, releasing the auth
    # transaction/connection (#183). Do not open the next socket until it arrives.
    assert (
        registered.get("type") == "node.registered"
        and registered.get("request_id") == json.loads(registration)["request_id"]
        and registered.get("node_id") == node
        and registered.get("payload", {}).get("node_id") == node
    ), "invalid node.registered acknowledgement"


@asynccontextmanager
async def keeping_alive(active):
    sent = {}
    ready = asyncio.Event()

    async def heartbeat() -> None:
        while True:
            for node, socket in list(active):
                await asyncio.wait_for(
                    socket.send(
                        frame(
                            "node.heartbeat",
                            node,
                            {
                                "daemon_version": "0.0.0-probe",
                                "active_sessions": 0,
                            },
                        )
                    ),
                    5,
                )
                sent[node] = sent.get(node, 0) + 1
                if len(sent) == 50:
                    ready.set()
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    task = asyncio.create_task(heartbeat(), name="edge-limit-heartbeats")
    try:
        yield sent, ready
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def connection_cap() -> None:
    code, data = await asyncio.to_thread(
        request,
        SETUP,
        "/api/auth/login",
        {
            "username": os.environ["CLIORA_VERIFY_ADMIN"],
            "password": os.environ["CLIORA_VERIFY_PASSWORD"],
        },
    )
    assert code == 200, f"admin login: HTTP {code}"
    token = data["tokens"]["access_token"]
    code, data = await asyncio.to_thread(
        request, SETUP, "/api/enrollment-tokens", {"ttl_seconds": 600, "max_uses": 51}, token
    )
    assert code == 201, f"enrollment token: HTTP {code}"
    enrollment, enrollment_id = data["token"], data["id"]
    nodes = []
    active = []
    parts = urlsplit(BASE)
    ws_base = f"{'wss' if parts.scheme == 'https' else 'ws'}://{parts.netloc}"
    options = {"ssl": CONTEXT} if parts.scheme == "https" else {}
    started = time.monotonic()
    try:
        # Enroll the rejected candidate too, so the 51st handshake names a real node.
        # Provision before opening sockets; public setup respects the register budget.
        for index in range(51):
            if index and SETUP == BASE:
                await asyncio.sleep(6.1)
            key = Ed25519PrivateKey.generate()
            public = base64.b64encode(
                key.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ).decode()
            payload = {
                "name": f"edge-cap-{index}",
                "hostname": "edge.probe",
                "os": "linux",
                "os_version": "0",
                "architecture": "amd64",
                "daemon_version": "0.0.0-probe",
                "run_user": "agentd",
                "runtimes": [],
                "workspace_roots": [],
            }
            code, data = await asyncio.to_thread(
                request,
                SETUP,
                "/api/nodes/register",
                {
                    **payload,
                    "token": enrollment,
                    "public_key": public,
                },
            )
            assert code == 201, f"enroll {index}: HTTP {code}"
            nodes.append((data["node_id"], key, payload))
        print("ok: 51 distinct probe nodes enrolled", flush=True)
        async with AsyncExitStack() as stack:
            async with keeping_alive(active) as (heartbeats, ready):
                for index, (node, key, payload) in enumerate(nodes[:50]):
                    socket = await stack.enter_async_context(
                        connect(
                            f"{ws_base}/ws/nodes/{node}",
                            open_timeout=10,
                            close_timeout=5,
                            ping_interval=None,
                            **options,
                        )
                    )
                    await authenticate_and_register(socket, node, key, payload)
                    active.append((node, socket))
                    assert all(item.state.name == "OPEN" for _, item in active), (
                        "earlier socket closed"
                    )
                    if (index + 1) % 5 == 0:
                        print(
                            f"progress: {index + 1}/50 authenticated and registered sockets",
                            flush=True,
                        )
                # Prove each node remains a live protocol participant, not just an open TCP socket.
                await asyncio.wait_for(ready.wait(), 10)
                assert len(heartbeats) == 50, "not every registered node sent a heartbeat"
                try:
                    async with connect(
                        f"{ws_base}/ws/nodes/{nodes[50][0]}",
                        open_timeout=10,
                        close_timeout=5,
                        **options,
                    ):
                        raise AssertionError("51st connection was admitted")
                except InvalidStatus as exc:
                    assert exc.response.status_code == 429, f"cap HTTP {exc.response.status_code}"
                assert all(item.state.name == "OPEN" for _, item in active), "earlier socket closed"
                for _, item in active:
                    pong = await item.ping()
                    await asyncio.wait_for(pong, 5)
                async with connect(
                    f"{ws_base}/ws/sessions/{nodes[0][0]}/terminal",
                    open_timeout=10,
                    close_timeout=5,
                    **options,
                ) as terminal:
                    await asyncio.wait_for(terminal.wait_closed(), 5)
                    assert terminal.close_code == 1008, terminal.close_code
            # Heartbeat task is cancelled/awaited before the exit stack closes all sockets.
        print(
            f"ok: 50 authenticated/registered/heartbeating node sockets; 51st HTTP 429; "
            f"terminal unaffected ({time.monotonic() - started:.1f}s)",
            flush=True,
        )
    finally:
        cleanup_failures = []
        for node, _, _ in nodes:
            try:
                code, _ = await asyncio.to_thread(
                    request, SETUP, f"/api/nodes/{node}", token=token, method="DELETE"
                )
                if code not in (200, 204):
                    cleanup_failures.append(f"node cleanup: HTTP {code}")
            except Exception as exc:
                cleanup_failures.append(f"node cleanup: {type(exc).__name__}")
        try:
            code, _ = await asyncio.to_thread(
                request,
                SETUP,
                f"/api/enrollment-tokens/{enrollment_id}",
                token=token,
                method="DELETE",
            )
            if code != 204:
                cleanup_failures.append(f"enrollment cleanup: HTTP {code}")
        except Exception as exc:
            cleanup_failures.append(f"enrollment cleanup: {type(exc).__name__}")
        assert not cleanup_failures, cleanup_failures
        print(
            f"ok: {len(nodes)} probe nodes removed; enrollment revoked; "
            "sockets and heartbeat task closed",
            flush=True,
        )


async def http_limits() -> None:
    # Wrong-method requests avoid application login failure accounting and expensive hashes.
    # Run concurrently so the 6-second refill cannot conceal a missing burst cap.
    for endpoint in ("login", "refresh"):
        results = await asyncio.gather(
            *(
                asyncio.to_thread(request, BASE, f"/api/auth/{endpoint}", method="GET")
                for _ in range(20)
            )
        )
        codes = [code for code, _ in results]
        assert 405 in codes and 429 in codes, f"{endpoint} burst: {codes}"
        assert all(code in (405, 429) for code in codes), codes
        print(f"ok: {endpoint} burst -> 429 ({codes.count(405)} admitted)", flush=True)
    # GET also matches authenticated /api/nodes/{node_id}; OPTIONS has no handler.
    first, _ = request(BASE, "/api/nodes/register", method="OPTIONS")
    second, _ = request(BASE, "/api/nodes/register", method="OPTIONS")
    assert (first, second) == (405, 429), f"register cap: {first}, {second}"
    for _ in range(20):
        code, _ = request(BASE, "/api/releases/manifest")
        assert code == 200, f"generic API unexpectedly limited: {code}"
    print("ok: register -> 429; 20 generic API requests remain unlimited", flush=True)


async def main() -> None:
    await connection_cap()
    # Let the last register request leave its no-burst bucket before asserting HTTP limits.
    await asyncio.sleep(6.1)
    await http_limits()


if __name__ == "__main__":
    asyncio.run(main())
