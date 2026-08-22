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
    KnowledgeDecisionsDTO,
    KnowledgeHealthDTO,
    KnowledgeHitDTO,
    KnowledgeSearchDTO,
    KnowledgeSourceRowDTO,
    ProjectDetailDTO,
    ProjectSummaryDTO,
    ProjectWorkspaceDTO,
    ResyncResponse,
    SetAuthorityRequest,
    SetKnowledgeEnabledRequest,
    SetPinRequest,
    SourceFamilyDTO,
    UpdateProjectRequest,
)
from app.db.engine import get_session
from app.db.models import KnowledgeSource, User
from app.logging import get_logger
from app.repositories.projects import ProjectSummary
from app.services.activity import redact_actors
from app.services.authz import may_view_activity_actors
from app.services.files import keyword_digest
from app.services.knowledge.admin import KnowledgeAdmin
from app.services.knowledge.search import KnowledgeSearch, SearchHit
from app.services.projects import DEFAULT_ACTIVITY_PAGE, MAX_ACTIVITY_PAGE, ProjectService
from app.services.rbac import PROJECT_MANAGE, PROJECT_VIEW
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

log = get_logger("cliora.projects")

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


# --- V2-K1 project memory (ADR 0038) ---------------------------------------
#
# **`project.view` reads, `project.manage` writes, and no new RBAC action.** Adding one
# means touching `rbac.py`, the seed migration and three role tables for a capability
# whose boundary the existing two already describe exactly (`research/03` D53).


