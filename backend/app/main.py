"""The Cliora Central ASGI application.

P4-07 retired the P0 development relay that used to live here: `/ws/p0/daemon`,
`/ws/p0/sessions/{id}/terminal` and their shared-static-token `authorized()` check
(ADR 0006, superseded by ADR 0016). The P2 relay replaced it functionally in full,
which left those endpoints as the only WebSocket surface in the app authorized by a
single static token shared by every client — an unmaintained authorization bypass,
kept alive only by a fail-closed environment check. Deleting it removes the bypass
rather than continuing to guard it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.api.errors import install_error_handlers
from app.api.http.audit import router as audit_router
from app.api.http.auth import router as auth_router
from app.api.http.dashboard import router as dashboard_router
from app.api.http.downloads import router as downloads_router
from app.api.http.enrollment import router as enrollment_router
from app.api.http.favorites import router as favorites_router
from app.api.http.files import router as files_router
from app.api.http.integrations import router as integrations_router
from app.api.http.metrics import router as metrics_router
from app.api.http.nodes import router as nodes_router
from app.api.http.releases import router as releases_router
from app.api.http.sessions import router as sessions_router
from app.api.http.tunnels import router as tunnels_router
from app.api.middleware import (
    AuthzDenialAuditMiddleware,
    HttpMetricsMiddleware,
    RequestIdMiddleware,
)
from app.api.ws.nodes import router as node_ws_router
from app.api.ws.terminal import router as terminal_ws_router
from app.db.engine import get_database, reset_database
from app.logging import configure_logging, get_logger
from app.security import secret_box
from app.services.registry import get_node_registry
from app.services.shell_reaper import get_shell_reaper
from app.services.terminal_relay import get_terminal_relay
from app.settings import get_settings

_logger = get_logger("cliora.central")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    _logger.info("central_startup", extra={"event": "central_startup"})
    await _rearm_shell_reaper()
    try:
        yield
    finally:
        await _drain()
        await reset_database()
        _logger.info("central_shutdown", extra={"event": "central_shutdown"})


async def _rearm_shell_reaper() -> None:
    """Re-arm the idle-shell timers this process lost when it last stopped.

    The counterpart to `cancel_all()` in `_drain()`: dropping the timers keeps a
    deploy from tearing down open terminals, but the shells detached during the
    restart would otherwise have nobody left to collect them (see
    `ShellReaper.reconcile`).

    A failure here must not stop Central from serving. The cost of skipping it is a
    stale shell row, which the next detach or the owner's next open now resolves;
    the cost of refusing to boot is the whole product.
    """
    try:
        await get_shell_reaper().reconcile()
    except Exception as exc:  # noqa: BLE001 - startup must not depend on this
        _logger.warning(
            "shell_reaper_reconcile_failed",
            extra={"event": "shell_reaper_reconcile_failed", "error": type(exc).__name__},
        )


async def _drain() -> None:
    """Wind down on SIGTERM in an order the operator and the user can both live with.

    1. Tell every subscribed browser *why* it is about to be disconnected, so a deploy
       reads as "reconnecting" rather than as an unexplained drop.
    2. Close the daemon sockets. Daemons reconnect on their existing backoff
       (FR-CONN-003), so nothing needs to be told anything.

    **No CLI session is ever terminated here.** NFR-002 says a browser disconnect must
    not end a session; a Central restart is the same promise seen from the other side,
    and it is the promise most easily broken by a shutdown hook that "tidies up".
    Nothing in this function touches tmux or sends `session.stop`.

    Bounded by `shutdown_drain_seconds` on the monotonic clock. Exceeding the bound logs
    and proceeds: a stuck socket must not turn a deploy into an outage, and since the
    sessions survive regardless there is nothing to protect by waiting longer.
    """
    settings = get_settings()
    started = time.monotonic()
    relay = get_terminal_relay()
    registry = get_node_registry()
    browsers = relay.connection_count()
    daemons = registry.connection_count
    try:
        async with asyncio.timeout(settings.shutdown_drain_seconds):
            await relay.announce_shutdown("server_restarting")
            # Drop the idle-shell timers rather than letting them fire mid-drain:
            # a deploy must not turn into a fleet-wide teardown of open terminals.
            await get_shell_reaper().cancel_all()
            await registry.close_all(code=1012)
    except TimeoutError:
        _logger.warning(
            "shutdown_drain_timeout",
            extra={
                "event": "shutdown_drain_timeout",
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
    _logger.info(
        "shutdown_drained",
        extra={
            "event": "shutdown_drained",
            "browser_connections": browsers,
            "daemon_connections": daemons,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )


app = FastAPI(title="Cliora Central", version="0.2.0", lifespan=lifespan)
# Order matters: add_middleware puts the *last* added outermost. The denial audit
# must sit inside RequestIdMiddleware so `request_id_var` is still set when it
# writes its row — otherwise the audit entry cannot be joined to the request's logs.
app.add_middleware(HttpMetricsMiddleware)
app.add_middleware(AuthzDenialAuditMiddleware)
app.add_middleware(RequestIdMiddleware)
install_error_handlers(app)
app.include_router(auth_router)
app.include_router(enrollment_router)
app.include_router(nodes_router)
app.include_router(sessions_router)
app.include_router(tunnels_router)
app.include_router(integrations_router)
app.include_router(files_router)
app.include_router(favorites_router)
app.include_router(audit_router)
app.include_router(dashboard_router)
app.include_router(releases_router)
app.include_router(metrics_router)
app.include_router(downloads_router)
app.include_router(node_ws_router)
app.include_router(terminal_ws_router)


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _database_ready() -> bool:
    try:
        async with get_database().engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


_MIGRATIONS_DIR = Path(__file__).resolve().parent / "db" / "migrations"


def _expected_migration_heads() -> set[str]:
    try:
        return set(ScriptDirectory(str(_MIGRATIONS_DIR)).get_heads())
    except Exception:
        return set()


async def _migration_head_applied() -> bool:
    """True when the DB's applied revision(s) match the migration head(s)."""
    expected = _expected_migration_heads()
    if not expected:
        return False
    try:
        async with get_database().engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            current = {row[0] for row in result}
    except Exception:
        return False
    return current == expected


