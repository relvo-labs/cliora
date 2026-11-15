"""Single-use, short-lived WebSocket tickets for browser WS auth (ADR 0007).

A JS WebSocket cannot send an Authorization header and a long-lived JWT must
never sit in a query string, so an authenticated HTTP call mints a one-shot
ticket bound to (user, resource). Expiry uses a monotonic clock so wall-clock
skew cannot extend a ticket's life. In-memory (like the connection registry);
a multi-process deployment would move this to a shared store.

Issuance sweeps a bounded number of expired entries. A fixed TTL and monotonic
issue order make the oldest entry the next to expire. Per-user and process-wide
pending caps reject new issuance without evicting live tickets. A user's expired
tickets are swept first, sharing the same removal budget with the global sweep,
so other users' expiry backlogs cannot prevent that user's quota from recovering.
Callers of issue() must authorize the resource first; consumers must re-check
current authorization.
"""

from __future__ import annotations

import secrets
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import status

from app.api.error_catalog import safe_message
from app.api.errors import ApiError
from app.clock import monotonic_seconds
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class _Ticket:
    user_id: uuid.UUID
    resource: str
    expires_at_monotonic: float


class WsTicketService:
    def __init__(
        self,
        ttl_seconds: int,
        *,
        max_pending: int = 4096,
        max_pending_per_user: int = 32,
        sweep_batch_size: int = 128,
    ) -> None:
        if max_pending < 1 or max_pending_per_user < 1 or sweep_batch_size < 1:
            raise ValueError("ticket capacity and sweep batch size must be positive")
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._max_pending_per_user = max_pending_per_user
        self._sweep_batch_size = sweep_batch_size
        self._tickets: OrderedDict[str, _Ticket] = OrderedDict()
        self._tickets_by_user: dict[uuid.UUID, OrderedDict[str, _Ticket]] = {}

    def _remove(self, ticket: str) -> _Ticket | None:
        entry = self._tickets.pop(ticket, None)
        if entry is not None:
            owned = self._tickets_by_user[entry.user_id]
            del owned[ticket]
            if not owned:
                del self._tickets_by_user[entry.user_id]
        return entry

    def _sweep(self, tickets: OrderedDict[str, _Ticket], now: float, budget: int) -> int:
        removed = 0
        for _ in range(budget):
            if not tickets:
                break
            ticket = next(iter(tickets))
            if now < tickets[ticket].expires_at_monotonic:
                break
            self._remove(ticket)
            removed += 1
        return removed

    def issue(self, user_id: uuid.UUID, resource: str) -> str:
        now = monotonic_seconds()
        # Both indexes contain only stored tickets, with no consumed tombstones.
        # No full scan: each issue shares one batch of O(1) removals across them.
        owned = self._tickets_by_user.get(user_id)
        removed = self._sweep(owned, now, self._sweep_batch_size) if owned else 0
        self._sweep(self._tickets, now, self._sweep_batch_size - removed)
        if len(self._tickets_by_user.get(user_id, ())) >= self._max_pending_per_user:
            raise ApiError(
                "WS_TICKET_BUSY",
                safe_message("WS_TICKET_BUSY"),
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if len(self._tickets) >= self._max_pending:
            raise ApiError(
                "INTERNAL_ERROR",
                safe_message("INTERNAL_ERROR"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        ticket = secrets.token_urlsafe(32)
        entry = _Ticket(
            user_id=user_id,
            resource=resource,
            expires_at_monotonic=now + self._ttl,
        )
        self._tickets[ticket] = entry
        self._tickets_by_user.setdefault(user_id, OrderedDict())[ticket] = entry
        return ticket

    def consume(self, ticket: str, resource: str) -> uuid.UUID | None:
        """Validate and burn a ticket; returns the bound user id or None."""
        entry = self._remove(ticket)
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
            max_pending_per_user=settings.ws_ticket_max_pending_per_user,
            sweep_batch_size=settings.ws_ticket_sweep_batch_size,
        )
    return _service
