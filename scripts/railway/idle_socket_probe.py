"""Hold an authenticated, idle daemon socket open through the deployed edge (RW-10).

Two lessons from `scripts/p4/verify-edge.sh` are baked in, because without them this check
passes while measuring nothing:

1. **The socket must be authenticated.** An unauthenticated one closes at exactly 30 s —
   `hmac_challenge_ttl_seconds`, i.e. *Central* timing out a node that never answered its
   challenge. That measures Central and reads as a proxy failure.
2. **The client must send no pings.** Keepalive frames reset the proxy's read timeout, so a
   pinging client passes at any timeout value. `ping_interval=None`.

It really does enroll a node, because that is the only way to get an authenticated socket. So
it cleans up after itself: the node is removed on the way out, in a `finally`, and the
enrollment token is minted with a 10-minute TTL and a single use so an aborted run cannot
leave a usable credential behind.

    VERIFY_BASE=https://cliora.example.com VERIFY_ADMIN=admin VERIFY_PASSWORD=… \
    VERIFY_IDLE=90 python scripts/railway/idle_socket_probe.py

Prints one line: `SURVIVED …` on success, anything else on failure, and exits non-zero.
Never prints a token, a signature or the password.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    from websockets.asyncio.client import connect
except ImportError:  # websockets < 13
    from websockets.client import connect

BASE = os.environ["VERIFY_BASE"].rstrip("/")
IDLE = float(os.environ.get("VERIFY_IDLE", "90"))
SIGNING_DOMAIN = b"cliora-node-auth-v1\n"
NODE_NAME = f"verify-idle-{uuid.uuid4().hex[:8]}"


def _request(method: str, path: str, body: dict | None, token: str | None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data is not None:
        request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = response.read()
    return json.loads(payload) if payload else {}


def main() -> int:
    try:
        access = _request(
            "POST",
            "/api/auth/login",
            {"username": os.environ["VERIFY_ADMIN"], "password": os.environ["VERIFY_PASSWORD"]},
            None,
        )["tokens"]["access_token"]
    except urllib.error.HTTPError as exc:
        print(f"LOGIN-FAILED HTTP {exc.code} (check VERIFY_ADMIN / VERIFY_PASSWORD)")
        return 2

    enrollment = _request(
        "POST", "/api/enrollment-tokens", {"ttl_seconds": 600, "max_uses": 1}, access
    )["token"]

    key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    ).decode()
    node_id = _request(
        "POST",
        "/api/nodes/register",
        {
            "token": enrollment,
            "name": NODE_NAME,
            "hostname": "verify.probe",
            "os": "linux",
            "os_version": "0.0",
            "architecture": "amd64",
            "daemon_version": "0.0.0-verify",
            "run_user": "agentd",
            "public_key": public_key,
            "runtimes": [],
            "workspace_roots": [],
        },
        None,
    )["node_id"]

    try:
        return asyncio.run(_hold(node_id, key))
    finally:
        # The probe must not leave a node behind on a real deployment. Failure to clean up is
        # reported but does not change the verdict of the check itself.
        try:
            _request("DELETE", f"/api/nodes/{node_id}", None, access)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"CLEANUP-FAILED could not remove probe node {NODE_NAME}: {exc}")


async def _hold(node_id: str, key: Ed25519PrivateKey) -> int:
    parts = urlsplit(BASE)
    scheme = "wss" if parts.scheme == "https" else "ws"
    url = f"{scheme}://{parts.netloc}/ws/nodes/{node_id}"
    # Verification is on: this runs against a real deployment with a real certificate. The
    # self-signed exception that the compose-edge check needs has no place here.
    context = ssl.create_default_context() if scheme == "wss" else None

    async with connect(url, ssl=context, open_timeout=30, ping_interval=None) as socket:
        challenge = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if challenge.get("type") != "node.challenge":
            print(f"UNEXPECTED-FIRST-FRAME {challenge.get('type')}")
            return 1
        challenge_id, nonce = challenge["request_id"], challenge["payload"]["nonce"]
        signature = base64.b64encode(
            key.sign(SIGNING_DOMAIN + f"{node_id}\n{challenge_id}\n{nonce}".encode())
        ).decode()
        await socket.send(
            json.dumps(
                {
                    "version": 1,
                    "type": "node.auth",
                    "request_id": challenge_id,
                    "node_id": node_id,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {"challenge_id": challenge_id, "signature": signature},
                }
            )
        )
        authenticated = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if authenticated.get("type") != "node.authenticated":
            print(f"AUTH-REJECTED {authenticated.get('type')}")
            return 1

        # Go silent. Central's control loop waits without a timeout once authenticated, so
        # anything that closes this connection is on the network path.
        started = time.monotonic()
        try:
            await asyncio.wait_for(socket.recv(), timeout=IDLE)
            print("UNEXPECTED-FRAME received while idle")
            return 1
        except asyncio.TimeoutError:
            pass
        except Exception as error:
            print(f"CLOSED after {time.monotonic() - started:.1f}s idle: {type(error).__name__}")
            return 1

        try:
            await asyncio.wait_for(socket.ping(), timeout=10)
        except Exception as error:
            print(f"DEAD after {time.monotonic() - started:.1f}s idle: {type(error).__name__}")
            return 1
        print(f"SURVIVED {time.monotonic() - started:.1f}s fully idle and still responsive")
        return 0


if __name__ == "__main__":
    sys.exit(main())
