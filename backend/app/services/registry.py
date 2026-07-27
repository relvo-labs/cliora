"""In-memory registry of live daemon connections and node status (P1-13/14).

Durable node metadata lives in PostgreSQL; only the live socket, its send-lock,
the monotonic heartbeat timestamp, the latest heartbeat resource sample, and the
in-flight request correlation table live here (ADR 0010). Status is computed by
Central from the monotonic gap since the last heartbeat — never taken from the
daemon's self-report — so wall-clock skew cannot flip a node's state.

Request correlation (tech §7.3): Central mints a `request_id`, parks a Future in
the node's `pending` map, and the daemon answers with the same id. Timeouts,
disconnects, duplicate/unknown responses, and a per-node pending bound are all
handled here so no coroutine leaks and no unbounded growth occurs.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, status

from app import metrics
from app.api.errors import ApiError
from app.clock import monotonic_seconds, now_utc
from app.protocol import ControlMessage
from app.security.node_keys import new_request_id
from app.settings import get_settings

# Status values (PRD §8.2 / FR-NODE-002).
ONLINE = "online"
DEGRADED = "degraded"
OFFLINE = "offline"
DISABLED = "disabled"


@dataclass
class NodeConnection:
    node_id: uuid.UUID
    websocket: WebSocket
    connected_at: float
    last_heartbeat: float
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Latest heartbeat resource sample. Live view; a reduced-rate copy is also
    # persisted to `node_metric_samples` (P4-06).
    resources: dict[str, Any] | None = None
    # Monotonic instant of the last persisted metric sample, or None if none has
    # been written on this connection. Per-connection so a reconnecting node
    # samples immediately rather than inheriting a stale schedule.
    last_metric_persist: float | None = None
    # Correlation table: request_id -> Future resolved by the daemon's response.
    pending: dict[str, asyncio.Future[ControlMessage]] = field(default_factory=dict)


def _request_frame(type_: str, node_id: uuid.UUID, request_id: str, payload: dict[str, Any]) -> str:
    timestamp = now_utc().isoformat().replace("+00:00", "Z")
    return json.dumps(
        {
            "version": 1,
            "type": type_,
            "request_id": request_id,
            "node_id": str(node_id),
            "timestamp": timestamp,
            "payload": payload,
        }
    )


class NodeConnectionRegistry:
    def __init__(
        self,
        clock: Callable[[], float] = monotonic_seconds,
        *,
        pending_max: int | None = None,
    ) -> None:
        self._clock = clock
        self._connections: dict[uuid.UUID, NodeConnection] = {}
        self._lock = asyncio.Lock()
        self._pending_max = pending_max or get_settings().pending_requests_max

    async def register(
        self, node_id: uuid.UUID, websocket: WebSocket
    ) -> tuple[NodeConnection, NodeConnection | None]:
        """Register a connection; returns (new, previous-to-evict)."""
        now = self._clock()
        connection = NodeConnection(
            node_id=node_id, websocket=websocket, connected_at=now, last_heartbeat=now
        )
        async with self._lock:
            previous = self._connections.get(node_id)
            self._connections[node_id] = connection
        if previous is not None:
            # A superseded socket must not strand its in-flight requests.
            _fail_pending(previous, self._offline_error())
        return connection, previous

    async def remove(self, node_id: uuid.UUID, connection: NodeConnection) -> None:
        async with self._lock:
            # Only remove if the current connection is the one we own (avoid
            # evicting a newer replacement).
            if self._connections.get(node_id) is connection:
                del self._connections[node_id]
        _fail_pending(connection, self._offline_error())

    async def evict(self, node_id: uuid.UUID) -> NodeConnection | None:
        """Remove a node's live socket (if any) and return it so the caller can
        close it. Used by credential revoke / node remove, which must sever the
        connection immediately rather than merely refuse future auth."""
        async with self._lock:
            connection = self._connections.pop(node_id, None)
        if connection is not None:
            _fail_pending(connection, self._offline_error())
        return connection

    async def close_all(self, *, code: int) -> int:
        """Drop every daemon socket, failing their in-flight requests (P4-12 drain).

        Used on SIGTERM. Nothing is *told* to reconnect: daemons already reconnect on
        their own backoff (FR-CONN-003), and a shutdown hook that tried to coordinate
        that would be inventing a protocol for the one case where the far side already
        handles it. Pending requests are failed with NODE_OFFLINE rather than left to
        time out, so a request in flight during a deploy gets an answer now instead of
        after the process is gone.
        """
        async with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        for connection in connections:
            _fail_pending(connection, self._offline_error())
            try:
                await connection.websocket.close(code=code)
            except (RuntimeError, OSError):
                # Already gone. A socket that cannot be closed must not stall the drain.
                pass
        return len(connections)

    async def touch(self, node_id: uuid.UUID) -> None:
        async with self._lock:
            connection = self._connections.get(node_id)
            if connection is not None:
                connection.last_heartbeat = self._clock()

    def set_resources(self, node_id: uuid.UUID, resources: dict[str, Any] | None) -> None:
        connection = self._connections.get(node_id)
        if connection is not None:
            connection.resources = resources

    def resources_for(self, node_id: uuid.UUID) -> dict[str, Any] | None:
        connection = self._connections.get(node_id)
        return connection.resources if connection is not None else None

    def claim_metric_sample(self, node_id: uuid.UUID, interval_seconds: float) -> bool:
        """Whether this heartbeat's resources should be persisted (P4-06).

        The decision is made from this process's monotonic clock, never from a
        query: the heartbeat path runs every few seconds per node and must not
        acquire a read just to decide whether to write.

        The slot is claimed here rather than on a successful write, which also rate
        limits *failures*. A node whose inserts keep failing would otherwise retry
        on every heartbeat — six attempts a minute per node, against a database
        that is evidently already unhappy.
        """
        connection = self._connections.get(node_id)
        if connection is None:
            return False
        now = self._clock()
        if (
            connection.last_metric_persist is not None
            and now - connection.last_metric_persist < interval_seconds
        ):
            return False
        connection.last_metric_persist = now
        return True

    def seconds_since_heartbeat(self, node_id: uuid.UUID) -> float | None:
        connection = self._connections.get(node_id)
        if connection is None:
            return None
        return self._clock() - connection.last_heartbeat

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return node_id in self._connections

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # --- Request correlation (tech §7.3) ---

    def _offline_error(self) -> ApiError:
        return ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)

    async def request(
        self,
        node_id: uuid.UUID,
        type_: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        request_id: str | None = None,
    ) -> ControlMessage:
        """Send a control request to a node and await its correlated response.

        Raises NODE_OFFLINE if the node has no live socket, NODE_BUSY when the
        per-node pending bound is reached, and REQUEST_TIMEOUT (cleaning up the
        entry) if the daemon does not answer in time.
        """
        connection = self._connections.get(node_id)
        if connection is None:
            raise self._offline_error()
        if len(connection.pending) >= self._pending_max:
            raise ApiError(
                "NODE_BUSY",
                "Too many in-flight requests for this node",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        rid = request_id or new_request_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ControlMessage] = loop.create_future()
        connection.pending[rid] = future
        # Every Central→daemon request is timed and counted by message type (P4-09,
        # tech §18.1). P3 measured only the filesystem calls, which meant a slow or
        # unanswered `session.start` was invisible while a slow `filesystem.read` was
        # not. `type_` is a closed message-type vocabulary, so it is a safe label.
        metrics.increment(metrics.DAEMON_REQUEST_TOTAL, type=type_)
        started = monotonic_seconds()
        try:
            async with connection.send_lock:
                await connection.websocket.send_text(_request_frame(type_, node_id, rid, payload))
            result = await asyncio.wait_for(future, timeout_seconds)
            metrics.observe(
                metrics.DAEMON_REQUEST_DURATION, monotonic_seconds() - started, type=type_
            )
            return result
        except TimeoutError as exc:
            metrics.increment(metrics.DAEMON_REQUEST_TIMEOUT_TOTAL, type=type_)
            raise ApiError(
                "REQUEST_TIMEOUT",
                "Node did not respond in time",
                status.HTTP_504_GATEWAY_TIMEOUT,
            ) from exc
        finally:
            # Always drop the entry: on success/timeout/cancel a later duplicate
            # is then treated as unknown and safely discarded (late-response
            # cleanup — no write to a released future, no leak).
            connection.pending.pop(rid, None)

    async def send_text_frame(self, node_id: uuid.UUID, frame: str) -> bool:
        """Fire-and-forget control frame to a node (e.g. terminal.resize), with
        no correlated response. Returns False if the node is offline."""
        connection = self._connections.get(node_id)
        if connection is None:
            return False
        async with connection.send_lock:
            await connection.websocket.send_text(frame)
        return True

    async def send_binary(self, node_id: uuid.UUID, frame: bytes) -> bool:
        """Send a raw binary terminal frame to a node (browser→daemon input).

        Fire-and-forget (not correlated); returns False if the node is offline.
        Serialized behind the per-node send-lock so it never interleaves with a
        control frame mid-write.
        """
        connection = self._connections.get(node_id)
        if connection is None:
            return False
        async with connection.send_lock:
            await connection.websocket.send_bytes(frame)
        return True

    def resolve_response(self, node_id: uuid.UUID, message: ControlMessage) -> bool:
        """Deliver a daemon response to its waiting Future.

        Returns False for an unknown/duplicate/late request_id so the caller can
        log a warning and drop it; True when a waiter was resolved.
        """
        connection = self._connections.get(node_id)
        if connection is None:
            return False
        future = connection.pending.get(message.request_id)
        if future is None or future.done():
            return False
        future.set_result(message)
        return True

    def is_pending(self, node_id: uuid.UUID, request_id: str) -> bool:
        connection = self._connections.get(node_id)
        return connection is not None and request_id in connection.pending


def _fail_pending(connection: NodeConnection, exc: BaseException) -> None:
    for future in list(connection.pending.values()):
        if not future.done():
            future.set_exception(exc)
    connection.pending.clear()


def compute_status(
    *,
    is_enabled: bool,
    seconds_since_heartbeat: float | None,
    online_within: int,
    degraded_within: int,
) -> str:
    if not is_enabled:
        return DISABLED
    if seconds_since_heartbeat is None:
        return OFFLINE
    if seconds_since_heartbeat <= online_within:
        return ONLINE
    if seconds_since_heartbeat <= degraded_within:
        return DEGRADED
    return OFFLINE


_registry: NodeConnectionRegistry | None = None


def get_node_registry() -> NodeConnectionRegistry:
    global _registry
    if _registry is None:
        _registry = NodeConnectionRegistry()
    return _registry
