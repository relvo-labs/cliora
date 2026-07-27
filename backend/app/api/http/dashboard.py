"""Dashboard aggregates endpoint (P4-06, PRD §10.2).

Guarded by `node.view`, which all three roles hold: the Dashboard is the landing
page, and every role has a legitimate view of fleet health. What differs is the
detail, not the access — `services/dashboard.project_for` strips actor identity
from recent activity for viewers without `audit.view`, because knowing *that* a
node was removed is operations while knowing *who* removed it is the audit trail.

The route is thin on purpose: freshness, per-block isolation and the cache all
live in the service, so a second caller cannot get a version of them with the
guarantees relaxed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.http.deps import require_action
from app.api.http.schemas import DashboardSummaryDTO
from app.clock import monotonic_seconds
from app.db.engine import get_session
from app.db.models import User
from app.services.authz import may_view_audit
from app.services.dashboard import DashboardService, cached_summary, project_for
from app.services.rbac import NODE_VIEW
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryDTO)
async def dashboard_summary(
    user: User = Depends(require_action(NODE_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DashboardSummaryDTO:
    summary = await cached_summary(
        DashboardService(session, settings=settings),
        ttl_seconds=settings.dashboard_cache_ttl_seconds,
        clock=monotonic_seconds,
    )
    return DashboardSummaryDTO.from_summary(
        project_for(summary, can_view_audit=may_view_audit(user))
    )
