"""In-memory terminal relay hub (P2-09/P2-10).

Maps a session to its live browser subscribers and enforces the single-writer
rule. Daemon terminal output/events (arriving on the node WS) are fanned out to
every subscriber's own bounded BrowserChannel; browser input is only relayed to
the daemon from the current writer (viewer/forged input is dropped server-side,
SEC-002/FR-SESSION-007). Like the connection registry this is process-local; a
multi-process deployment would move it to a shared store.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app import metrics
from app.clock import monotonic_seconds, now_utc
from app.logging import get_logger
from app.services.terminal_queue import BrowserChannel, QueueOverflow

_logger = get_logger("cliora.terminal_relay")


@dataclass
class Subscriber:
    conn_id: str
    user_id: uuid.UUID
    channel: BrowserChannel


class TerminalRelay:
    def __init__(
        self,
        *,
        ownership_cache_max: int = 4096,
        ownership_ttl_seconds: float = 60,
        clock: Callable[[], float] = monotonic_seconds,
    ) -> None:
        self._sessions: dict[uuid.UUID, dict[str, Subscriber]] = {}
        self._writer: dict[uuid.UUID, str] = {}
        self._lock = asyncio.Lock()
        self._owners: OrderedDict[uuid.UUID, tuple[uuid.UUID, float]] = OrderedDict()
        self._ownership_cache_max = ownership_cache_max
        self._ownership_ttl_seconds = ownership_ttl_seconds
        self._clock = clock
        self._ownership_generation = 0
        self._denial_log_at: float | None = None

    async def authorize_node_session(
        self,
        node_id: uuid.UUID,
        session_id: uuid.UUID,
        lookup: Callable[[uuid.UUID], Awaitable[tuple[uuid.UUID, bool] | None]],
    ) -> bool:
        """Single ownership gate for daemon output, status and terminal events.

        Only a repository lookup can teach us an owner; neither subscribers nor
        daemon claims are authority. Session node_id is immutable. Cache live rows
        in a bounded LRU so terminal bursts do not query PostgreSQL per frame.
        End/delete invalidates; TTL forces periodic revalidation. Node
        reconnect preserves ownership, while a Central restart safely starts cold.
        """
        now = self._clock()
        cached = self._owners.get(session_id)
        owner = None
        if cached is not None:
            if now < cached[1]:
                owner = cached[0]
                self._owners.move_to_end(session_id)
            else:
                self._owners.pop(session_id, None)
        if owner is None:
            generation = self._ownership_generation
            found = await lookup(session_id)
            if found is not None:
                owner, active = found
                # An end/delete while the lookup was suspended must win over the
                # stale result. No lock or DB access is needed on cache hits.
                if active and generation == self._ownership_generation:
                    self._owners[session_id] = (owner, now + self._ownership_ttl_seconds)
                    self._owners.move_to_end(session_id)
                    while len(self._owners) > self._ownership_cache_max:
                        self._owners.popitem(last=False)
        if owner == node_id:
            return True
        # Follow denial telemetry's fixed action/role/reason vocabulary. No ids
        # become metric labels; no terminal bytes or daemon text enter any sink.
        metrics.increment(
            metrics.AUTHZ_DENIED_TOTAL, action="node.session", role="daemon", reason="scope"
        )
        # One fixed-size structured signal per 30 seconds per process, even when
        # forged UUIDs vary. Every dropped frame is still counted above.
        if self._denial_log_at is None or now - self._denial_log_at >= 30:
            self._denial_log_at = now
            _logger.warning(
                "node_session_denied",
                extra={
                    "event": "node_session_denied",
                    "node_id": str(node_id),
                    "session_id": str(session_id),
                    "denied_action": "node.session",
                    "reason": "scope",
                },
            )
        return False

    def forget_session(self, session_id: uuid.UUID) -> None:
        """Invalidate ownership on every lifecycle path that ends/deletes a row."""
        self._ownership_generation += 1
        self._owners.pop(session_id, None)

    async def subscribe(
        self,
        session_id: uuid.UUID,
        conn_id: str,
        user_id: uuid.UUID,
        channel: BrowserChannel,
        *,
        can_write: bool,
    ) -> str:
        """Register a subscriber; the first write-capable subscriber with no
        incumbent becomes the writer, otherwise a viewer. Returns the role."""
        async with self._lock:
            subs = self._sessions.setdefault(session_id, {})
            subs[conn_id] = Subscriber(conn_id, user_id, channel)
            if can_write and session_id not in self._writer:
                self._writer[session_id] = conn_id
            return "writer" if self._writer.get(session_id) == conn_id else "viewer"

    async def unsubscribe(self, session_id: uuid.UUID, conn_id: str) -> None:
        async with self._lock:
            subs = self._sessions.get(session_id)
            if subs is not None:
                subs.pop(conn_id, None)
                if not subs:
                    self._sessions.pop(session_id, None)
            if self._writer.get(session_id) == conn_id:
                # Writer released; the 30s hold window (ADR 0013) is enforced
                # client-side, takeover reassigns here.
                self._writer.pop(session_id, None)

    def is_writer(self, session_id: uuid.UUID, conn_id: str) -> bool:
        return self._writer.get(session_id) == conn_id

    def role_of(self, session_id: uuid.UUID, conn_id: str) -> str:
        return "writer" if self.is_writer(session_id, conn_id) else "viewer"

    async def takeover(self, session_id: uuid.UUID, conn_id: str) -> bool:
        """Transfer the writer marker to conn_id (caller must have checked the
        terminal.takeover permission). Returns False if the connection is not a
        subscriber of the session."""
        async with self._lock:
            if conn_id not in self._sessions.get(session_id, {}):
                return False
            self._writer[session_id] = conn_id
            return True

    async def _subscribers(self, session_id: uuid.UUID) -> list[Subscriber]:
        async with self._lock:
            return list(self._sessions.get(session_id, {}).values())

    async def route_output(self, session_id: uuid.UUID, payload: bytes) -> None:
        for sub in await self._subscribers(session_id):
            await sub.channel.send_output(payload)
            # Observed after the enqueue, so the sample is the depth the slowest
            # consumer actually reached. A gauge read on a scrape interval would miss
            # the spike that caused an overflow — which is the only depth that matters
            # (tech §18.1).
            depth = sub.channel.stats
            metrics.observe(metrics.TERMINAL_QUEUE_BYTES, depth.bytes)
            metrics.observe(metrics.TERMINAL_QUEUE_FRAMES, depth.frames)
        metrics.increment(
            metrics.WEBSOCKET_MESSAGES_TOTAL,
            direction="out",
            channel="terminal",
            kind="binary",
        )
        metrics.increment(
            metrics.WEBSOCKET_BYTES_TOTAL,
            len(payload),
            direction="out",
            channel="terminal",
            kind="binary",
        )

    async def route_control(self, session_id: uuid.UUID, text: str) -> None:
        for sub in await self._subscribers(session_id):
            try:
                await sub.channel.send_control(text)
            except QueueOverflow:
                # A control frame that cannot be queued is dropped for that one
                # subscriber; counted because a silent drop here is how a browser ends
                # up never learning its session exited.
                metrics.increment(metrics.TERMINAL_QUEUE_OVERFLOW_TOTAL, reason="control")
        metrics.increment(
            metrics.WEBSOCKET_MESSAGES_TOTAL,
            direction="out",
            channel="terminal",
            kind="control",
        )
        metrics.increment(
            metrics.WEBSOCKET_BYTES_TOTAL,
            len(text.encode("utf-8", "replace")),
            direction="out",
            channel="terminal",
            kind="control",
        )

    def subscriber_count(self, session_id: uuid.UUID) -> int:
        return len(self._sessions.get(session_id, {}))

    def connection_count(self) -> int:
        """Live browser terminal connections across every session, for the
        `active_terminal_connections` gauge."""
        return sum(len(subs) for subs in self._sessions.values())

    def session_ids(self) -> list[uuid.UUID]:
        return list(self._sessions)

    async def announce_shutdown(self, reason: str) -> int:
        """Tell every subscribed browser that Central is going away, and why.

        Sent on SIGTERM before the sockets close (P4-12). Without it a deploy looks to
        the user like an unexplained disconnect, which is indistinguishable from a
        crash or a network fault — so the reconnect is a guess instead of an expectation.
        The CLI session itself is untouched: Central restarting must never end a
        terminal (NFR-002), and this message says so.

        Returns the number of sessions notified. Best effort by construction: a
        subscriber whose control queue is already full is skipped rather than allowed
        to hold up the drain.
        """
        notified = 0
        for session_id in self.session_ids():
            payload = json.dumps(
                {
                    "version": 1,
                    "type": "terminal.server_shutdown",
                    "request_id": "00000000000000000000000000",
                    "node_id": str(session_id),
                    "timestamp": now_utc().isoformat().replace("+00:00", "Z"),
                    "payload": {
                        "session_id": str(session_id),
                        "reason": reason,
                        # Stated explicitly so the browser can promise the right thing:
                        # the session survives, only this connection is going.
                        "session_preserved": True,
                    },
                }
            )
            await self.route_control(session_id, payload)
            notified += 1
        return notified


_relay: TerminalRelay | None = None


def get_terminal_relay() -> TerminalRelay:
    global _relay
    if _relay is None:
        _relay = TerminalRelay()
    return _relay
