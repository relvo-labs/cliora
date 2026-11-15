"""Single-use, short-lived WebSocket tickets for browser WS auth (ADR 0007).

A JS WebSocket cannot send an Authorization header and a long-lived JWT must
never sit in a query string, so an authenticated HTTP call mints a one-shot
ticket bound to (user, resource). Expiry uses a monotonic clock so wall-clock
skew cannot extend a ticket's life. In-memory (like the connection registry);
a multi-process deployment would move this to a shared store.

Issuance sweeps a bounded number of expired entries. A fixed TTL and monotonic
issue order make the oldest entry the next to expire. The hard process-wide cap
also bounds abandoned tickets between sweeps; overflow evicts the oldest ticket
(even if still live), so the newest request can connect. Callers of issue() must
authorize the resource first; consumers must re-check current authorization.
"""

from __future__ import annotations

import secrets
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from app.clock import monotonic_seconds
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class _Ticket:
    user_id: uuid.UUID
    resource: str
    expires_at_monotonic: float


class WsTicketService:
    def __init__(
        self, ttl_seconds: int, *, max_pending: int = 4096, sweep_batch_size: int = 128
    ) -> None:
        if max_pending < 1 or sweep_batch_size < 1:
            raise ValueError("ticket capacity and sweep batch size must be positive")
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._sweep_batch_size = sweep_batch_size
        self._tickets: OrderedDict[str, _Ticket] = OrderedDict()

    def issue(self, user_id: uuid.UUID, resource: str) -> str:
        now = monotonic_seconds()
        # No full scan or secondary expiry index: consumed tickets leave no
        # tombstones, and each call does at most one batch of O(1) removals.
        for _ in range(self._sweep_batch_size):
            if not self._tickets:
                break
            oldest = next(iter(self._tickets.values()))
            if now < oldest.expires_at_monotonic:
                break
            self._tickets.popitem(last=False)
        if len(self._tickets) >= self._max_pending:
            self._tickets.popitem(last=False)
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = _Ticket(
            user_id=user_id,
            resource=resource,
            expires_at_monotonic=now + self._ttl,
        )
        return ticket

    def consume(self, ticket: str, resource: str) -> uuid.UUID | None:
        """Validate and burn a ticket; returns the bound user id or None."""
        entry = self._tickets.pop(ticket, None)
        if entry is None:
            return None
        if entry.resource != resource:
            return None
        # Equal boundary is treated as expired (consistent with token expiry).
        if monotonic_seconds() >= entry.expires_at_monotonic:
            return None
        return entry.user_id


_service: WsTicketService | None = None


def get_ws_ticket_service() -> WsTicketService:
    global _service
    if _service is None:
        settings = get_settings()
        _service = WsTicketService(
            settings.ws_ticket_ttl_seconds,
            max_pending=settings.ws_ticket_max_pending,
            sweep_batch_size=settings.ws_ticket_sweep_batch_size,
        )
    return _service
