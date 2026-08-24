"""`/api/me/*` — everything about **the caller**, and nothing about anybody else (PX-47).

This is a new namespace in this deployment: there was no `/api/me/` before V2-P1. So the
rule that governs it is written down here before there are enough routes for the rule to
be inferred from them:

> **A route under `/api/me/` answers only about the authenticated caller, and never
> accepts a `user_id` parameter.**

That sentence exists because of what happens without it. The first request for "let a
lead see somebody else's My Work" arrives, and the cheapest change is `?user_id=`. At
that point every route here silently becomes a route about arbitrary users, the
authorization for which was written for a namespace where the subject was implicit.
Looking at another person's queue is a **different** capability with a different
permission, and it belongs on `/api/users/{id}/…` where the subject is visible in the
path and the guard has something to check.

What else will live here: notification state and personal preferences. Both are
per-caller and neither takes a subject.

**The read model is shared, not re-implemented** (D93). `/api/me/work-items` and
`/api/projects/{id}/work-items` use the same filter compiler and the same
`derive_attention`; only the `ProjectScope` differs. There is a test asserting that the
two return the same `primary_attention` for the same card.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action, require_projects_enabled
from app.api.http.work import (
    WorkCountsDTO,
    WorkItemsDTO,
    _decode_cursors,
    _decode_filter,
    _page_dto,
)
from app.db.engine import get_session
from app.db.models import User
from app.services.rbac import PROJECT_VIEW
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.work import items as work_items_service
from app.services.work.filters import (
    MAX_SEARCH_LENGTH,
    FilterNode,
    compile_filter,
    compile_order,
)
from app.services.work.scope import visible_project_ids

router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(require_projects_enabled)])


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


def _no_subject(parameters: dict[str, Any]) -> None:
    """Refuse any attempt to name a subject on this namespace.

    A guard rather than a convention. The parameter is not declared on the routes below,
    so FastAPI already ignores it — which is the problem: ignoring it silently would let
    a caller believe they had asked for somebody else's queue and received it.
    """
    named = sorted(key for key in parameters if key in {"user_id", "username", "actor_id"})
    if named:
        raise ApiError(
            "INVALID_QUERY",
            "`/api/me` answers only about the authenticated caller",
            status.HTTP_400_BAD_REQUEST,
            details={"rejected_parameters": named},
        )


@router.get("/work-items", response_model=WorkItemsDTO, response_model_exclude_unset=True)
async def read_my_work_items(
    filter: str | None = None,  # noqa: A002 - the query parameter's name is part of the API
    q: str | None = Query(default=None, max_length=MAX_SEARCH_LENGTH),
    group: str | None = None,
    order: str | None = None,
    cursors: str | None = None,
    limit: int = Query(
        default=work_items_service.DEFAULT_LIMIT, ge=1, le=work_items_service.MAX_LIMIT
    ),
    user_id: str | None = None,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> WorkItemsDTO:
    """Cards across **every project this caller can see**, in one request.

    Not one request per project merged in the browser (upstream §4.1): N projects would
    be N requests, paging could not order correctly across them, and the permission
    boundary would become the browser's responsibility — which is the one place it must
    never be.

    `user_id` is declared **only so that it can be refused**. Undeclared it would be
    silently dropped, and a caller who passed it would believe they had been answered.
    """
    _no_subject({"user_id": user_id} if user_id is not None else {})
    scope = await visible_project_ids(session, user)
    if group is not None and group not in work_items_service.GROUPS:
        raise ApiError(
            "FILTER_FIELD_NOT_ALLOWED",
            f"`{group}` is not a grouping",
            status.HTTP_400_BAD_REQUEST,
            details={"field": group, "allowed_fields": list(work_items_service.GROUPS)},
        )
    compiled = compile_filter(
        FilterNode.model_validate(_decode_filter(filter) or {}), actor_id=user.id, search=q
    )
    page = await work_items_service.work_items(
        session,
        scope=scope,
        compiled=compiled,
        project_id=None,
        group=group,
        order=compile_order(order),
        limit=limit,
        cursors=_decode_cursors(cursors),
        is_online=registry.is_connected,
    )
    return _page_dto(page, None)


@router.get("/attention-counts", response_model=WorkCountsDTO)
async def read_my_attention_counts(
    filter: str | None = None,  # noqa: A002
    q: str | None = Query(default=None, max_length=MAX_SEARCH_LENGTH),
    user_id: str | None = None,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> WorkCountsDTO:
    """The same counts as a project's, over every visible project.

    Shares the polling cadence with the board's counts (D95), so it shares the budget:
    one request every twenty seconds per open tab.
    """
    _no_subject({"user_id": user_id} if user_id is not None else {})
    scope = await visible_project_ids(session, user)
    compiled = compile_filter(
        FilterNode.model_validate(_decode_filter(filter) or {}), actor_id=user.id, search=q
    )
    counts = await work_items_service.work_counts(
        session,
        scope=scope,
        compiled=compiled,
        project_id=None,
        is_online=registry.is_connected,
    )
    return WorkCountsDTO(
        by_lifecycle=counts.by_lifecycle,
        by_attention=counts.by_attention,
        total=counts.total,
        runtime_signals_available=counts.runtime_signals_available,
    )
