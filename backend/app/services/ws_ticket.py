"""Single-use, short-lived WebSocket tickets for browser WS auth (ADR 0007).

A JS WebSocket cannot send an Authorization header and a long-lived JWT must
never sit in a query string, so an authenticated HTTP call mints a one-shot
ticket bound to (user, resource). Expiry uses a monotonic clock so wall-clock
skew cannot extend a ticket's life. In-memory (like the connection registry);
a multi-process deployment would move this to a shared store.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from app.clock import monotonic_seconds
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class _Ticket:
    user_id: uuid.UUID
    resource: str
    expires_at_monotonic: float


class WsTicketService:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._tickets: dict[str, _Ticket] = {}

    def issue(self, user_id: uuid.UUID, resource: str) -> str:
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = _Ticket(
            user_id=user_id,
            resource=resource,
            expires_at_monotonic=monotonic_seconds() + self._ttl,
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
        _service = WsTicketService(get_settings().ws_ticket_ttl_seconds)
    return _service
