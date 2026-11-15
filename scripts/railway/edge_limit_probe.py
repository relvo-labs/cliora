"""Online nginx limits; use a disposable compose/staging stack, never a busy origin.

Run via verify-edge.sh --online BASE OUT. Requires admin credentials for 50 authenticated
node sockets. Public enrollment takes about five minutes at the approved 10 r/min.
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
from contextlib import AsyncExitStack
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
        return exc.code, {}


async def connection_cap() -> None:
    code, data = request(
        SETUP,
        "/api/auth/login",
        {
            "username": os.environ["CLIORA_VERIFY_ADMIN"],
            "password": os.environ["CLIORA_VERIFY_PASSWORD"],
        },
    )
    assert code == 200, f"admin login: HTTP {code}"
    token = data["tokens"]["access_token"]
    code, data = request(
        SETUP, "/api/enrollment-tokens", {"ttl_seconds": 600, "max_uses": 50}, token
    )
    assert code == 201, f"enrollment token: HTTP {code}"
    enrollment = data["token"]
    enrollment_id = data["id"]
    nodes: list[str] = []
    sockets = []
    parts = urlsplit(BASE)
    ws_base = f"{'wss' if parts.scheme == 'https' else 'ws'}://{parts.netloc}"
    options = {"ssl": CONTEXT} if parts.scheme == "https" else {}
    started = time.monotonic()
    try:
        async with AsyncExitStack() as stack:
            for index in range(50):
                # A public setup route must respect the register budget too.
                if index and SETUP == BASE:
                    await asyncio.sleep(6.1)
                key = Ed25519PrivateKey.generate()
                public = base64.b64encode(
                    key.public_key().public_bytes(
                        serialization.Encoding.Raw, serialization.PublicFormat.Raw
                    )
                ).decode()
                code, data = request(
                    SETUP,
                    "/api/nodes/register",
                    {
                        "token": enrollment,
                        "name": f"edge-cap-{index}",
                        "hostname": "edge.probe",
                        "os": "linux",
                        "os_version": "0",
                        "architecture": "amd64",
                        "daemon_version": "0.0.0-probe",
                        "run_user": "agentd",
                        "public_key": public,
                        "runtimes": [],
                        "workspace_roots": [],
                    },
                )
                assert code == 201, f"register {index}: HTTP {code}"
                node = data["node_id"]
                nodes.append(node)
                socket = await stack.enter_async_context(
                    connect(
                        f"{ws_base}/ws/nodes/{node}",
                        open_timeout=10,
                        ping_interval=None,
                        **options,
                    )
                )
                challenge = json.loads(await asyncio.wait_for(socket.recv(), 5))
                assert challenge["type"] == "node.challenge", challenge["type"]
                ident, nonce = challenge["request_id"], challenge["payload"]["nonce"]
                signature = base64.b64encode(
                    key.sign(b"cliora-node-auth-v1\n" + f"{node}\n{ident}\n{nonce}".encode())
                ).decode()
                await socket.send(
                    json.dumps(
                        {
                            "version": 1,
                            "type": "node.auth",
                            "request_id": ident,
                            "node_id": node,
                            "timestamp": "2026-01-01T00:00:00Z",
                            "payload": {"challenge_id": ident, "signature": signature},
                        }
                    )
                )
                authenticated = json.loads(await asyncio.wait_for(socket.recv(), 5))
                assert authenticated["type"] == "node.authenticated", authenticated["type"]
                assert all(item.state.name == "OPEN" for item in sockets), "earlier socket closed"
                sockets.append(socket)
                if (index + 1) % 5 == 0:
                    print(f"progress: {index + 1}/50 authenticated sockets", flush=True)
            try:
                async with connect(f"{ws_base}/ws/nodes/{nodes[0]}", open_timeout=10, **options):
                    raise AssertionError("51st connection was admitted")
            except InvalidStatus as exc:
                assert exc.response.status_code == 429, f"cap HTTP {exc.response.status_code}"
            assert all(item.state.name == "OPEN" for item in sockets), "earlier socket closed"
            for item in sockets:
                pong = await item.ping()
                await asyncio.wait_for(pong, 5)
            # Terminal WS must still reach Central despite 50 node sockets.
            async with connect(
                f"{ws_base}/ws/sessions/{nodes[0]}/terminal", open_timeout=10, **options
            ) as terminal:
                await asyncio.wait_for(terminal.wait_closed(), 5)
                assert terminal.close_code == 1008, terminal.close_code
            print(
                f"ok: 50 authenticated node sockets; 51st HTTP 429; terminal unaffected "
                f"({time.monotonic() - started:.1f}s)",
                flush=True,
            )
    finally:
        cleanup_failures = []
        for node in nodes:
            code, _ = request(SETUP, f"/api/nodes/{node}", token=token, method="DELETE")
            if code not in (200, 204):
                cleanup_failures.append(f"node cleanup: HTTP {code}")
        code, _ = request(
            SETUP,
            f"/api/enrollment-tokens/{enrollment_id}",
            token=token,
            method="DELETE",
        )
        if code != 204:
            cleanup_failures.append(f"enrollment cleanup: HTTP {code}")
        assert not cleanup_failures, cleanup_failures


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
    first, _ = request(BASE, "/api/nodes/register", method="GET")
    second, _ = request(BASE, "/api/nodes/register", method="GET")
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
