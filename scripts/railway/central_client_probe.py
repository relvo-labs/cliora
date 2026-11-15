"""Correlate harmless requests with Central's private uvicorn HTTP/WS client-scope logs.

No new server endpoint or credentials: HTTP reaches an unknown API path; node WS receives
its public challenge and disconnects without authenticating. The existing uvicorn logs
contain the client after proxy-header middleware. Receipts alone are not acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect


def verify(receipt: dict, log: str) -> None:
    expected = ipaddress.ip_address(receipt["expected_ip"])
    probes = receipt["probes"]
    if {probe["protocol"] for probe in probes} != {"http", "websocket"} or any(
        sum(probe["protocol"] == kind for probe in probes) != 3 for kind in ("http", "websocket")
    ):
        raise ValueError("receipt must contain three HTTP and three WebSocket probes")
    for probe in probes:
        method = "GET" if probe["protocol"] == "http" else "WebSocket"
        pattern = re.compile(
            r'(?P<client>[0-9a-fA-F:.]+):[0-9]+ - "'
            + method
            + " "
            + re.escape(probe["path"])
            + (r' HTTP/[0-9.]+"' if method == "GET" else '"')
        )
        clients = [match["client"] for match in pattern.finditer(log)]
        if not clients:
            raise ValueError(f"missing Central {probe['protocol']} scope log for {probe['path']}")
        if any(ipaddress.ip_address(client) != expected for client in clients):
            raise ValueError(f"Central {probe['protocol']} saw {clients}, expected {expected}")


def http_status(request: urllib.request.Request, context: ssl.SSLContext) -> int:
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        return status


async def send(base: str, expected: str) -> dict:
    # Validate and normalize the independent expected value before sending anything.
    expected = str(ipaddress.ip_address(expected))
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        raise ValueError("base must be an HTTP(S) origin")
    context = ssl.create_default_context()
    if os.environ.get("CLIORA_VERIFY_INSECURE") == "1":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # opt-in self-signed local Compose only
    probes = []
    for forged in ("", "203.0.113.59", "198.51.100.59"):
        headers = {"X-Forwarded-For": f"{forged}, 192.0.2.59", "X-Real-IP": forged}
        ident = str(uuid.uuid4())
        http_path = f"/api/edge-client-probe/{ident}"
        request = urllib.request.Request(base.rstrip("/") + http_path, headers=headers)
        status = await asyncio.to_thread(http_status, request, context)
        if status != 404:
            raise ValueError(f"HTTP probe expected Central 404, got {status}")
        probes.append({"protocol": "http", "path": http_path})
        ws_path = f"/ws/nodes/{ident}"
        ws_url = f"{'wss' if parts.scheme == 'https' else 'ws'}://{parts.netloc}{ws_path}"
        options = {"ssl": context} if parts.scheme == "https" else {}
        async with connect(
            ws_url,
            additional_headers=headers,
            open_timeout=15,
            close_timeout=5,
            ping_interval=None,
            **options,
        ) as socket:
            first = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if first.get("type") != "node.challenge":
                raise ValueError("WS probe did not reach Central's node challenge")
        probes.append({"protocol": "websocket", "path": ws_path})
    return {"base": base, "expected_ip": expected, "probes": probes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("send")
    generate.add_argument("base")
    generate.add_argument("expected_ip")
    generate.add_argument("receipt", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("receipt", type=Path)
    check.add_argument("central_log", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "send":
            receipt = asyncio.run(send(args.base, args.expected_ip))
            args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
            print(f"PENDING: six probes sent; verify {args.receipt} against Central's private logs")
        else:
            verify(json.loads(args.receipt.read_text()), args.central_log.read_text())
            print(
                "ok: Central HTTP and WebSocket client scope matches independent egress (6 probes)"
            )
    except (ValueError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
