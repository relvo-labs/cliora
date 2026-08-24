"""The read model's HTTP surface: work items, counts, and saved views (PX-25, PX-26).

Also still the home of the **wave-0 side-car**, `GET /projects/{id}/board-attention`,
which is temporary and whose removal is `PX-25`'s job — it stays until the existing board
is replaced, because deleting it earlier would take the attention badges off the only
board there is.

Two rules govern everything here, and both are about the same failure:

1. **Every `Task` query takes its project predicate from a `ProjectScope`**, including the
   single-project endpoints where the id is already in the path. That id says which
   project the caller wants; the scope says which they may have.
   `GATE-PX-ONE-PROJECT-SCOPE` scans for a second path.
2. **Counts and items receive the same two objects** — one `ProjectScope`, one
   `CompiledFilter`. Not the same logic; the same instances, because the signatures
   require them.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import may_perform, require_action, require_projects_enabled
from app.db.engine import get_session
from app.db.models import Task, User, WorkView
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.services.projects import ProjectService
from app.services.rbac import PROJECT_MANAGE, PROJECT_VIEW, TASK_UPDATE
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.tasks import TaskService
from app.services.work import filters as filters_module
from app.services.work import items as work_items_service
from app.services.work.attention import derive_attention
from app.services.work.filters import FilterNode, compile_filter, compile_order
from app.services.work.items import DerivedItem, ItemPage
from app.services.work.rows import WorkRowReader
from app.services.work.scope import scope_for_project
from app.services.work.views_service import WorkViewService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["work"], dependencies=[Depends(require_projects_enabled)])


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


# --- DTOs ---------------------------------------------------------------------------


class WorkItemCardDTO(BaseModel):
    """One card as six screens render it (`FR-WORK-001`, ADR 0040).

    **Not `BoardCardDTO`.** That type is pinned to the byte and shares a query with the
    V1 board; widening it is how the pin gets undone. This one has its own budget,
    measured rather than quoted (D94), and its own query.

    `attention_signals` is deliberately **not** here (D107): the card carries the primary
    level and a count, and the full set belongs to the drawer. At two hundred cards the
    full list is most of the payload and it drives no decision a person makes from the
    board.
    """

    # **Identity is required; everything else is optional with no default value set.**
    # Not because a card might lack a lifecycle, but because a view's `visible_fields`
    # shapes the response by *omitting* keys, and the route serialises with
    # `response_model_exclude_unset=True`. Declaring the rest required would force the
    # shaping to send nulls instead — and `"owner_name": null` then means both "this card
    # has no owner" and "this view does not show owners", which are different facts.
    id: uuid.UUID
    card_ref: str
    # **Not in the plan's field list**, and My Work cannot work without it: a
    # cross-project page has to know which project a card is in to link to it. The
    # upstream list was written for the single-project endpoint, where the answer is in
    # the path. Part of identity, so `visible_fields` cannot drop it.
    project_id: uuid.UUID
    version: int
    updated_at: datetime

    title: str | None = None
    card_kind: str | None = None
    lifecycle: str | None = None
    # What this card looks like on the old board, so the projection stays reversible
    # while the three legacy writers of `stage='blocked'` still exist (ADR 0040 §1).
    legacy_stage: str | None = None
    readiness: str | None = None
    # **`readiness_missing` is deliberately not here, and the reason is a measurement.**
    #
    # The Ready-transition dialog needs which items are missing, not how many, and the
    # field is already on `WorkRow` — so adding it looked free. It costs **+34,440 bytes
    # at 200 cards, taking the card from 169,518 to 203,958 (+20 %)**, which made it the
    # single most expensive field in the payload, ahead of `project_id`. Paid on every
    # card of every response, including My Work's cross-project page, for something one
    # dialog needs about one card.
    #
    # So the dialog reads `/api/tasks/{id}` instead: one request, when somebody opens it,
    # for the card they pointed at. `plan/26/03` §4's cut list starts with fields nobody
    # reads for exactly this reason, and `test_work_items_size` is what turned "looked
    # free" into a number.
    is_blocked: bool | None = None
    blocking_reason: str | None = None
    blocking_refs: list[str] | None = None
    blocking_count: int | None = None
    primary_attention: str | None = None
    attention_count: int | None = None
    execution_status: str | None = None
    active_run_id: uuid.UUID | None = None
    active_run_runner_name: str | None = None
    active_run_started_at: datetime | None = None
    pending_human_action: str | None = None
    verification_state: str | None = None
    owner_user_id: uuid.UUID | None = None
    owner_name: str | None = None
    risk: str | None = None
    priority: str | None = None
    delivery: str | None = None
    requirement_id: uuid.UUID | None = None
    epic_id: uuid.UUID | None = None
    user_story_id: uuid.UUID | None = None
    labels: list[str] | None = None
    conversation_last_seq: int | None = None
    open_question_count: int | None = None
    waiting_for_actor: str | None = None
    rank: str | None = None


class WorkGroupDTO(BaseModel):
    key: str
    # **The server's count, not `len(items)`.** A column header that counts what the
    # browser happens to have loaded is the commonest lie on a board like this.
    count: int
    items: list[WorkItemCardDTO]
    next_cursor: str | None


class WorkItemsDTO(BaseModel):
    groups: list[WorkGroupDTO]
    # False when phase B did not run. The console then shows the two runtime-dependent
    # quick filters as disabled with a reason rather than returning zero rows, because
    # zero rows reads as "fixed" (ADR 0040 §2).
    runtime_signals_available: bool


class WorkCountsDTO(BaseModel):
    by_lifecycle: dict[str, int]
    by_attention: dict[str, int]
    total: int
    runtime_signals_available: bool


class WorkViewDTO(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    name: str
    layout: str
    scope: str
    filter: dict[str, Any]
    group_by: str | None
    subgroup_by: str | None
    order_by: list[dict[str, Any]]
    visible_fields: list[str]
    density: str
    show_subtasks: bool
    is_default: bool
    position: int
    version: int


class WorkViewWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    layout: str = "board"
    scope: str = "personal"
    filter: dict[str, Any] = Field(default_factory=dict)
    group_by: str | None = None
    subgroup_by: str | None = None
    order_by: list[dict[str, Any]] = Field(default_factory=list)
    visible_fields: list[str] = Field(default_factory=list)
    density: str = "comfortable"
    show_subtasks: bool = True


class WorkViewPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    layout: str | None = None
    filter: dict[str, Any] | None = None
    group_by: str | None = None
    subgroup_by: str | None = None
    order_by: list[dict[str, Any]] | None = None
    visible_fields: list[str] | None = None
    density: str | None = None
    show_subtasks: bool | None = None
    is_default: bool | None = None


class WorkViewDuplicateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


# --- shaping ------------------------------------------------------------------------


def _card(item: DerivedItem, visible: frozenset[str] | None) -> WorkItemCardDTO:
    """Shape one derived row.

    `visible` drops fields from the response and **changes nothing about
    authorization** — asserted by a test, because a field list is the most natural place
    for somebody to eventually put a permission (ADR 0042 §2).
    """
    row = item.row
    run = row.active_run
    payload: dict[str, Any] = {
        "id": row.task_id,
        "card_ref": row.card_ref,
        "project_id": row.project_id,
        "title": row.title,
        "card_kind": row.card_kind,
        "lifecycle": row.lifecycle,
        "legacy_stage": row.stage,
        "readiness": row.readiness,
        "is_blocked": row.is_blocked,
        "blocking_reason": row.blocking_reason,
        "blocking_refs": list(row.blocking_refs),
        "blocking_count": row.blocking_count,
        "primary_attention": item.attention.primary,
        "attention_count": item.attention.count,
        "execution_status": row.execution,
        "active_run_id": run.run_id if run else None,
        "active_run_runner_name": run.runner_name if run else None,
        "active_run_started_at": run.started_at if run else None,
        "pending_human_action": row.human_decision,
        "verification_state": row.latest_verification_result,
        "owner_user_id": row.owner_user_id,
        "owner_name": row.owner_name,
        "risk": row.risk,
        "priority": row.priority,
        "delivery": row.delivery,
        "requirement_id": row.requirement_id,
        "epic_id": row.epic_id,
        "user_story_id": row.user_story_id,
        "labels": list(row.labels),
        "conversation_last_seq": row.conversation_seq,
        "open_question_count": row.open_question_count,
        "waiting_for_actor": row.waiting_for_actor,
        "rank": row.rank,
        "version": row.version,
        "updated_at": row.updated_at,
    }
    if visible:
        # Identity always survives: a card the client cannot address is not a shorter
        # response, it is a broken one.
        keep = visible | {"id", "card_ref", "project_id", "version", "updated_at"}
        payload = {key: value for key, value in payload.items() if key in keep}
    return WorkItemCardDTO(**payload)


def _page_dto(page: ItemPage, visible: frozenset[str] | None) -> WorkItemsDTO:
    return WorkItemsDTO(
        groups=[
            WorkGroupDTO(
                key=group.key,
                count=group.count,
                items=[_card(item, visible) for item in group.items],
                next_cursor=group.next_cursor,
            )
            for group in page.groups
        ],
        runtime_signals_available=page.runtime_signals_available,
    )


def _view_dto(view: WorkView) -> WorkViewDTO:
    return WorkViewDTO(
        id=view.id,
        project_id=view.project_id,
        owner_user_id=view.owner_user_id,
        name=view.name,
        layout=view.layout,
        scope=view.scope,
        filter=dict(view.filter_json or {}),
        group_by=view.group_by,
        subgroup_by=view.subgroup_by,
        order_by=list(view.order_by_json or []),
        visible_fields=list(view.visible_fields_json or []),
        density=view.density,
        show_subtasks=view.show_subtasks,
        is_default=view.is_default,
        position=view.position,
        version=view.version,
    )


def _decode_filter(encoded: str | None) -> dict[str, Any] | None:
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, TypeError, binascii.Error) as bad:
        raise ApiError(
            "INVALID_QUERY",
            "filter is not valid base64url JSON",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"parameter": "filter"},
        ) from bad
    if not isinstance(decoded, dict):
        raise ApiError(
            "INVALID_QUERY",
            "filter must be an object",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"parameter": "filter"},
        )
    return decoded


def _decode_cursors(encoded: str | None) -> dict[str, str]:
    if not encoded:
        return {}
    decoded = _decode_filter(encoded) or {}
    return {str(key): str(value) for key, value in decoded.items()}


async def _resolve_view(
    session: AsyncSession, view_id: uuid.UUID | None, actor: User
) -> WorkView | None:
    if view_id is None:
        return None
    view = await WorkViewService(session).require(view_id)
    if view.scope == "personal" and view.owner_user_id != actor.id:
        raise ApiError(
            "VIEW_NOT_OWNED",
            "This personal view belongs to somebody else",
            status.HTTP_403_FORBIDDEN,
            details={"view_id": str(view.id)},
        )
    return view


def _merge(view: WorkView | None, override: dict[str, Any] | None) -> dict[str, Any] | None:
    """A quick filter **replaces** the view's filter rather than merging into it.

    Replacement, because merging two conjunctions silently produces a question nobody
    asked: "waiting for me" plus a saved "high risk only" would return the intersection
    while the toolbar shows one chip. The toolbar says *modified* and offers Save as /
    Revert instead (D103), and the URL carries the whole filter.
    """
    if override is not None:
        return override
    if view is not None:
        return dict(view.filter_json or {})
    return None


# --- work items and counts ----------------------------------------------------------


@router.get(
    "/projects/{project_id}/work-items",
    response_model=WorkItemsDTO,
    # See `WorkItemCardDTO`: a view's `visible_fields` shapes the payload by omitting
    # keys, which only works if unset fields are not serialised as nulls.
    response_model_exclude_unset=True,
)
async def read_work_items(
    project_id: uuid.UUID,
    view: uuid.UUID | None = None,
    filter: str | None = None,  # noqa: A002 - the query parameter's name is part of the API
    # Search is its own parameter, not a sixteenth filter field — `search_clause` says
    # why. `q` rather than `search` because it is what the board's URL carries and a
    # shared link is read by people.
    q: str | None = Query(default=None, max_length=filters_module.MAX_SEARCH_LENGTH),
    group: str | None = None,
    order: str | None = None,
    cursors: str | None = None,
    limit: int = Query(
        default=work_items_service.DEFAULT_LIMIT, ge=1, le=work_items_service.MAX_LIMIT
    ),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> WorkItemsDTO:
    """The read model's page. One group per `group` value, each with a server count."""
    await ProjectService(session, settings=settings).require(project_id)
    saved = await _resolve_view(session, view, user)
    if group is None and saved is not None:
        group = saved.group_by
    if order is None and saved is not None and saved.order_by_json:
        order = ",".join(
            f"{entry.get('field')}:{entry.get('direction', 'asc')}" for entry in saved.order_by_json
        )
    if group is not None and group not in work_items_service.GROUPS:
        raise ApiError(
            "FILTER_FIELD_NOT_ALLOWED",
            f"`{group}` is not a grouping",
            status.HTTP_400_BAD_REQUEST,
            details={"field": group, "allowed_fields": list(work_items_service.GROUPS)},
        )
    scope = await scope_for_project(session, user, project_id)
    compiled = compile_filter(
        FilterNode.model_validate(_merge(saved, _decode_filter(filter)) or {}),
        actor_id=user.id,
        search=q,
    )
    page = await work_items_service.work_items(
        session,
        scope=scope,
        compiled=compiled,
        project_id=project_id,
        group=group,
        order=compile_order(order),
        limit=limit,
        cursors=_decode_cursors(cursors),
        is_online=registry.is_connected,
    )
    visible = (
        frozenset(saved.visible_fields_json)
        if saved is not None and saved.visible_fields_json
        else None
    )
    return _page_dto(page, visible)


