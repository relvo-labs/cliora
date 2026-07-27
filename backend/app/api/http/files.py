"""Read-only filesystem HTTP API (P3-06). RBAC-guarded (file.browse) browser
boundary that relays directory listing, filename search, and single-file
preview to the daemon via the request-correlation path. Central authorizes and
relays only — it never reads the node filesystem and never returns a server
absolute path (ADR 0014). Denials (sensitive/binary/oversize) come back in-band
in the content body with success:false; path/existence errors surface as safe
ApiError responses via the global handler.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.db.engine import get_session
from app.db.models import User
from app.services.files import FileRelayService
from app.services.rbac import FILE_BROWSE
from app.services.registry import NodeConnectionRegistry, get_node_registry

router = APIRouter(prefix="/api/sessions/{session_id}/files", tags=["files"])


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


@router.get("/tree")
async def list_tree(
    session_id: uuid.UUID,
    path: str = Query(default="."),
    cursor: str | None = Query(default=None),
    entry_limit: int | None = Query(default=None, ge=1, le=2000),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    return await service.list_dir(
        actor=user, session_id=session_id, path=path, cursor=cursor, entry_limit=entry_limit
    )


@router.get("/search")
async def search_files(
    session_id: uuid.UUID,
    keyword: str = Query(min_length=1, max_length=256),
    root: str | None = Query(default=None),
    max_results: int | None = Query(default=None, ge=1, le=200),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    return await service.search(
        actor=user, session_id=session_id, keyword=keyword, root=root, max_results=max_results
    )


@router.get("/content")
async def read_content(
    session_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=4096),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    payload = await service.read_file(actor=user, session_id=session_id, path=path)
    # A sensitive-read denial is audited inside read_file; commit that entry.
    await session.commit()
    return payload
