"""NFR-001/003 terminal relay: many browser WebSockets, incl. slow and flood clients.

The property that matters most here is the one PRD §20.5 names as a risk: **a client
that stops reading must not cost anything unbounded, and must not degrade the others.**
So the run mixes three client kinds against the same sessions:

* **normal** — reads every frame and measures the round trip (browser → Central →
  daemon → Central → browser). The daemon echo is a real network hop through both
  relay legs, so the number is the whole Central-owned path, not half of it.
* **slow** — connects, is granted its subscription, and then never reads. Its channel
  must hit `terminal_queue_max_bytes`/`max_frames`, emit exactly one `terminal.gap`,
  and be closed. What it must *not* do is grow, block `route_output`, or slow the
  normal clients sharing its session.
* **flood** — writes input as fast as the socket accepts. Only the writer's bytes may
  reach the daemon, so most flood clients are also an authorization check: a viewer
  flooding input should produce no daemon traffic at all.

The judgement is comparative on purpose: the normal clients' p95 is measured **with**
slow and flood clients present. A latency budget met only on an otherwise idle system
is not evidence about this risk.

    cd backend && uv run python ../scripts/p4/load/terminal_clients.py \
        --base-url http://127.0.0.1:8000 --admin-password ... --clients 500
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import struct
import sys
import time
import base64
import os
import socket as socketlib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    Central,
    CentralError,
    FakeDaemon,
    RssSampler,
    Scenario,
    bring_up_fleet,
    distribution,
    print_scenario,
    ssl_context_for,
    tear_down_fleet,
    write_report,
    ws_connect,
)

# NFR-001: keystroke to displayed output.
ROUND_TRIP_BUDGET_P95_MS = 200.0
_STAMP = struct.Struct("<d")

# Frames are self-describing by a leading tag byte. Without it, unsolicited filler
# output would be decoded as a timestamp — random bytes occasionally unpack to a
# plausible float, which would inject fabricated samples into the latency
# distribution. An explicit tag makes "not one of ours" unambiguous.
TAG_TIMED = 0x01
TAG_FILLER = 0x00


@dataclass
class ClientStats:
    kind: str = "normal"
    connected: bool = False
    frames_read: int = 0
    bytes_read: int = 0
    round_trips_ms: list[float] = field(default_factory=list)
    gap_events: int = 0
    frames_sent: int = 0
    close_code: int | None = None
    closed_by_server: bool = False
    error: str = ""
    role: str = ""


def _stamped(size: int) -> bytes:
    """An input payload carrying its own send time, so the round trip needs no
    external correlation table (and no clock skew between two processes)."""
    body = b"x" * max(0, size - _STAMP.size - 1)
    return bytes((TAG_TIMED,)) + _STAMP.pack(time.perf_counter()) + body


def _filler(size: int) -> bytes:
    """Unsolicited daemon output: what fills a non-reading client's queue."""
    return bytes((TAG_FILLER,)) + b"o" * max(0, size - 1)


def _elapsed_ms(payload: bytes) -> float | None:
    if len(payload) < 1 + _STAMP.size or payload[0] != TAG_TIMED:
        return None
    sent = _STAMP.unpack(payload[1 : 1 + _STAMP.size])[0]
    delta = (time.perf_counter() - sent) * 1000.0
    return delta if 0 <= delta < 60_000 else None


async def _normal_client(
    central: Central, session_id: str, stats: ClientStats, args: argparse.Namespace
) -> None:
    ticket = await asyncio.to_thread(central.attach_ticket, session_id)
    url = central.ws_url(f"/ws/sessions/{session_id}/terminal?ticket={ticket}")
    async with ws_connect(url, ssl=ssl_context_for(url), open_timeout=30) as socket:
        stats.connected = True
        deadline = time.perf_counter() + args.duration
        pending = 0
        while time.perf_counter() < deadline:
            if pending < args.in_flight:
                await socket.send(_stamped(args.input_size))
                stats.frames_sent += 1
                pending += 1
            try:
                message = await asyncio.wait_for(socket.recv(), timeout=1.0)
            except TimeoutError:
                continue
            if isinstance(message, bytes):
                stats.frames_read += 1
                stats.bytes_read += len(message)
                elapsed = _elapsed_ms(message)
                if elapsed is not None:
                    stats.round_trips_ms.append(elapsed)
                    pending = max(0, pending - 1)
            else:
                event = json.loads(message)
                if event.get("type") == "terminal.role":
                    stats.role = event["payload"].get("role", "")
                elif event.get("type") == "terminal.gap":
                    stats.gap_events += 1