class TaskAttentionDTO(BaseModel):
    """One card's attention, in full.

    **The signal set lives here and not on the board's card** (D107, and
    `test_the_work_item_card_carries_the_primary_attention_and_not_the_set` says so in as
    many words: *the full signal list is the drawer's, not the card's*). At two hundred
    cards the list is most of the payload and it drives no decision anybody makes from the
    board — they open the card for that. This is the endpoint they open it with.

    It exists because the Drawer needs the **set**, not the primary. Its execution block
    expands itself when one of four situations is the reason the card is stuck, and a card
    can be several things at once: one that has no eligible runner *and* is awaiting a human
    decision shows `pending_human_approval` on the board, because that outranks it — and the
    first version of the Drawer read `primary_attention`, so it left the execution settings
    collapsed on exactly the card whose execution settings were the answer. Found by the
    browser run of wave 5 (`plan/26/12` §2.28).
    """

    task_id: uuid.UUID
    primary: str | None
    signals: list[str]
    #: False when the node registry could not be consulted, so levels 5 and 6 are
    #: **absent rather than false** (ADR 0040 §2). A Drawer that treated absence as "no
    #: problem" would say a card is fine when nobody knows.
    runtime_signals_available: bool


@router.get("/tasks/{task_id}/attention", response_model=TaskAttentionDTO)
async def read_task_attention(
    task_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> TaskAttentionDTO:
    """`derive_attention` for one card, through the same reader the board uses.

    **Not a second derivation.** `WorkRowReader` and `derive_attention` are the same two
    functions the board calls; only the row set differs. `GATE-PX-SINGLE-ATTENTION`
    already fails the build on a second ordering, and this route is why that gate matters
    beyond the board: an endpoint that answered "why is this card stuck" from its own
    reading of the columns would be a second opinion nobody could reconcile.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
    # Through the scope, not the task's own `project_id`. *Which card do you want* and
    # *which may you have* are different questions, and only one of them is answered by
    # the path (`services/work/scope.py`).
    scope = await scope_for_project(session, user, task.project_id)
    project = await ProjectService(session, settings=settings).require(task.project_id)
    if not scope.permits(project.id):
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
    rows, runtime = await WorkRowReader(session).for_project(
        project, is_online=registry.is_connected
    )
    row = next((candidate for candidate in rows if candidate.task_id == task_id), None)
    if row is None:  # pragma: no cover - the row came from this project
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
    attention = derive_attention(row, runtime)
    return TaskAttentionDTO(
        task_id=task_id,
        primary=attention.primary,
        signals=list(attention.signals),
        runtime_signals_available=attention.runtime_available,
    )


@router.get("/projects/{project_id}/work-counts", response_model=WorkCountsDTO)
async def read_work_counts(
    project_id: uuid.UUID,
    view: uuid.UUID | None = None,
    filter: str | None = None,  # noqa: A002
    q: str | None = Query(default=None, max_length=filters_module.MAX_SEARCH_LENGTH),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> WorkCountsDTO:
    """The two breakdowns the board polls every twenty seconds (D95).

    The hottest endpoint of the phase, and it takes **the same `ProjectScope` and the same
    `CompiledFilter` construction** as `work-items` above. That is the mechanism behind
    "counts and items cannot disagree"; a shared helper each endpoint called separately
    would be two places to edit.
    """
    await ProjectService(session, settings=settings).require(project_id)
    saved = await _resolve_view(session, view, user)
    scope = await scope_for_project(session, user, project_id)
    compiled = compile_filter(
        FilterNode.model_validate(_merge(saved, _decode_filter(filter)) or {}),
        actor_id=user.id,
        search=q,
    )
    counts = await work_items_service.work_counts(
        session,
        scope=scope,
        compiled=compiled,
        project_id=project_id,
        is_online=registry.is_connected,
    )
    return WorkCountsDTO(
        by_lifecycle=counts.by_lifecycle,
        by_attention=counts.by_attention,
        total=counts.total,
        runtime_signals_available=counts.runtime_signals_available,
    )


# --- view CRUD ----------------------------------------------------------------------


@router.get("/projects/{project_id}/views", response_model=list[WorkViewDTO])
async def list_views(
    project_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[WorkViewDTO]:
    """The project's shared views plus the caller's own personal ones.

    Somebody else's personal view is **absent**, which is why writing to one is a 403
    rather than a 404: this list already does not mention it.
    """
    await ProjectService(session, settings=settings).require(project_id)
    views = await WorkViewService(session).visible_for(project_id=project_id, actor=user)
    return [_view_dto(view) for view in views]


@router.post("/projects/{project_id}/views", response_model=WorkViewDTO, status_code=201)
async def create_view(
    project_id: uuid.UUID,
    body: WorkViewWriteRequest,
    user: User = Depends(require_action(PROJECT_VIEW)),
    may_manage: bool = Depends(may_perform(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> WorkViewDTO:
    """`project.view` to save a personal view, `project.manage` for a shared one.

    Two actions rather than a new `view.manage`: twenty-seven is already a matrix people
    have to hold in their heads, and a new one would be held by exactly the roles that
    hold `project.manage` (D53).
    """
    await ProjectService(session, settings=settings).require(project_id)
    # A filter that cannot be compiled must not be storable: a saved view whose filter
    # only fails on read is a view that looks fine in the list and breaks the board.
    compile_filter(FilterNode.model_validate(body.filter), actor_id=user.id)
    view = await WorkViewService(session).create(
        project_id=project_id,
        actor=user,
        scope=body.scope,
        fields={
            "name": body.name,
            "layout": body.layout,
            "filter_json": body.filter,
            "group_by": body.group_by,
            "subgroup_by": body.subgroup_by,
            "order_by_json": body.order_by,
            "visible_fields_json": body.visible_fields,
            "density": body.density,
            "show_subtasks": body.show_subtasks,
        },
        may_manage=may_manage,
    )
    dto = _view_dto(view)
    await session.commit()
    return dto


@router.patch("/work-views/{view_id}", response_model=WorkViewDTO)
async def update_view(
    view_id: uuid.UUID,
    body: WorkViewPatchRequest,
    user: User = Depends(require_action(PROJECT_VIEW)),
    may_manage: bool = Depends(may_perform(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> WorkViewDTO:
    service = WorkViewService(session)
    view = await service.require(view_id)
    fields: dict[str, Any] = {}
    for source, target in (
        ("name", "name"),
        ("layout", "layout"),
        ("filter", "filter_json"),
        ("group_by", "group_by"),
        ("subgroup_by", "subgroup_by"),
        ("order_by", "order_by_json"),
        ("visible_fields", "visible_fields_json"),
        ("density", "density"),
        ("show_subtasks", "show_subtasks"),
    ):
        value = getattr(body, source)
        if value is not None:
            fields[target] = value
    if "filter_json" in fields:
        compile_filter(FilterNode.model_validate(fields["filter_json"]), actor_id=user.id)
    if fields:
        view = await service.update(view=view, actor=user, fields=fields, may_manage=may_manage)
    if body.is_default:
        view = await service.set_default(view=view, actor=user, may_manage=may_manage)
    dto = _view_dto(view)
    await session.commit()
    return dto


@router.delete("/work-views/{view_id}", status_code=204)
async def delete_view(
    view_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    may_manage: bool = Depends(may_perform(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    service = WorkViewService(session)
    view = await service.require(view_id)
    await service.delete(view=view, actor=user, may_manage=may_manage)
    await session.commit()


@router.post("/work-views/{view_id}/duplicate", response_model=WorkViewDTO, status_code=201)
async def duplicate_view(
    view_id: uuid.UUID,
    body: WorkViewDuplicateRequest,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> WorkViewDTO:
    """Any readable view becomes a **personal** copy.

    Always personal: copying a shared view is how somebody tries something without
    changing what the team sees.
    """
    service = WorkViewService(session)
    view = await service.require(view_id)
    if view.scope == "personal" and view.owner_user_id != user.id:
        raise ApiError(
            "VIEW_NOT_OWNED",
            "This personal view belongs to somebody else",
            status.HTTP_403_FORBIDDEN,
            details={"view_id": str(view.id)},
        )
    copy = await service.duplicate(view=view, actor=user, name=body.name)
    dto = _view_dto(copy)
    await session.commit()
    return dto


# --- bulk update ---------------------------------------------------------------------

BULK_LIMIT = 100


class BulkUpdateRequest(BaseModel):
    """Change many cards the same way.

    **There is no `version`.** Bulk means "make these hundred cards say this", and
    carrying a version per card would require the browser to read a hundred current
    versions first. So bulk has **no optimistic lock**, and that is stated here and in
    the UI rather than left as a silent last-writer-wins.
    """

    task_ids: list[uuid.UUID] = Field(min_length=1)
    patch: dict[str, Any]
    idempotency_key: str | None = Field(default=None, max_length=128)


class BulkUpdateDTO(BaseModel):
    updated: int
    card_refs: list[str]


@router.post("/tasks/bulk-update", response_model=BulkUpdateDTO)
async def bulk_update(
    body: BulkUpdateRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> BulkUpdateDTO:
    """One card at a time, through `TaskService.update()`, in one transaction (D96).

    **Not one `UPDATE`.** A statement like `UPDATE tasks SET stage='done' WHERE id = ANY(…)`
    would bypass five things at once: the Done Gate's six conditions, the dependency
    refusal, the optimistic lock, the audit and activity trails — and, the one the
    upstream plan missed entirely, the **knowledge outbox**. `ActivityService.record()` is
    `alpha.3`'s only enqueue point, so skipping activity means those hundred cards' project
    memory never updates, and the symptom is that the cards merely look quiet.

    So bulk is slow: a hundred cards is roughly four hundred row writes plus up to a
    hundred Done Gate evaluations. The mitigation is progress in the interface and an
    explicit all-or-nothing, **not** quietly relaxing to partial success.

    `audit` gets **one** row naming every card; `activity` gets **N**, because each card's
    own timeline has to show its own change (D105).
    """
    if len(body.task_ids) > BULK_LIMIT:
        raise ApiError(
            "BULK_LIMIT_EXCEEDED",
            f"a bulk update covers at most {BULK_LIMIT} cards",
            status.HTTP_400_BAD_REQUEST,
            details={"limit": BULK_LIMIT, "received": len(body.task_ids)},
        )
    service = TaskService(session, settings=settings)
    refs: list[str] = []
    seen: set[uuid.UUID] = set()
    for task_id in body.task_ids:
        if task_id in seen:
            # A repeated id is not an error and not a second write: the request means
            # "these cards", and a set is what that means.
            continue
        seen.add(task_id)
        task = await service.require_task(task_id)
        # **Authorization per card**, not "holds task.update, therefore all of them".
        # Today the action is global, so this is a project-existence check; the loop is
        # the shape that survives membership arriving.
        await ProjectService(session, settings=settings).require(task.project_id)
        updated = await service.update_task(
            task=task,
            actor_id=user.id,
            actor_kind="user",
            expected_version=task.version,
            changes=dict(body.patch),
        )
        refs.append(updated.task.card_ref)
    await AuditService(session).record(
        audit_actions.TASK_UPDATE,
        user_id=user.id,
        metadata={
            "action": "bulk_update",
            "patch": sorted(body.patch),
            "item_refs": refs,
            "idempotency_key": body.idempotency_key,
        },
    )
    await session.commit()
    return BulkUpdateDTO(updated=len(refs), card_refs=refs)
