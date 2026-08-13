"""Project CRUD, workspace bindings and the activity timeline (PJ-04, ADR 0027).

The router is mounted **unconditionally** and every route carries
`require_projects_enabled`, which answers 404 while the flag is off. Mounting
conditionally would make `test_every_mounted_route_is_in_the_matrix` — which reads
the import-time `app.routes` — pass or fail according to the environment the suite
ran in (ADR 0027 sec 3).

Routes stay thin: authorization at the boundary, rules in `services/projects.py`,
queries in `repositories/projects.py`. The one thing decided here rather than in the
service is who may see an actor's name, because that depends on the *caller*, not on
the resource.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action, require_projects_enabled
from app.api.http.schemas import (
    ActivityEventDTO,
    ActivityPageDTO,
    BindWorkspaceRequest,
    CreateProjectRequest,
    ProjectDetailDTO,
    ProjectSummaryDTO,
    ProjectWorkspaceDTO,
    UpdateProjectRequest,
)
from app.db.engine import get_session
from app.db.models import User
from app.repositories.projects import ProjectSummary
from app.services.activity import redact_actors
from app.services.authz import may_view_activity_actors
from app.services.projects import DEFAULT_ACTIVITY_PAGE, MAX_ACTIVITY_PAGE, ProjectService
from app.services.rbac import PROJECT_MANAGE, PROJECT_VIEW
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_projects_enabled)],
)


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


def _service(session: AsyncSession, settings: Settings) -> ProjectService:
    return ProjectService(session, settings=settings)


def _summary_dto(summary: ProjectSummary) -> ProjectSummaryDTO:
    project = summary.project
    return ProjectSummaryDTO(
        id=project.id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        status=project.status,
        owner_user_id=project.owner_user_id,
        owner_name=summary.owner_name,
        workspace_count=summary.binding_count,
        node_count=summary.node_count,
        active_session_count=summary.active_session_count,
        last_activity_at=summary.last_activity_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _encode_cursor(occurred_at: datetime, event_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{occurred_at.isoformat()}|{event_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        occurred_raw, id_raw = raw.split("|", 1)
        return datetime.fromisoformat(occurred_raw), uuid.UUID(id_raw)
    except (ValueError, binascii.Error) as exc:
        # A malformed cursor is the caller's, not a server fault: answering 422 keeps
        # a hand-edited query string from looking like an outage.
        raise ApiError(
            "INVALID_QUERY",
            "The pagination cursor is not valid",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc


@router.get("", response_model=list[ProjectSummaryDTO])
async def list_projects(
    status_filter: str | None = Query(default=None, alias="status"),
    owned_by_me: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ProjectSummaryDTO]:
    """Every holder of `project.view` sees every project.

    The same rule `node.view` already follows. With no `project_members` table, two
    teams sharing one Cliora see each other's project names — a real disclosure,
    accepted deliberately and recorded in ADR 0027's Consequences rather than left
    for someone to discover.
    """
    summaries = await _service(session, settings).list_projects(
        status_filter=status_filter,
        owner_user_id=user.id if owned_by_me else None,
        limit=limit,
        offset=offset,
    )
    return [_summary_dto(summary) for summary in summaries]


@router.post("", response_model=ProjectDetailDTO, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectDetailDTO:
    service = _service(session, settings)
    project = await service.create(
        user, name=body.name, slug=body.slug, description=body.description
    )
    summary = await service.summary(project)
    await session.commit()
    return ProjectDetailDTO(**_summary_dto(summary).model_dump(), workspaces=[])


@router.get("/{project_id}", response_model=ProjectDetailDTO)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> ProjectDetailDTO:
    service = _service(session, settings)
    project = await service.require(project_id)
    summary = await service.summary(project)
    bindings = await service.bindings(
        project.id, seconds_since_heartbeat=registry.seconds_since_heartbeat
    )
    return ProjectDetailDTO(
        **_summary_dto(summary).model_dump(),
        workspaces=[
            ProjectWorkspaceDTO(
                id=row.binding.id,
                node_id=row.binding.node_id,
                node_name=row.node_name,
                node_enabled=row.node_enabled,
                path=row.binding.path,
                label=row.binding.label,
                is_primary=row.binding.is_primary,
                usability=usability,
                created_at=row.binding.created_at,
            )
            for row, usability in bindings
        ],
    )


@router.patch("/{project_id}", response_model=ProjectSummaryDTO)
async def update_project(
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectSummaryDTO:
    service = _service(session, settings)
    project = await service.require(project_id)
    await service.update(
        user,
        project,
        name=body.name,
        description=body.description,
        new_status=body.status,
    )
    summary = await service.summary(project)
    await session.commit()
    return _summary_dto(summary)


@router.get("/{project_id}/activity", response_model=ActivityPageDTO)
async def project_activity(
    project_id: uuid.UUID,
    limit: int = Query(default=DEFAULT_ACTIVITY_PAGE, ge=1, le=MAX_ACTIVITY_PAGE),
    before: str | None = Query(default=None),
    task_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ActivityPageDTO:
    """One page of the timeline, newest first.

    **Actor identity is stripped for callers without `audit.view`.** The redaction
    happens here rather than in the query so one caller's permissions can never leak
    into another's response, which is the same reason `dashboard.project_for` narrows
    a cached summary after the fact instead of caching per role.
    """
    service = _service(session, settings)
    await service.require(project_id)
    items = await service.activity(
        project_id,
        limit=limit,
        before=_decode_cursor(before) if before else None,
        task_id=task_id,
    )

    can_view_audit = may_view_activity_actors(user)
    visible = redact_actors(items, can_view_audit=can_view_audit)
    next_before = (
        _encode_cursor(items[-1].occurred_at, items[-1].id) if len(items) == limit else None
    )
    return ActivityPageDTO(
        items=[
            ActivityEventDTO(
                id=item.id,
                kind=item.kind,
                occurred_at=item.occurred_at,
                payload=item.payload,
                actor_id=item.actor_id,
                actor_name=item.actor_name,
                session_id=item.session_id,
                actor_kind=item.actor_kind,
            )
            for item in visible
        ],
        actors_hidden=not can_view_audit,
        next_before=next_before,
    )


@router.post("/{project_id}/workspaces", response_model=ProjectWorkspaceDTO)
async def bind_workspace(
    project_id: uuid.UUID,
    body: BindWorkspaceRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> ProjectWorkspaceDTO:
    """Bind a path, or return the binding that already exists.

    200 in both cases rather than 201/409: binding the same path twice is the same
    intent expressed twice, and a conflict would make the UI's optimistic toggle need
    a special case for "already there" (the judgement `POST /workspaces/favorites`
    already made).
    """
    service = _service(session, settings)
    project = await service.require(project_id)
    binding, _created = await service.bind_workspace(
        user,
        project,
        node_id=body.node_id,
        path=body.path,
        label=body.label,
        is_primary=body.is_primary,
    )
    await session.commit()

    # Re-read through the listing so the response reports the *same* verdict the next
    # GET will. `services/favorites.py` records what happens otherwise: the create
    # path hard-coded `usable` and disagreed with the listing for the same row.
    rows = await service.bindings(
        project.id, seconds_since_heartbeat=registry.seconds_since_heartbeat
    )
    row, usability = next(pair for pair in rows if pair[0].binding.id == binding.id)
    return ProjectWorkspaceDTO(
        id=row.binding.id,
        node_id=row.binding.node_id,
        node_name=row.node_name,
        node_enabled=row.node_enabled,
        path=row.binding.path,
        label=row.binding.label,
        is_primary=row.binding.is_primary,
        usability=usability,
        created_at=row.binding.created_at,
    )


@router.delete("/{project_id}/workspaces/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unbind_workspace(
    project_id: uuid.UUID,
    binding_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Remove a binding. Running sessions are untouched (exit condition 3)."""
    service = _service(session, settings)
    project = await service.require(project_id)
    await service.unbind_workspace(user, project, binding_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
