"""HTTP middleware: request correlation and the authorization-denial audit.

`RequestIdMiddleware` correlates every request in logs, responses and audit rows.
`AuthzDenialAuditMiddleware` turns a refused mutation into an accountable event.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import metrics
from app.clock import monotonic_seconds
from app.logging import get_logger, request_id_var

HEADER = "x-request-id"
_logger = get_logger("cliora.api")

# Set by the two places that can refuse on authorization grounds — the action
# guard (`api/http/deps.require_action`) and the resource layer
# (`services/authz`) — and read by the middleware below. A contextvar is used
# rather than threading a database session into the authorization code, which has
# no business holding one: the refusal decision must not depend on a write
# succeeding, and the audit row must land even when the request's own transaction
# has already been rolled back.
denial_var: ContextVar[tuple[str, str] | None] = ContextVar("authz_denial", default=None)
# Set by `get_current_user` so a refusal can name its actor.
actor_var: ContextVar[uuid.UUID | None] = ContextVar("authz_actor", default=None)

# Only refusals of a *mutation*, or a cross-owner ("scope") refusal of any method,
# are recorded (ADR 0016). Plain read 403s are frequent and uninteresting;
# auditing them would bury the signal this event exists to provide.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get(HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[HEADER] = request_id
        return response


class HttpMetricsMiddleware:
    """Time every HTTP request, labelled by method, route template and status class
    (tech §18.1).

    Three deliberate choices about the labels, all about cardinality:

    * **the route template, not the path.** `/api/sessions/{session_id}/files/content`
      is one series; the actual path would create one per session, forever. The
      template comes from the matched Starlette route, which is only available *after*
      routing — hence a pure ASGI middleware reading `scope["route"]` on the way out.
    * **a status class, not the code.** `2xx`/`4xx`/`5xx` answers "is this endpoint
      healthy"; the exact code is in the log line next to the request id.
    * **an unmatched request is one series, not one per URL.** A 404 for a random path
      records `route="<unmatched>"`, so a scanner probing a thousand URLs cannot grow
      the series set at all.

    Pure ASGI rather than `BaseHTTPMiddleware` for the same reason as the denial audit:
    it needs the scope the router populated, in the same context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        started = monotonic_seconds()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.observe(
                metrics.HTTP_REQUEST_DURATION,
                monotonic_seconds() - started,
                method=str(scope.get("method", "")),
                route=_route_template(scope),
                status_class=_status_class(status_code),
            )


def _route_template(scope: Scope) -> str:
    """The matched route's path template, or a single bucket for anything unmatched."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "<unmatched>"


def _status_class(status_code: int) -> str:
    if status_code <= 0:
        # The app raised before sending a response start; the exception handler will
        # have produced a 500, but this middleware never saw it.
        return "5xx"
    return f"{status_code // 100}xx"


class AuthzDenialAuditMiddleware:
    """Record `authz.denied` for a refused mutation or cross-owner access.

    Deliberately a **pure ASGI** middleware rather than a `BaseHTTPMiddleware`:
    the latter runs the downstream app in a separate anyio task, so a contextvar
    set by the route (here, `denial_var`) is written in a child context and is
    invisible to the middleware afterwards. Calling the app directly keeps one
    context, which is what makes the denial observable at all.

    The row is written on its own short-lived session, because the request's own
    session may have been rolled back or closed and the audit must survive that. A
    failed write is counted and logged, never turned into a different response: the
    user is being refused either way, and converting an audit fault into a 500
    would hide the refusal.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        denial_token = denial_var.set(None)
        actor_token = actor_var.set(None)
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            denial = denial_var.get()
            if status_code == 403 and denial is not None:
                method = scope.get("method", "")
                if method in _MUTATING_METHODS or denial[1] == "scope":
                    await self._record(method, scope.get("path", ""), denial, actor_var.get())
        finally:
            denial_var.reset(denial_token)
            actor_var.reset(actor_token)

    async def _record(
        self, method: str, path: str, denial: tuple[str, str], actor_id: uuid.UUID | None
    ) -> None:
        from app import metrics
        from app.db.engine import get_database
        from app.services import audit

        action, reason = denial
        try:
            async with get_database().session() as session:
                await audit.AuditService(session).record(
                    audit.AUTHZ_DENIED,
                    user_id=actor_id,
                    metadata={
                        "denied_action": action,
                        "reason": reason,
                        "method": method,
                        # The API route path. It may embed a resource id, which is
                        # exactly what an investigation needs; it is never a
                        # filesystem path.
                        "path": path[:256],
                    },
                )
                await session.commit()
        except Exception:
            metrics.increment(metrics.AUDIT_ERROR_TOTAL, action=audit.AUTHZ_DENIED)
            _logger.warning("audit_write_failed", extra={"event": "audit_write_failed"})