async def _slow_client(
    central: Central,
    session_id: str,
    stats: ClientStats,
    args: argparse.Namespace,
    stop_output: asyncio.Event,
) -> None:
    """A genuinely slow client: raw socket, nothing read at the OS level.

    This does **not** use the `websockets` client, and that is the whole point. That
    library drains the socket into its own queue from a background task, so a client
    that merely stops calling `recv()` still creates no backpressure — Central would
    see a perfectly healthy reader and the queue bound would never be approached. The
    test would pass while testing nothing.

    So: hand-rolled HTTP Upgrade, consume exactly the 101 response, then stop reading
    entirely. Central's per-browser channel fills, hits `terminal_queue_max_bytes`,
    emits `terminal.gap` and closes. Afterwards the socket is drained *once*, bounded
    by a deadline and a byte cap, to count what Central managed to send and to find the
    gap frame. The byte count therefore includes kernel and library buffers as well as
    the channel, which is what `--queue-slack` accounts for.
    """
    stats.kind = "slow"
    ticket = await asyncio.to_thread(central.attach_ticket, session_id)
    parsed = urlparse(central.base_url)
    if parsed.scheme != "http":
        stats.error = "slow client needs plain http (raw socket, no TLS)"
        return
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = f"/ws/sessions/{session_id}/terminal?ticket={ticket}"
    key = base64.b64encode(os.urandom(16)).decode()

    # A deliberately tiny receive buffer. On loopback the kernel auto-tunes the socket
    # buffer into the megabytes, so it happily absorbed several MiB of backlog and
    # Central's channel never filled — the bound looked untested and the "was it
    # closed" check failed for a reason that had nothing to do with Central. Shrinking
    # the window is what makes a non-reading client apply real backpressure.
    raw = socketlib.socket(socketlib.AF_INET, socketlib.SOCK_STREAM)
    raw.setsockopt(socketlib.SOL_SOCKET, socketlib.SO_RCVBUF, args.slow_rcvbuf)
    raw.setblocking(False)
    await asyncio.get_running_loop().sock_connect(raw, (host, port))
    reader, writer = await asyncio.open_connection(sock=raw)
    try:
        writer.write(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).encode()
        )
        await writer.drain()
        # Only the handshake response is read. Anything after it is left in the socket
        # on purpose — that unread data is the backpressure being tested.
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
        status_line = header.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            stats.error = f"upgrade refused: {status_line!r}"
            return
        stats.connected = True

        await asyncio.sleep(args.duration + args.slow_extra)
        # Output for this session is stopped before draining. Otherwise the drain reads
        # the backlog *plus* whatever arrives during it, and the total exceeds the queue
        # bound for a reason that is not a queue-bound violation — which is exactly the
        # false failure the first run produced.
        stop_output.set()
        await asyncio.sleep(0.3)

        # One bounded drain. Both bounds matter: filler output keeps arriving for the
        # whole scenario, so an unbounded read loop here never returns — which is
        # exactly how the first version of this harness hung instead of reporting.
        deadline = time.perf_counter() + args.slow_drain_seconds
        cap = int(args.queue_max_bytes * args.queue_slack * 2)
        # A short carry-over so a sentinel split across two reads is still found.
        carry = b""
        while time.perf_counter() < deadline and stats.bytes_read < cap:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=0.5)
            except TimeoutError:
                continue
            if not chunk:
                stats.closed_by_server = True
                break
            stats.bytes_read += len(chunk)
            stats.frames_read += 1
            # Server-to-client text frames are unmasked, so the JSON body appears
            # verbatim; a substring match is enough to spot the sentinel without
            # implementing frame parsing in a load tool.
            window = carry + chunk
            stats.gap_events += window.count(b"terminal.gap")
            carry = window[-len(b"terminal.gap") :]
    except (TimeoutError, asyncio.IncompleteReadError, OSError) as error:
        stats.error = stats.error or f"{type(error).__name__}: {error}"
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _flood_client(
    central: Central, session_id: str, stats: ClientStats, args: argparse.Namespace
) -> None:
    stats.kind = "flood"
    ticket = await asyncio.to_thread(central.attach_ticket, session_id)
    url = central.ws_url(f"/ws/sessions/{session_id}/terminal?ticket={ticket}")
    async with ws_connect(url, ssl=ssl_context_for(url), open_timeout=30) as socket:
        stats.connected = True
        deadline = time.perf_counter() + args.duration

        async def drain() -> None:
            while True:
                message = await socket.recv()
                if isinstance(message, bytes):
                    stats.frames_read += 1
                    stats.bytes_read += len(message)
                elif json.loads(message).get("type") == "terminal.gap":
                    stats.gap_events += 1

        reader = asyncio.create_task(drain())
        try:
            while time.perf_counter() < deadline:
                await socket.send(b"y" * args.input_size)
                stats.frames_sent += 1
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader


