"""Session HTTP API (PRD §11.6). RBAC-guarded browser boundary that delegates
to the session domain service and is the first production caller of the daemon
request-correlation path (services/registry.py). Central never accepts a
command/binary/shell string — only runtime id, workspace, name and size."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.api.http.schemas import (
    AttachTicketResponse,
    CreateSessionRequest,
    SessionDetail,
    SessionSummary,
)
from app.db.engine import get_session
from app.db.models import User
from app.services import authz
from app.services.rbac import SESSION_CREATE, SESSION_TERMINATE, SESSION_VIEW
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.sessions import SessionService
from app.services.ws_ticket import get_ws_ticket_service

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
) -> SessionDetail:
    service = SessionService(session, registry=registry)
    try:
        result = await service.create(
            actor_id=user.id,
            node_id=body.node_id,
            runtime=body.runtime,
            name=body.name,
            workspace=body.workspace,
            rows=body.rows,
            columns=body.columns,
        )
    except ApiError:
        # Persist a FAILED row + failure audit if one was created before the
        # daemon round-trip failed; pre-insert guard errors commit nothing.
        await session.commit()
        raise
    await session.commit()
    return SessionDetail.from_model(result, viewer=user)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    node_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_action(SESSION_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> list[SessionSummary]:
    """Every `session.view` holder sees the whole fleet's sessions (ADR 0016: a
    Developer may see a colleague's session but not act on it). Per-row
    capability flags say which of those they may actually operate on."""
    sessions = await SessionService(session).list(
        node_id=node_id, status_filter=status_filter, limit=limit, offset=offset
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
    return SessionDetail.from_model(result, viewer=user)


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
    return SessionDetail.from_model(result, viewer=user)


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
