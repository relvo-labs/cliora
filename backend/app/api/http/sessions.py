"""Session HTTP API (PRD §11.6). RBAC-guarded browser boundary that delegates
to the session domain service and is the first production caller of the daemon
request-correlation path (services/registry.py). Central never accepts a
command/binary/shell string — only runtime id, workspace, name and size."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.api.http.schemas import (
    AttachTicketResponse,
    CreateSessionRequest,
    OpenShellRequest,
    SessionDetail,
    SessionSummary,
)
from app.db.engine import get_session
from app.db.models import ActivityEvent, TerminalSession, User
from app.repositories.nodes import NodeRepository
from app.services import authz
from app.services.context_projection import ProjectionOutcome
from app.services.rbac import (
    SESSION_CREATE,
    SESSION_TERMINATE,
    SESSION_VIEW,
    TERMINAL_SHELL,
)
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.sessions import SessionService
from app.services.ws_ticket import get_ws_ticket_service
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_registry() -> NodeConnectionRegistry:
    """Registry dependency (overridable in tests)."""
    return get_node_registry()


def attach_resource(session_id: uuid.UUID) -> str:
    """Resource string a terminal ws-ticket is bound to (consumed by P2-09)."""
    return f"session:{session_id}"


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
    # Injected rather than read from the process-wide cache: `create` consults
    # `projects_enabled`, and a service that resolves its own settings cannot be
    # overridden per request — which is also how a test would silently exercise the
    # wrong configuration.
    settings: Settings = Depends(get_settings),
) -> SessionDetail:
    service = SessionService(session, registry=registry, settings=settings)
    try:
        result = await service.create(
            actor_id=user.id,
            node_id=body.node_id,
            runtime=body.runtime,
            name=body.name,
            workspace=body.workspace,
            rows=body.rows,
            columns=body.columns,
            project_id=body.project_id,
            task_id=body.task_id,
        )
    except ApiError:
        # Persist a FAILED row + failure audit if one was created before the
        # daemon round-trip failed; pre-insert guard errors commit nothing.
        await session.commit()
        raise
    await session.commit()
    # The context projection is a **second** round trip, after the session is already
    # running and committed (ADR 0028 sec 5, `plan/17` D8). Two consequences, both
    # deliberate: `session.start` has already succeeded, so nothing here can roll it
    # back; and a failure is recorded rather than raised, because context is an
    # addition and the session is the product.
    outcome = None
    if result.project_id is not None:
        outcome = await _project_context(
            session, registry, settings, terminal=result, actor_id=user.id
        )
        await session.commit()
    return SessionDetail.from_model(
        result,
        viewer=user,
        context_projection=outcome.status if outcome else None,
        context_projection_detail=outcome.detail if outcome else None,
    )


async def _project_context(
    session: AsyncSession,
    registry: NodeConnectionRegistry,
    settings: Settings,
    *,
    terminal: TerminalSession,
    actor_id: uuid.UUID,
) -> ProjectionOutcome:
    from app.services import audit
    from app.services.activity import SESSION_CONTEXT_PROJECTION, ActivityService
    from app.services.audit import AuditService
    from app.services.context_projection import ContextProjectionService

    node = await NodeRepository(session).get(terminal.node_id)
    if node is None or terminal.project_id is None:  # pragma: no cover
        return ProjectionOutcome(status="failed", written=[], skipped=[], detail="node missing")
    project_id = terminal.project_id
    outcome = await ContextProjectionService(session, settings=settings).project(
        terminal=terminal, node=node, actor_id=actor_id, registry=registry
    )
    # Record every outcome, not only failure. Session detail derives its durable
    # status from the latest row, so a successful retry supersedes an earlier fault.
    await ActivityService(session).record(
        SESSION_CONTEXT_PROJECTION,
        project_id=project_id,
        actor_user_id=actor_id,
        session_id=terminal.id,
        task_id=terminal.task_id,
        payload={"context_projection": outcome.status, "detail": outcome.detail},
    )
    await AuditService(session).record(
        audit.SESSION_CONTEXT_PROJECTION,
        user_id=actor_id,
        session_id=terminal.id,
        metadata={"status": outcome.status, "project_id": str(project_id)},
    )
    return outcome


async def _projection_state(
    session: AsyncSession, terminal: TerminalSession
) -> tuple[str | None, str | None]:
    if terminal.project_id is None:
        return None, None
    row = (
        await session.execute(
            select(ActivityEvent)
            .where(
                ActivityEvent.session_id == terminal.id,
                ActivityEvent.kind == "session.context_projection",
            )
            .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return "pending", None
    payload = row.activity_payload or {}
    return str(payload.get("context_projection") or "failed"), (
        str(payload["detail"]) if payload.get("detail") else None
    )


async def _session_detail(
    session: AsyncSession, terminal: TerminalSession, user: User
) -> SessionDetail:
    projection, detail = await _projection_state(session, terminal)
    return SessionDetail.from_model(
        terminal,
        viewer=user,
        context_projection=projection,
        context_projection_detail=detail,
    )


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    node_id: uuid.UUID | None = None,
    # Three value ranges: absent means every session (identical to before the project
    # layer existed), a uuid means that project's, and the literal `none` means the
    # ad-hoc ones. The third exists so "how many sessions are actually ad-hoc" is
    # answerable — the measurement that decides whether V2's defaults are right.
    project_id: str | None = Query(default=None),
    task_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_action(SESSION_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[SessionSummary]:
    """Every `session.view` holder sees the whole fleet's sessions (ADR 0016: a
    Developer may see a colleague's session but not act on it). Per-row
    capability flags say which of those they may actually operate on."""
    sessions = await SessionService(session, settings=settings).list(
        node_id=node_id,
        project_id=project_id,
        task_id=task_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return [SessionSummary.from_model(s, viewer=user) for s in sessions]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> SessionDetail:
    result = await SessionService(session).get(session_id)
    authz.authorize_session_view(user, result)
    return await _session_detail(session, result, user)


@router.post("/{session_id}/context-projection", response_model=SessionDetail)
async def retry_context_projection(
    session_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> SessionDetail:
    service = SessionService(session, settings=settings)
    terminal = await service.get(session_id)
    authz.authorize_session_context_projection(user, terminal)
    if terminal.project_id is None:
        raise ApiError(
            "SESSION_INVALID_STATE",
            "This session has no project context",
            status.HTTP_409_CONFLICT,
        )
    if terminal.ended_at is not None:
        raise ApiError(
            "SESSION_INVALID_STATE",
            "An ended session cannot receive new context",
            status.HTTP_409_CONFLICT,
        )
    await _project_context(session, registry, settings, terminal=terminal, actor_id=user.id)
    await session.commit()
    return await _session_detail(session, terminal, user)


@router.post("/{session_id}/terminate", response_model=SessionDetail)
async def terminate_session(
    session_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_TERMINATE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> SessionDetail:
    service = SessionService(session, registry=registry)
    # Load first, then check ownership: `session.terminate` alone is not enough —
    # only the owner or an Admin may end a session (ADR 0016).
    existing = await service.get(session_id)
    authz.authorize_session_terminate(user, existing)
    result = await service.terminate(actor_id=user.id, session_id=session_id)
    await session.commit()
    return await _session_detail(session, result, user)


@router.post(
    "/{session_id}/shell",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def open_shell(
    session_id: uuid.UUID,
    body: OpenShellRequest,
    user: User = Depends(require_action(TERMINAL_SHELL)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> SessionDetail:
    """Open a system terminal inside a CLI session (FR-SHELL-001, ADR 0021).

    The parent is in the path rather than the body, so a shell session cannot be
    created without one — that structural choice, not a validation rule, is what
    keeps shells out of the New Session dialog and the session list.

    Two layers, in this order: `terminal.shell` (action) then ownership of the
    parent (scope). An Admin holds the action but not other people's sessions.
    """
    service = SessionService(session, registry=registry)
    parent = await service.get(session_id)
    if not authz.may_open_shell(user, parent):
        raise authz.forbidden_shell(user, parent)
    try:
        result = await service.open_shell(
            actor_id=user.id, parent=parent, rows=body.rows, columns=body.columns
        )
    except ApiError:
        # Same reasoning as create(): a row and a failure audit may already exist.
        await session.commit()
        raise
    await session.commit()
    return await _session_detail(session, result, user)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_TERMINATE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = SessionService(session)
    existing = await service.get(session_id)
    authz.authorize_session_terminate(user, existing)
    await service.delete(session_id=session_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/attach", response_model=AttachTicketResponse)
async def attach_session(
    session_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> AttachTicketResponse:
    """Mint a single-use ws-ticket bound to (user, session) for the terminal WS
    (P2-09). Verifies the session exists first (404 otherwise)."""
    existing = await SessionService(session).get(session_id)
    authz.authorize_session_view(user, existing)
    ticket = get_ws_ticket_service().issue(user.id, attach_resource(session_id))
    return AttachTicketResponse(session_id=session_id, ticket=ticket)