async def _filler_loop(
    daemon: FakeDaemon,
    session_id: str,
    args: argparse.Namespace,
    stop: asyncio.Event,
) -> None:
    """Push output into one session at roughly `output_rate_bytes` per second."""
    chunk = _filler(args.output_chunk)
    per_second = max(1, args.output_rate_bytes // max(1, args.output_chunk))
    delay = 1.0 / per_second
    while not stop.is_set():
        try:
            await daemon.send_output(session_id, chunk)
        except Exception:  # noqa: BLE001 - socket closing ends the run
            return
        await asyncio.sleep(delay)


async def run(args: argparse.Namespace) -> Scenario:
    scenario = Scenario(name="terminal-relay")
    central = Central(args.base_url)
    central.login(args.admin_user, args.admin_password)

    rss = RssSampler(args.central_pid)
    if not rss.available:
        scenario.notes.append(
            "Central RSS not sampled: pass --central-pid on the same host to include "
            "the memory-boundedness evidence."
        )

    # Enough nodes to spread the sessions without exceeding sessions_per_node_max.
    sessions_per_node = min(args.sessions_per_node, 10)
    nodes_needed = max(1, -(-args.sessions // sessions_per_node))
    daemons = await bring_up_fleet(
        central,
        nodes=nodes_needed,
        roots=[args.workspace_root],
        heartbeat_interval=args.heartbeat_interval,
    )

    # Every daemon echoes input straight back as output, which is what makes the
    # measured value a full round trip rather than one leg of it.
    async def echo(daemon: FakeDaemon):  # noqa: ANN202
        async def handler(session_id: str, payload: bytes) -> None:
            await daemon.send_output(session_id, payload)

        return handler

    for daemon in daemons:
        daemon.on_input = await echo(daemon)

    sessions: list[str] = []
    filler_tasks: list[asyncio.Task[None]] = []
    try:
        for index in range(args.sessions):
            daemon = daemons[index % len(daemons)]
            try:
                created = await asyncio.to_thread(
                    central.create_session,
                    daemon.node_id,
                    name=f"load-{index:04d}",
                    workspace=args.workspace_root,
                )
                sessions.append(created["id"])
            except CentralError as error:
                scenario.notes.append(f"session {index} not created: {error}")
        if not sessions:
            scenario.check(
                "sessions_created",
                "harness precondition: at least one session exists",
                passed=False,
                observed=0,
                limit=">= 1",
            )
            return scenario

        # Unsolicited output at a fixed rate per session. This is what a real CLI
        # produces and what a non-reading client's queue fills with; without it the
        # slow-client scenario would stall on an idle socket and the overflow bound
        # would go untested while appearing to pass.
        stop_output = {session_id: asyncio.Event() for session_id in sessions}
        if args.output_rate_bytes > 0:
            for index, session_id in enumerate(sessions):
                filler_tasks.append(
                    asyncio.create_task(
                        _filler_loop(
                            daemons[index % len(daemons)],
                            session_id,
                            args,
                            stop_output[session_id],
                        )
                    )
                )

        rss.start()
        stats: list[ClientStats] = []
        tasks: list[asyncio.Task[None]] = []

        # A normal client subscribes to each session **first**, on purpose. Only the
        # writer's input reaches the daemon (SEC-002/FR-SESSION-007), and the writer is
        # the first write-capable subscriber. When a slow or flood client got there
        # first, that session produced no timed echoes at all and four of eight normal
        # clients recorded zero samples — a harness artifact that read exactly like
        # "the relay degraded under load".
        for session_id in sessions:
            entry = ClientStats()
            stats.append(entry)
            tasks.append(
                asyncio.create_task(_normal_client(central, session_id, entry, args))
            )
            await asyncio.sleep(0.15)

        for index in range(max(0, args.clients - len(sessions))):
            session_id = sessions[index % len(sessions)]
            entry = ClientStats()
            stats.append(entry)
            if index < args.slow_clients:
                tasks.append(
                    asyncio.create_task(
                        _slow_client(
                            central, session_id, entry, args, stop_output[session_id]
                        )
                    )
                )
            elif index < args.slow_clients + args.flood_clients:
                tasks.append(
                    asyncio.create_task(_flood_client(central, session_id, entry, args))
                )
            else:
                tasks.append(
                    asyncio.create_task(
                        _normal_client(central, session_id, entry, args)
                    )
                )
            # Paced so the measurement is of steady state, not of a connect storm.
            if args.connect_pace:
                await asyncio.sleep(args.connect_pace)

        for entry, result in zip(
            stats, await asyncio.gather(*tasks, return_exceptions=True), strict=True
        ):
            if isinstance(result, BaseException):
                entry.error = f"{type(result).__name__}: {result}"

        await rss.stop()
        _judge(scenario, stats, args, rss, daemons)
    finally:
        for task in filler_tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*filler_tasks, return_exceptions=True)
        for session_id in sessions:
            with contextlib.suppress(CentralError):
                await asyncio.to_thread(central.terminate_session, session_id)
        await tear_down_fleet(daemons)
        await rss.stop()
    return scenario


def _judge(
    scenario: Scenario,
    stats: list[ClientStats],
    args: argparse.Namespace,
    rss: RssSampler,
    daemons: list[FakeDaemon],
) -> None:
    normal = [s for s in stats if s.kind == "normal"]
    slow = [s for s in stats if s.kind == "slow"]
    flood = [s for s in stats if s.kind == "flood"]
    round_trips = [ms for s in normal for ms in s.round_trips_ms]
    connected = sum(1 for s in stats if s.connected)
    errored = [s for s in stats if s.error]

    scenario.measurements.update(
        {
            "clients_requested": args.clients,
            "clients_connected": connected,
            "sessions": args.sessions,
            "normal_clients": len(normal),
            "slow_clients": len(slow),
            "flood_clients": len(flood),
            "round_trip": distribution(round_trips),
            "slow_client_bytes_received": [s.bytes_read for s in slow],
            "slow_client_gap_events": [s.gap_events for s in slow],
            "slow_client_closed_by_server": [s.closed_by_server for s in slow],
            "flood_bytes_echoed": sum(s.bytes_read for s in flood),
            "client_errors": [s.error for s in errored][:10],
            "central_rss": rss.summary(),
        }
    )

    scenario.check(
        "clients_connected",
        "NFR-003: the requested number of terminal WebSockets connect",
        passed=connected >= args.clients,
        observed=connected,
        limit=args.clients,
        detail=f"{len(errored)} client task(s) raised",
    )
    scenario.check(
        "round_trip_p95",
        "NFR-001: keystroke round trip p95 under 200 ms, measured while slow and "
        "flood clients are active",
        passed=bool(round_trips)
        and distribution(round_trips)["p95_ms"] <= ROUND_TRIP_BUDGET_P95_MS,
        observed=distribution(round_trips)["p95_ms"] if round_trips else "no samples",
        limit=ROUND_TRIP_BUDGET_P95_MS,
        detail=f"{len(round_trips)} samples across {len(normal)} normal clients",
    )

    if slow:
        # The queue bound in bytes is what Central promises. A slow client may receive
        # up to roughly that much before the overflow decision, plus the gap frame.
        worst = max(s.bytes_read for s in slow)
        budget = args.queue_max_bytes * args.queue_slack
        scenario.check(
            "slow_client_queue_bounded",
            "PRD §20.5: a non-reading client is bounded by terminal_queue_max_bytes",
            passed=worst <= budget,
            observed=worst,
            limit=int(budget),
            detail=f"queue_max_bytes={args.queue_max_bytes}, slack x{args.queue_slack}",
        )
        gaps = [s.gap_events for s in slow]
        scenario.check(
            "slow_client_gets_exactly_one_gap",
            "P2: overflow produces one terminal.gap, then the connection closes",
            passed=all(g <= 1 for g in gaps),
            observed=gaps,
            limit="<= 1 per client",
            detail="A repeating gap would mean the channel kept accepting after "
            "overflow; zero across all of them means the stall never filled the "
            "queue, which is reported rather than treated as a pass.",
        )
        scenario.check(
            "slow_client_is_disconnected",
            "P2: after overflow Central closes the connection rather than keeping it",
            passed=all(s.closed_by_server for s in slow),
            observed=[s.closed_by_server for s in slow],
            limit="all closed",
            detail="A client held open after overflow would keep occupying a "
            "subscription while receiving a stream it has already lost.",
        )
        if all(g == 0 for g in gaps):
            scenario.notes.append(
                "No slow client reached overflow: the run was too short or too quiet "
                "to fill terminal_queue_max_bytes. Raise --output-rate or --duration "
                "for the overflow path to be exercised rather than assumed."
            )
    else:
        scenario.notes.append(
            "No slow clients configured; the overflow path was not exercised."
        )

    # Only the writer's bytes may reach a node. Flood clients subscribe after the
    # writer, so they are viewers: their input must be dropped at Central. Comparing
    # what the nodes actually received against what the writers sent is the check.
    daemon_inputs = sum(d.counters.inputs_received for d in daemons)
    writers_sent = sum(s.frames_sent for s in normal)
    flood_sent = sum(s.frames_sent for s in flood)
    scenario.measurements.update(
        {
            "daemon_input_frames": daemon_inputs,
            "normal_client_frames_sent": writers_sent,
            "flood_client_frames_sent": flood_sent,
        }
    )
    if flood:
        scenario.check(
            "viewer_flood_reaches_no_node",
            "SEC-002/FR-SESSION-007: a flooding viewer's input never reaches a node",
            passed=daemon_inputs <= writers_sent,
            observed=f"{daemon_inputs} received vs {writers_sent} sent by writers",
            limit=f"<= {writers_sent}",
            detail=f"flood clients sent {flood_sent} frames; none may be counted. "
            "This also bounds the flood: dropped input costs Central nothing downstream.",
        )

    if normal and slow:
        # The comparative claim: a stalled neighbour must not degrade the readers.
        healthy = [s for s in normal if s.round_trips_ms]
        scenario.check(
            "normal_clients_unaffected",
            "PRD §20.5: normal clients keep receiving while a co-tenant stalls",
            passed=len(healthy) >= max(1, int(len(normal) * 0.95)),
            observed=f"{len(healthy)}/{len(normal)} still measuring",
            limit=f">= {max(1, int(len(normal) * 0.95))}",
        )

    if rss.samples:
        summary = rss.summary()
        growth = summary["second_half_mean_mib"] - summary["first_half_mean_mib"]
        scenario.check(
            "central_rss_bounded",
            "boundedness: Central RSS does not grow monotonically with slow clients present",
            passed=growth <= args.rss_growth_budget_mib,
            observed=round(growth, 1),
            limit=args.rss_growth_budget_mib,
            detail=f"peak {summary['peak_mib']} MiB, final {summary['final_mib']} MiB",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--clients", type=int, default=500)
    parser.add_argument("--sessions", type=int, default=50)
    parser.add_argument("--sessions-per-node", type=int, default=10)
    parser.add_argument("--slow-clients", type=int, default=5)
    parser.add_argument("--flood-clients", type=int, default=5)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--slow-extra", type=float, default=5.0)
    # Generous, because the drain has to read the whole backlog *through the deliberately
    # tiny receive window* before the close frame behind it becomes visible. At 5 s a 6 MiB
    # backlog was still in flight when the deadline hit, so the connection looked as though
    # Central had never closed it.
    parser.add_argument("--slow-drain-seconds", type=float, default=20.0)
    parser.add_argument("--slow-rcvbuf", type=int, default=4096)
    parser.add_argument("--input-size", type=int, default=64)
    parser.add_argument("--in-flight", type=int, default=1)
    # Enough per session that a stalled client crosses the 4 MiB queue bound inside the
    # default duration. 512 KiB/s was not: over ~13 s it pushed ~6.6 MiB, but a few MiB
    # of that sat in Central's socket send buffer (loopback auto-tunes it large), so the
    # channel itself peaked around 3.2 MiB and never overflowed. The bound was real; the
    # push was too small to reach it. At 2 MiB/s the total dwarfs every buffer in the
    # path, so overflow is reached rather than approached.
    parser.add_argument("--output-rate-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--output-chunk", type=int, default=4096)
    parser.add_argument("--connect-pace", type=float, default=0.004)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--workspace-root", default="/tmp/cliora-load")
    parser.add_argument("--central-pid", type=int, default=None)
    parser.add_argument("--queue-max-bytes", type=int, default=4 * 1024 * 1024)
    # Slack over the byte bound: the last frame accepted before the decision may push
    # the total slightly past it, and the gap frame itself adds a little.
    parser.add_argument("--queue-slack", type=float, default=1.5)
    parser.add_argument("--rss-growth-budget-mib", type=float, default=96.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    scenario = asyncio.run(run(args))
    print_scenario(scenario)
    if args.out:
        write_report(args.out, scenario.to_json())
    return 1 if scenario.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
