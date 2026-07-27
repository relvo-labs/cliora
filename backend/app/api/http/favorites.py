"""Workspace favourites and recents (P4-13, FR-WORKSPACE-004/005).

Guarded by `session.create`, because that is what these are for: getting to a new session
faster. A Viewer cannot create sessions, so has nothing to shortcut (ADR 0016). Widening
this to `file.browse` for read-only convenience would be a permission change, and must
land together with its row in the P4-03 matrix — not be adjusted here.

Nothing in this module reads a node filesystem. It is Central metadata only; the path in
a favourite is re-authorized on every use and re-resolved canonically by the daemon.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.api.http.schemas import (
    CreateWorkspaceFavoriteRequest,
    RecentWorkspaceDTO,
    WorkspaceFavoriteDTO,
)
from app.db.engine import get_session
from app.db.models import User
from app.repositories.nodes import NodeRepository
from app.services.favorites import FavoriteService, node_is_online
from app.services.rbac import SESSION_CREATE
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


@router.get("/favorites", response_model=list[WorkspaceFavoriteDTO])
async def list_favorites(
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> list[WorkspaceFavoriteDTO]:
    """The caller's own favourites. Never anyone else's — a per-user list that leaked
    would disclose one user's workspace layout to another."""
    service = FavoriteService(session, settings=settings)
    rows = await service.list_favorites(
        user, seconds_since_heartbeat=registry.seconds_since_heartbeat
    )
    return [
        WorkspaceFavoriteDTO(
            id=row.favorite.id,
            node_id=row.favorite.node_id,
            node_name=row.node_name,
            path=row.favorite.path,
            display_name=row.favorite.display_name,
            created_at=row.favorite.created_at,
            usability=usability,
        )
        for row, usability in rows
    ]


@router.post("/favorites", response_model=WorkspaceFavoriteDTO)
async def add_favorite(
    body: CreateWorkspaceFavoriteRequest,
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> WorkspaceFavoriteDTO:
    """Save a favourite, or return the one that already exists.

    200 rather than 201/409 in both cases, deliberately: favouriting something twice is
    the same intent expressed twice, and a conflict would make the UI's optimistic toggle
    need a special case for "already there".
    """
    service = FavoriteService(session, settings=settings)
    favorite = await service.add(
        user, node_id=body.node_id, path=body.path, display_name=body.display_name
    )
    await session.commit()
    node = await NodeRepository(session).get(favorite.node_id)
    return WorkspaceFavoriteDTO(
        id=favorite.id,
        node_id=favorite.node_id,
        node_name=node.name if node else "",
        path=favorite.path,
        display_name=favorite.display_name,
        created_at=favorite.created_at,
        # The same verdict the next listing will report. Computing it here rather than
        # assuming `usable` matters because `add` accepts an offline node on purpose.
        usability=await service.usability(favorite, registry.seconds_since_heartbeat),
    )


@router.delete("/favorites/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    favorite_id: uuid.UUID,
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Another user's favourite answers 404, not 403: a 403 would confirm the id exists,
    which is how a per-user list becomes a way to probe other users' rows."""
    await FavoriteService(session, settings=settings).remove(user, favorite_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/recent", response_model=list[RecentWorkspaceDTO])
async def list_recent(
    limit: int | None = Query(default=None, ge=1, le=20),
    user: User = Depends(require_action(SESSION_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> list[RecentWorkspaceDTO]:
    """Where this user recently worked, derived from `terminal_sessions`.

    Disabled and offline nodes are annotated rather than filtered: an entry that silently
    vanishes reads as data loss, while "that machine is down" is actionable.
    """
    service = FavoriteService(session, settings=settings)
    nodes = NodeRepository(session)
    items: list[RecentWorkspaceDTO] = []
    for recent in await service.recent(user, limit=limit):
        node = await nodes.get(recent.node_id)
        items.append(
            RecentWorkspaceDTO(
                node_id=recent.node_id,
                node_name=recent.node_name,
                path=recent.path,
                last_used_at=recent.last_used_at,
                node_online=node_is_online(
                    node, registry.seconds_since_heartbeat(recent.node_id), settings
                ),
                node_enabled=recent.node_enabled,
            )
        )
    return items