@router.get("/{project_id}/knowledge/search", response_model=KnowledgeSearchDTO)
async def search_knowledge(
    project_id: uuid.UUID,
    q: str = Query(min_length=1, max_length=256),
    source_type: str | None = Query(default=None),
    authority: str | None = Query(default=None),
    task_id: uuid.UUID | None = Query(default=None),
    include_history: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> KnowledgeSearchDTO:
    """Search one project's memory.

    **The query string is not recorded anywhere**: not in the audit log, not in a metric
    label — metrics are the one sink with no redaction — and not in a table. What
    somebody is searching for says what they are thinking about, and it has no audit
    value. The application log keeps only a digest, reusing the function
    `filesystem.search` already uses for the same reason.

    A project with memory switched off answers **404**, not 403: the status must not
    disclose that the project exists and has the feature turned off.
    """
    project = await _service(session, settings).require(project_id)
    result = await KnowledgeSearch(session, project.id).search(
        q,
        limit=limit,
        source_types=_csv(source_type),
        authorities=_csv(authority),
        task_id=task_id,
        include_history=include_history,
    )
    log.info(
        "knowledge_search",
        extra={
            "event": "knowledge_search",
            "keyword_digest": keyword_digest(q),
            "results": result.total,
            "degraded": result.degraded,
        },
    )
    return KnowledgeSearchDTO(
        items=[_hit_dto(hit) for hit in result.items],
        total=result.total,
        channels=list(result.channels),
        degraded=result.degraded,
    )


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _hit_dto(hit: SearchHit) -> KnowledgeHitDTO:
    return KnowledgeHitDTO(
        source_id=hit.source_id,
        source_type=hit.source_type,
        title=hit.title,
        authority=hit.authority,
        version=hit.version,
        occurred_at=hit.occurred_at,
        uri=hit.uri,
        excerpt=hit.excerpt,
        score=round(hit.score, 4),
        historical=hit.historical,
        why=list(hit.why),
    )


def _source_row(row: KnowledgeSource) -> KnowledgeSourceRowDTO:
    return KnowledgeSourceRowDTO(
        source_id=row.id,
        source_type=row.source_type,
        external_id=row.source_external_id,
        title=row.title or row.source_external_id,
        authority=row.authority,
        version=row.source_version,
        occurred_at=row.occurred_at,
        ingested_at=row.ingested_at,
        uri=row.source_uri,
        chunk_count=row.chunk_count,
        active=row.active,
    )


@router.get("/{project_id}/knowledge/sources", response_model=list[KnowledgeSourceRowDTO])
async def list_knowledge_sources(
    project_id: uuid.UUID,
    source_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[KnowledgeSourceRowDTO]:
    project = await _service(session, settings).require(project_id)
    rows = await KnowledgeAdmin(session).sources(project.id, source_type=source_type, limit=limit)
    return [_source_row(row) for row in rows]


@router.get(
    "/{project_id}/knowledge/sources/{source_id}/versions",
    response_model=list[KnowledgeSourceRowDTO],
)
async def list_source_versions(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[KnowledgeSourceRowDTO]:
    """Every version of the thing this source is a version of, newest first."""
    project = await _service(session, settings).require(project_id)
    rows = await KnowledgeAdmin(session).versions(project.id, source_id)
    return [_source_row(row) for row in rows]


@router.get("/{project_id}/knowledge/health", response_model=KnowledgeHealthDTO)
async def knowledge_health(
    project_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> KnowledgeHealthDTO:
    project = await _service(session, settings).require(project_id)
    admin = KnowledgeAdmin(session)
    health = await admin.health(project.id)
    return KnowledgeHealthDTO(
        families=[
            SourceFamilyDTO(
                source_type=family.source_type,
                sources=family.sources,
                chunks=family.chunks,
                last_ingested_at=family.last_ingested_at,
            )
            for family in health.families
        ],
        pending_jobs=health.pending_jobs,
        failed_jobs=health.failed_jobs,
        dead_jobs=health.dead_jobs,
        dead_letter_age_seconds=health.dead_letter_age_seconds,
        last_error=health.last_error,
        repo_last_synced_at=health.repo_last_synced_at,
        repo_commit=health.repo_commit,
        repo_never_synced=await admin.stale_repo(project.id),
    )


@router.get("/{project_id}/knowledge/recent", response_model=list[KnowledgeSourceRowDTO])
async def recently_learned(
    project_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[KnowledgeSourceRowDTO]:
    """What arrived lately.

    Not decoration: this is where a person checks that the decision they just accepted
    is findable, which is the ingest-freshness budget as a thing you can look at.
    """
    project = await _service(session, settings).require(project_id)
    rows = await KnowledgeAdmin(session).recent(project.id, limit=limit)
    return [_source_row(row) for row in rows]


@router.get("/{project_id}/knowledge/decisions", response_model=KnowledgeDecisionsDTO)
async def knowledge_decisions(
    project_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDecisionsDTO:
    project = await _service(session, settings).require(project_id)
    columns = await KnowledgeAdmin(session).decisions(project.id)
    return KnowledgeDecisionsDTO(
        accepted=[_source_row(row) for row in columns["accepted"]],
        superseded=[_source_row(row) for row in columns["superseded"]],
        conflicting=[_source_row(row) for row in columns["conflicting"]],
    )


@router.post("/{project_id}/knowledge/enabled", response_model=ProjectSummaryDTO)
async def set_knowledge_enabled(
    project_id: uuid.UUID,
    payload: SetKnowledgeEnabledRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectSummaryDTO:
    """The per-project switch (ADR 0038 §7). Audited, and off deletes nothing."""
    service = _service(session, settings)
    project = await service.require(project_id)
    await KnowledgeAdmin(session).set_enabled(user, project.id, payload.enabled)
    await session.commit()
    return _summary_dto(await service.summary(project))


@router.post(
    "/{project_id}/knowledge/sources/{source_id}/authority",
    response_model=KnowledgeSourceRowDTO,
)
async def set_source_authority(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    payload: SetAuthorityRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> KnowledgeSourceRowDTO:
    """Mark a source as a formal decision, or withdraw it.

    A person may assert what *they* decided; they may not assert what the platform
    observed. `canonical` and `verified` are not in the allowlist for that reason.
    """
    project = await _service(session, settings).require(project_id)
    row = await KnowledgeAdmin(session).set_authority(
        user, project.id, source_id, payload.authority
    )
    await session.commit()
    return _source_row(row)


@router.post("/{project_id}/knowledge/pins", status_code=status.HTTP_204_NO_CONTENT)
async def set_knowledge_pin(
    project_id: uuid.UUID,
    payload: SetPinRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await _service(session, settings).require(project_id)
    await KnowledgeAdmin(session).set_pin(
        user, project.id, payload.task_id, payload.source_id, payload.mode
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{project_id}/knowledge/pins/{task_id}/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_knowledge_pin(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    source_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    project = await _service(session, settings).require(project_id)
    await KnowledgeAdmin(session).clear_pin(user, project.id, task_id, source_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/knowledge/resync", response_model=ResyncResponse)
async def resync_knowledge(
    project_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ResyncResponse:
    """Re-read everything now.

    The same code path as the scheduled reconciler, because a job is a hint rather than
    content — so this is not a second implementation of ingestion that could disagree
    with the first.
    """
    project = await _service(session, settings).require(project_id)
    queued = await KnowledgeAdmin(session).resync(user, project.id)
    await session.commit()
    return ResyncResponse(queued=queued)
