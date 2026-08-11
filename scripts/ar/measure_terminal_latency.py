"""Interactive-terminal echo latency, p50/p95 over 50 samples (plan/18 AR-00).

The sixth baseline, and the one V2.1 did not need. V2.2 puts a **continuous** log
stream on the same node WebSocket that carries interactive terminal bytes — the
`raw_bytes` branch and the `run.*` branches live in the same `while` loop in
`api/ws/nodes.py` (`plan/18/00-…md` D3). The risk that buys is "running an Agent
makes the terminal feel laggy", and a feeling is not evidence. This is the number
that turns it into one.

What is measured is the whole round trip a person actually waits on:

    browser socket → Central relay → node WSS → daemon → tmux pty → the CLI
             → back out the same path → browser socket

against the e2e stack's `fakecli`, which echoes each line it reads. Not a
microbenchmark of any one hop: the claim being protected is about the felt latency
of the whole chain, so the instrument has to span the whole chain.

    scripts/e2e/run-stack.sh python scripts/ar/measure_terminal_latency.py \
        --out artifacts/ar/local/baseline/terminal-latency.json

Run it inside `run-stack.sh` so the stack's node, workspace and admin credentials
are the ones already standing. Re-run it during AR-07 with a run streaming at full
rate on the same node and compare: the exit condition is that p95 does not regress
by more than 20% against this file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# One dependency the repo already has (Central's own test client stack). Imported
# lazily inside main() so `--help` works outside the backend virtualenv.
WS_IMPORT_HINT = (
    "run under `uv run --project backend python …` so `websockets` is importable"
)

# Prefixed so a leftover from an aborted attempt is recognisable and reclaimable.
SESSION_NAME = "ar-00 terminal latency baseline"


def _post(
    base: str, path: str, body: dict[str, Any], token: str | None = None
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            **({"authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # Central answers with a coded error body; without it a 409 here is just a
        # number, and the two plausible causes (capacity, and a runtime the node does
        # not offer) need different fixes.
        raise SystemExit(
            f"POST {path} → {exc.code}: {exc.read().decode(errors='replace')}"
        ) from exc


def _get(base: str, path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"{base}{path}", headers={"authorization": f"Bearer {token}"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


async def _measure(
    base: str, token: str, session_id: str, samples: int, ready_timeout: float
) -> list[float]:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(f"{exc}: {WS_IMPORT_HINT}") from exc

    ticket = _post(base, f"/api/sessions/{session_id}/attach", {}, token)["ticket"]
    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    url = f"{ws_base}/ws/sessions/{session_id}/terminal?ticket={ticket}"

    latencies: list[float] = []
    async with websockets.connect(url, max_size=None) as socket:
        # Wait for the runtime to be up before timing anything. `fakecli` prints
        # FAKECLI_READY once its pty exists; timing a keystroke sent before that
        # would measure process startup, not echo latency.
        deadline = time.monotonic() + ready_timeout
        buffer = b""
        while b"FAKECLI_READY" not in buffer:
            if time.monotonic() > deadline:
                raise SystemExit(
                    "the runtime never announced itself; saw: " + repr(buffer[-400:])
                )
            frame = await asyncio.wait_for(
                socket.recv(), timeout=max(0.1, deadline - time.monotonic())
            )
            if isinstance(frame, bytes):
                buffer += frame

        # FAKECLI_READY is printed before tmux has finished painting the alternate
        # screen and before the daemon's first resize lands, and a keystroke sent into
        # that window is simply lost — the first attempt at this measured a 30-second
        # timeout instead of a latency. Wait for the output to go quiet, then spend one
        # uncounted round trip proving the input path is live.
        while True:
            try:
                await asyncio.wait_for(socket.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                break

        for index in range(-1, samples):
            # A unique marker per sample: the pty echoes the keystrokes *and* fakecli
            # writes the line back, so "the first output after I typed" is ambiguous.
            # Waiting for a token that cannot appear before this sample is not.
            marker = f"ARLAT{index:03d}{uuid.uuid4().hex[:8]}".upper()
            buffer = b""
            started = time.perf_counter()
            await socket.send(f"{marker}\r".encode())
            while buffer.count(marker.encode()) < 2:
                # Twice: once from the pty's own echo of the typed line, once from
                # fakecli writing it back. The second is the full round trip.
                frame = await asyncio.wait_for(socket.recv(), timeout=30)
                if isinstance(frame, bytes):
                    buffer += frame
            if index >= 0:  # index -1 is the warm-up
                latencies.append((time.perf_counter() - started) * 1000.0)
    return latencies


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    # Nearest-rank. With 50 samples the interpolation choice moves p95 by well under
    # the 20% regression threshold this file exists to support, and nearest-rank has
    # the property that the number reported is a measurement that actually happened.
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", default=f"http://127.0.0.1:{os.environ.get('CENTRAL_PORT', '8000')}"
    )
    parser.add_argument(
        "--username", default=os.environ.get("E2E_ADMIN_USER", "e2e-admin")
    )
    parser.add_argument(
        "--password", default=os.environ.get("E2E_ADMIN_PASSWORD", "e2e-admin-pw")
    )
    parser.add_argument("--workspace", default=os.environ.get("E2E_WORKSPACE_ROOT", ""))
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument(
        "--out", type=Path, help="write the JSON here as well as to stdout"
    )
    args = parser.parse_args()

    try:
        tokens = _post(
            args.base,
            "/api/auth/login",
            {"username": args.username, "password": args.password},
        )
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"cannot reach Central at {args.base}: {exc}. Run this inside scripts/e2e/run-stack.sh."
        )
    token = tokens["tokens"]["access_token"]

    nodes = [
        node
        for node in _get(args.base, "/api/nodes", token)
        if node.get("status") == "online"
    ]
    if not nodes:
        raise SystemExit("no online node; run this inside scripts/e2e/run-stack.sh")
    node = nodes[0]
    workspace = args.workspace or (node.get("allowed_roots") or [{}])[0].get("path", "")
    if not workspace:
        raise SystemExit("no workspace root to open a session in; pass --workspace")

    # Terminate leftovers from an earlier attempt before creating another. The e2e
    # database outlives a single run of the stack, and the per-user session limit is
    # low enough that two aborted attempts make the third fail with a 409 that reads
    # like a capacity problem rather than like litter.
    for existing in _get(args.base, "/api/sessions", token) or []:
        if (
            str(existing.get("name", "")).startswith(SESSION_NAME)
            and existing.get("status") != "terminated"
        ):
            try:
                _post(args.base, f"/api/sessions/{existing['id']}/terminate", {}, token)
            except SystemExit:
                pass

    created = _post(
        args.base,
        "/api/sessions",
        {
            "node_id": node["id"],
            "runtime": "claude",
            "name": SESSION_NAME,
            "workspace": workspace,
            "rows": 24,
            "columns": 80,
        },
        token,
    )
    session_id = created["id"]
    try:
        latencies = asyncio.run(
            _measure(args.base, token, session_id, args.samples, args.ready_timeout)
        )
    finally:
        try:
            _post(args.base, f"/api/sessions/{session_id}/terminate", {}, token)
        except urllib.error.URLError:
            pass

    report = {
        "measurement": "M-AR-0 interactive terminal echo latency (plan/18 AR-00)",
        "unit": "milliseconds",
        "samples": len(latencies),
        "p50": round(_percentile(latencies, 0.50), 3),
        "p95": round(_percentile(latencies, 0.95), 3),
        "min": round(min(latencies), 3),
        "max": round(max(latencies), 3),
        "mean": round(statistics.fmean(latencies), 3),
        "raw_ms": [round(value, 3) for value in latencies],
        "runtime": "fakecli via tmux (scripts/e2e/run-stack.sh)",
        "note": (
            "Round trip browser socket → Central → node WSS → daemon → tmux → CLI and back. "
            "AR-07 re-runs this with a run streaming log_chunk frames on the same node; the "
            "exit condition is p95 no more than 20% above the value here."
        ),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
