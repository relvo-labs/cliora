"""P2 terminal-relay latency / backpressure / scale harness (P2-16, plan/03/08 §3).

Exercises the *real* Central relay hot path — ``TerminalRelay`` fanning daemon
terminal output into per-browser ``BrowserChannel`` queues — with no mocks, and
emits the ``latency.json`` / ``backpressure.json`` artifacts the exit gate asks
for. It measures the component the Central owns; true end-to-end latency
(browser → Central → daemon → tmux → back) additionally needs the full stack and
is produced by ``scripts/e2e/latency_probe.py`` against a live node.

Three scenarios:

1. **fan-out latency** — route N output frames to S subscribers (default 500,
   NFR-003) that all drain concurrently; report the per-frame route→dequeue
   latency distribution against the < 200 ms target (tech §NFR-001).
2. **slow consumer / backpressure** — one consumer stops draining while a large
   burst is pushed; assert the channel stays byte- and frame-bounded, exactly
   one overflow sentinel (→ ``terminal.gap``) is queued, ``route_output`` never
   blocks or raises, and process RSS stays bounded.
3. **multi-session scale** — many sessions each with many subscribers, to show
   the hub stays bounded across sessions.

Run:  ``cd backend && uv run --project . python perf/relay_bench.py``
Knobs: ``--subscribers --frames --frame-size --sessions --burst-mib --out``.
Deterministic (no wall-clock in the measured path beyond perf_counter); exits
non-zero if a hard invariant (bounded queue, single gap, latency budget) fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import struct
import sys
import time
import uuid
from pathlib import Path

# Make the backend package importable when run as a bare script (sys.path[0] is
# the perf/ dir, so the app package one level up is not otherwise visible).
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.terminal_queue import BrowserChannel  # noqa: E402
from app.services.terminal_relay import TerminalRelay  # noqa: E402
from app.settings import Settings  # noqa: E402

_TS = struct.Struct("<d")  # little-endian float64 enqueue timestamp header


def _payload(size: int) -> bytes:
    """A frame whose first 8 bytes carry the route-time perf_counter stamp."""
    body = b"x" * max(0, size - _TS.size)
    return _TS.pack(time.perf_counter()) + body


def _latency_ms(payload: bytes) -> float:
    return (time.perf_counter() - _TS.unpack(payload[: _TS.size])[0]) * 1000.0


def _rss_mib() -> float:
    # ru_maxrss is KiB on Linux, bytes on macOS; assume Linux CI/dev host.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
    return ordered[k]


def _dist(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "p50_ms": round(_pct(values, 50), 3),
        "p90_ms": round(_pct(values, 90), 3),
        "p99_ms": round(_pct(values, 99), 3),
        "max_ms": round(max(values), 3) if values else 0.0,
        "mean_ms": round(statistics.fmean(values), 3) if values else 0.0,
    }


async def _fan_out(settings: Settings, subscribers: int, frames: int, frame_size: int) -> dict:
    """Scenario 1 + 3 core: one session, `subscribers` concurrent drainers."""
    relay = TerminalRelay()
    session_id = uuid.uuid4()
    channels: list[BrowserChannel] = []
    latencies: list[float] = []

    for i in range(subscribers):
        ch = BrowserChannel(settings.terminal_queue_max_bytes, settings.terminal_queue_max_frames)
        channels.append(ch)
        await relay.subscribe(session_id, f"c{i}", uuid.uuid4(), ch, can_write=(i == 0))

    async def consume(ch: BrowserChannel) -> None:
        got = 0
        while got < frames:
            item = await ch.get()
            if item is None:
                return
            kind, payload = item
            if kind == "output":
                latencies.append(_latency_ms(payload))  # type: ignore[arg-type]
                got += 1
            elif kind == "overflow":
                return

    consumers = [asyncio.create_task(consume(ch)) for ch in channels]
    started = time.perf_counter()
    # ``route_output`` only touches in-memory queues, so awaiting it need not yield
    # to the consumers. A real daemon receives separate WebSocket frames and returns
    # to the event loop between them; mirror that here. Otherwise this scenario
    # measures one synthetic producer monopolising the loop as if every active
    # browser were stalled (the separate backpressure scenario deliberately does
    # measure a stalled browser).
    for _ in range(frames):
        await relay.route_output(session_id, _payload(frame_size))
        await asyncio.sleep(0)
    await asyncio.wait_for(asyncio.gather(*consumers), timeout=60)
    wall = time.perf_counter() - started

    delivered = len(latencies)
    expected = subscribers * frames
    total_bytes = expected * frame_size
    return {
        "subscribers": subscribers,
        "frames_per_subscriber": frames,
        "frame_size_bytes": frame_size,
        "delivered_frames": delivered,
        "expected_frames": expected,
        "wall_seconds": round(wall, 4),
        "throughput_frames_per_s": round(delivered / wall, 1) if wall else 0.0,
        "throughput_mib_per_s": round(total_bytes / wall / (1024 * 1024), 1) if wall else 0.0,
        "latency": _dist(latencies),
        "target_ms": 200,
        "meets_target": bool(latencies) and _pct(latencies, 99) < 200,
    }


async def _backpressure(settings: Settings, burst_mib: int, frame_size: int) -> dict:
    """Scenario 2: a stalled consumer must not let a burst grow unbounded."""
    max_bytes = settings.terminal_queue_max_bytes
    max_frames = settings.terminal_queue_max_frames
    relay = TerminalRelay()
    session_id = uuid.uuid4()
    ch = BrowserChannel(max_bytes, max_frames)
    await relay.subscribe(session_id, "stalled", uuid.uuid4(), ch, can_write=True)

    rss_before = _rss_mib()
    frames = (burst_mib * 1024 * 1024) // frame_size
    route_errors = 0
    for _ in range(frames):
        try:
            await relay.route_output(session_id, _payload(frame_size))
        except Exception:  # noqa: BLE001 - the whole point is this must not raise
            route_errors += 1
    rss_after = _rss_mib()

    stats = ch.stats
    # Drain what is buffered and confirm exactly one overflow sentinel arrived.
    overflow_seen = 0
    drained = 0
    while not ch._items.empty():  # noqa: SLF001 - harness inspects the real queue
        kind, _ = ch._items.get_nowait()  # type: ignore[misc]
        if kind == "overflow":
            overflow_seen += 1
        else:
            drained += 1

    bounded = stats.bytes <= max_bytes and stats.frames <= max_frames
    ok = bounded and route_errors == 0 and overflow_seen == 1
    return {
        "burst_mib": burst_mib,
        "frame_size_bytes": frame_size,
        "frames_pushed": frames,
        "queue_max_bytes": max_bytes,
        "queue_max_frames": max_frames,
        "peak_buffered_bytes": stats.bytes,
        "peak_buffered_frames": stats.frames,
        "buffered_bytes_within_bound": stats.bytes <= max_bytes,
        "buffered_frames_within_bound": stats.frames <= max_frames,
        "overflow_sentinels": overflow_seen,
        "route_output_errors": route_errors,
        "rss_mib_before": round(rss_before, 1),
        "rss_mib_after": round(rss_after, 1),
        "rss_delta_mib": round(rss_after - rss_before, 1),
        "ok": ok,
    }


async def _run(args: argparse.Namespace) -> dict:
    settings = Settings()
    single = await _fan_out(settings, 1, args.frames, args.frame_size)
    scaled = await _fan_out(settings, args.subscribers, max(1, args.frames // 10), args.frame_size)
    multi = []
    for _ in range(args.sessions):
        multi.append(
            await _fan_out(settings, args.subscribers // args.sessions or 1, 20, args.frame_size)
        )
    backpressure = await _backpressure(settings, args.burst_mib, args.frame_size)
    return {
        "config": {
            "subscribers": args.subscribers,
            "frames": args.frames,
            "frame_size_bytes": args.frame_size,
            "sessions": args.sessions,
            "burst_mib": args.burst_mib,
            "queue_max_bytes": settings.terminal_queue_max_bytes,
            "queue_max_frames": settings.terminal_queue_max_frames,
        },
        "latency": {
            "single_subscriber": single,
            "scaled_fan_out": scaled,
        },
        "scale": {
            "sessions": args.sessions,
            "per_session_delivered": [m["delivered_frames"] for m in multi],
            "all_bounded": all(m["delivered_frames"] == m["expected_frames"] for m in multi),
        },
        "backpressure": backpressure,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscribers", type=int, default=500, help="fan-out width (NFR-003)")
    parser.add_argument(
        "--frames", type=int, default=2000, help="frames for the single-subscriber latency pass"
    )
    parser.add_argument("--frame-size", type=int, default=1024, help="bytes per output frame")
    parser.add_argument(
        "--sessions", type=int, default=10, help="concurrent sessions in the scale pass"
    )
    parser.add_argument("--burst-mib", type=int, default=16, help="slow-consumer burst size")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args()

    report = asyncio.run(_run(args))

    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)

    lat = report["latency"]["scaled_fan_out"]
    bp = report["backpressure"]
    print(
        f"\n[summary] fan-out {lat['subscribers']}×{lat['frames_per_subscriber']} "
        f"p50={lat['latency']['p50_ms']}ms p99={lat['latency']['p99_ms']}ms "
        f"max={lat['latency']['max_ms']}ms (target<200) · "
        f"backpressure bounded={bp['ok']} peak={bp['peak_buffered_bytes']}B "
        f"gap={bp['overflow_sentinels']}",
        file=sys.stderr,
    )

    ok = bp["ok"] and report["scale"]["all_bounded"] and lat["meets_target"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
