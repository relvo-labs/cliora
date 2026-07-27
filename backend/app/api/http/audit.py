"""Audit-trail query endpoint (P4-05, FR-AUTH-002, SEC-006).

Admin-only (`audit.view`). This route is what finally makes that permission real:
it was seeded to Admin in migration `0002` and checked by nothing for three
phases, which is why `rbac.UNENFORCED_ACTIONS` exists and why `audit.view` has
now been removed from it.

Central holds the bounds; the browser only asks. Validation, the closed action
vocabulary, the time-window cap and the keyset cursor all live in
`services/audit_query.py` so a second caller cannot get a laxer version of them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.api.http.schemas import AuditPageDTO
from app.db.engine import get_session
from app.db.models import User
from app.services.audit_query import AuditQueryService
from app.services.rbac import AUDIT_VIEW

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditPageDTO)
async def list_audit(
    action: list[str] | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    node_id: uuid.UUID | None = Query(default=None),
    session_id: uuid.UUID | None = Query(default=None),
    # Named `from`/`to` on the wire; `from` is a Python keyword, hence the alias.
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    limit: int | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    _: User = Depends(require_action(AUDIT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> AuditPageDTO:
    """Reading the trail is deliberately not itself audited (ADR 0016)."""
    page = await AuditQueryService(session).query(
        actions=action,
        user_id=user_id,
        node_id=node_id,
        session_id=session_id,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )
    return AuditPageDTO.from_page(page)
