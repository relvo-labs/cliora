"""P3 filesystem relay latency harness (P3-10, plan/04/07 §3).

Measures the *Central* leg of the two P3 NFRs — directory listing < 2 s and
≤2 MB preview < 3 s (ADR 0015) — over the real code path: mint a request_id,
park a Future in the node's correlation table, encode the request frame, decode
the daemon's response through the production codec, and serialize the response
body the way the HTTP layer does. Nothing is mocked except the socket, which is
replaced by an in-process daemon stub that answers with realistic payloads
(2000-entry listings, a 2 MiB preview, a 200-hit search result).

The daemon leg is measured separately by
``go test ./internal/files -run TestFilesystemLatencyBudget`` (real os.Root
confinement + policy + bounded read); ``docs/p3-report.md`` sums the two legs
against the NFR.

Also covers the bounds this phase must prove: relay timeout cleanup, cancel
cleanup, node-disconnect cleanup, and the per-node pending bound (NODE_BUSY) —
each asserted to leave no pending entry behind.

Run:  ``cd backend && uv run --project . python perf/files_bench.py``
Knobs: ``--entries --preview-mib --search-results --iterations --out``.
Exits non-zero if a latency budget or a bounds invariant fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# Make the backend package importable when run as a bare script.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.errors import ApiError  # noqa: E402
from app.protocol import decode_control  # noqa: E402
from app.services.registry import NodeConnectionRegistry  # noqa: E402

# Central-leg budgets in milliseconds. Deliberately a small fraction of the
# end-to-end NFR: the daemon leg and the network own the rest.
LIST_BUDGET_MS = 300.0
READ_BUDGET_MS = 400.0
SEARCH_BUDGET_MS = 300.0


def _entry(index: int) -> dict[str, Any]:
    return {
        "name": f"file_{index:05d}.py",
        "rel_path": f"src/file_{index:05d}.py",
        "type": "file",
        "size": 2048,
        "modified_at": "2026-07-25T00:00:00Z",
        "hidden": False,
        "symlink": False,
        "excluded": False,
        "expandable": False,
    }


class DaemonStub:
    """Stands in for the node's WebSocket: answers every correlated request
    immediately with a realistic payload, through the real codec."""

    def __init__(
        self, registry: NodeConnectionRegistry, node_id: uuid.UUID, replies: dict[str, dict]
    ):
        self._registry = registry
        self._node_id = node_id
        self._replies = replies
        self.sent = 0
        # When set, requests are swallowed (used for the timeout/cancel passes).
        self.silent = False

    async def send_text(self, frame: str) -> None:
        self.sent += 1
        if self.silent:
            return
        request = json.loads(frame)
        reply_type, payload = self._replies[request["type"]]
        response = json.dumps(
            {
                "version": 1,
                "type": reply_type,
                "request_id": request["request_id"],
                "node_id": str(self._node_id),
                "timestamp": "2026-07-25T00:00:00Z",
                "success": True,
                "payload": payload,
            }
        )
        # Decode through the production codec, exactly as the ws handler does.
        message = decode_control(response)
        self._registry.resolve_response(self._node_id, message)

    async def send_bytes(self, frame: bytes) -> None:  # pragma: no cover - unused
        self.sent += 1


def _percentile(samples: list[float], quantile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(quantile * (len(ordered) - 1)))
    return ordered[index]


async def _measure(
    label: str,
    budget_ms: float,
    iterations: int,
    call: Any,
) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        payload = await call()
        # The HTTP layer serializes the payload it returns; that cost is part of
        # the user-visible latency, so it is measured too.
        json.dumps(payload)
        samples.append((time.perf_counter() - started) * 1000)
    result = {
        "name": label,
        "iterations": iterations,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
        "budget_ms": budget_ms,
    }
    result["ok"] = result["p95_ms"] < budget_ms
    return result


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    node_id = uuid.uuid4()
    session_id = uuid.uuid4()
    registry = NodeConnectionRegistry()
    preview = "const answer = 42;\n" * ((args.preview_mib * 1024 * 1024) // 19)
    replies = {
        "filesystem.list": (
            "filesystem.entries",
            {
                "path": "src",
                "entries": [_entry(i) for i in range(args.entries)],
                "truncated": True,
                "next_cursor": str(args.entries),
            },
        ),
        "filesystem.read": (
            "filesystem.content",
            {
                "success": True,
                "rel_path": "src/large.ts",
                "size": len(preview),
                "modified_at": "2026-07-25T00:00:00Z",
                "encoding": "utf-8",
                "language_hint": "typescript",
                "content": preview,
            },
        ),
        "filesystem.search": (
            "filesystem.search_result",
            {
                "results": [
                    {
                        "name": f"file_{i:05d}.py",
                        "rel_path": f"src/file_{i:05d}.py",
                        "type": "file",
                        "modified_at": "2026-07-25T00:00:00Z",
                    }
                    for i in range(args.search_results)
                ],
                "partial": True,
                "stopped_reason": "results",
                "scanned_count": 50_000,
            },
        ),
    }
    stub = DaemonStub(registry, node_id, replies)
    connection, _ = await registry.register(node_id, stub)  # type: ignore[arg-type]

    async def relay(type_: str) -> dict[str, Any]:
        message = await registry.request(
            node_id, type_, {"session_id": str(session_id), "path": "src"}, timeout_seconds=15
        )
        return message.payload

    latency = {
        "list": await _measure(
            f"relay_list_{args.entries}_entries",
            LIST_BUDGET_MS,
            args.iterations,
            lambda: relay("filesystem.list"),
        ),
        "read": await _measure(
            f"relay_read_{args.preview_mib}mib",
            READ_BUDGET_MS,
            args.iterations,
            lambda: relay("filesystem.read"),
        ),
        "search": await _measure(
            f"relay_search_{args.search_results}_results",
            SEARCH_BUDGET_MS,
            args.iterations,
            lambda: relay("filesystem.search"),
        ),
    }

    bounds = await _bounds(registry, node_id, stub, connection)
    return {
        "component": "central-relay",
        "config": {
            "entries": args.entries,
            "preview_mib": args.preview_mib,
            "search_results": args.search_results,
            "iterations": args.iterations,
            "preview_bytes": len(preview),
        },
        "nfr": {"directory_list_ms": 2000, "preview_2mb_ms": 3000},
        "latency": latency,
        "bounds": bounds,
    }


async def _bounds(
    registry: NodeConnectionRegistry,
    node_id: uuid.UUID,
    stub: DaemonStub,
    connection: Any,
) -> dict[str, Any]:
    """Relay bounds the exit gate asks for: timeout, cancel, disconnect and the
    per-node pending cap must all leave the correlation table empty."""
    stub.silent = True

    # 1. Timeout → REQUEST_TIMEOUT and the pending entry is dropped.
    timed_out = False
    try:
        await registry.request(node_id, "filesystem.list", {"path": "."}, timeout_seconds=0.05)
    except ApiError as exc:
        timed_out = exc.code == "REQUEST_TIMEOUT"
    timeout_clean = len(connection.pending) == 0

    # 2. Caller cancel (browser abort) → no pending entry left behind.
    task = asyncio.create_task(
        registry.request(node_id, "filesystem.read", {"path": "a"}, timeout_seconds=30)
    )
    await asyncio.sleep(0.02)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    cancel_clean = len(connection.pending) == 0

    # 3. Per-node pending bound → NODE_BUSY once the cap is reached.
    filler = [
        asyncio.create_task(
            registry.request(node_id, "filesystem.list", {"path": "."}, timeout_seconds=30)
        )
        for _ in range(registry._pending_max)  # noqa: SLF001 - harness inspects the bound
    ]
    await asyncio.sleep(0.05)
    busy = False
    try:
        await registry.request(node_id, "filesystem.list", {"path": "."}, timeout_seconds=1)
    except ApiError as exc:
        busy = exc.code == "NODE_BUSY"

    # 4. Disconnect mid-flight → every waiter fails fast, table cleared.
    await registry.remove(node_id, connection)
    offline_errors = 0
    for task in filler:
        try:
            await task
        except ApiError as exc:
            offline_errors += 1 if exc.code == "NODE_OFFLINE" else 0
        except asyncio.CancelledError:
            pass
    disconnect_clean = len(connection.pending) == 0

    return {
        "timeout_raised": timed_out,
        "timeout_no_pending_leak": timeout_clean,
        "cancel_raised": cancelled,
        "cancel_no_pending_leak": cancel_clean,
        "pending_cap": registry._pending_max,  # noqa: SLF001
        "node_busy_at_cap": busy,
        "disconnect_failed_waiters": offline_errors,
        "disconnect_no_pending_leak": disconnect_clean,
        "ok": all(
            [
                timed_out,
                timeout_clean,
                cancelled,
                cancel_clean,
                busy,
                offline_errors > 0,
                disconnect_clean,
            ]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entries", type=int, default=2000, help="entries per listing (ADR 0015 cap)"
    )
    parser.add_argument("--preview-mib", type=int, default=2, help="preview size (FR-FILE-003 cap)")
    parser.add_argument("--search-results", type=int, default=200, help="search hits (max_results)")
    parser.add_argument("--iterations", type=int, default=30, help="samples per scenario")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args()

    report = asyncio.run(_run(args))
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)

    failures = [case["name"] for case in report["latency"].values() if not case["ok"]]
    if not report["bounds"]["ok"]:
        failures.append("relay-bounds")
    if failures:
        print(f"FAIL: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("OK: central relay within budget; relay bounds hold", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