@app.get("/readyz")
async def ready(response: Response) -> dict[str, object]:
    """Readiness, expressed in the status code as well as the body.

    The body alone was not enough. A managed platform's health check reads the
    **status code** and nothing else (Railway is the case that forced this — see ADR
    0020), so a `200 {"status": "degraded"}` meant a Central that could not reach its
    database, or was running against an unmigrated schema, passed the check and took
    traffic. The rule "an unready replica does not serve" then existed only in the
    compose healthcheck, which parses the body, and nowhere else.

    503 also settles a disagreement that was already in the tree:
    `scripts/p4/drills/db-exhaustion.sh` tells the operator to "expect some 503s" when
    the pool is saturated, but `_database_ready()` swallows the checkout timeout and
    returned 200 — so that drill's stated expectation had never once held.

    The body keeps both booleans: which half is broken decides which runbook to open.
    """
    database_ok = await _database_ready()
    migration_ok = await _migration_head_applied() if database_ok else False
    ready_ok = database_ok and migration_ok
    if not ready_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready_ok else "degraded",
        "database": database_ok,
        # A *feature* being unavailable is not a replica being unready (P11 §2.5). Without an
        # encryption key the port-forwarding integration cannot store a provider credential,
        # and most deployments do not use it — making that a startup failure would force
        # every one of them to generate a key they never use. It is reported here instead, so
        # an operator finds out from readiness rather than from an administrator's 503.
        "tunnel_integration": (
            "available" if secret_box.is_available() else "unavailable: no encryption key"
        ),
        # Counted from the authenticated daemon registry, which is now the only one.
        # It used to report the P0 relay's registry, so a real fleet of enrolled nodes
        # showed `daemon_connected: false` while the dev relay showed true.
        "daemon_connected": get_node_registry().connection_count > 0,
    }
