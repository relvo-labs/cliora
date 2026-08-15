"""Agents, project repositories, dispatch, runs and card messages (AR-04, ADR 0029).

Mounted **unconditionally**, like every V2 router, with two flag guards on the router
itself — and their **order is not incidental**: `require_projects_enabled` first,
`require_agent_runs_enabled` second. Reversed, a deployment with the project layer off
would answer 403 here where it must answer 404, and a 403 confirms the route exists
(plan/18/00-…md D12).

Routes stay thin: authorization at the boundary, rules in `services/runs.py` and
`services/runners.py`. Two things are decided here rather than in a service because
they depend on the *caller* rather than on the resource — whether a runner's node is
currently connected, and which of the two credential types is posting a message.

**The message endpoint exists twice, once per credential type**, and both require the
same action (`task.update`). That is what makes "humans and agents share one channel"
true in the authorization layer and not only in the URL. It is deliberately *not* one
route with a dependency that inspects the principal's type: the first handler to forget
which one it received is an agent doing something a person was meant to do.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import (
    require_action,
    require_agent_action,
    require_agent_runs_enabled,
    require_projects_enabled,
)
from app.api.http.requirements import _proposal_dto, _spec_dto, requirement_detail
from app.api.http.schemas import (
    AddEvidenceRequest,
    AgentRunnerDTO,
    CreatePatchProposalRequest,
    CreateProposalRequest,
    CreateRepositoryRequest,
    CreateSpecRequest,
    DecidePatchProposalRequest,
    DeleteArtifactRequest,
    DispatchRequest,
    DispatchResponseDTO,
    DocumentPatchProposalDTO,
    EvidenceItemDTO,
    ExecutionPlanDTO,
    FeatureSpecDTO,
    PostMessageRequest,
    ProjectRepositoryDTO,
    RecordPlanRequest,
    RequirementDetailDTO,
    RunLogLineDTO,
    RunLogPageDTO,
    SubmitVerificationRequest,
    TaskArtifactDTO,
    TaskMessageDTO,
    TaskProposalDTO,
    TaskRunDTO,
    UpdateAgentRequest,
    VerificationReportDTO,
)
from app.clock import now_utc
from app.db.engine import get_session
from app.db.models import (
    AgentRunner,
    DocumentPatchProposal,
    EvidenceItem,
    ExecutionPlan,
    ProjectRepository,
    Requirement,
    RunLog,
    Task,
    TaskArtifact,
    TaskMessage,
    TaskRun,
    User,
    VerificationReport,
)
from app.services.activity import ACTOR_AGENT, ACTOR_USER
from app.services.agent_auth import KIND_RUN, AgentPrincipal
from app.services.artifacts import PREVIEWABLE, ArtifactService
from app.services.evidence import EvidenceService, PlanService, VerificationService
from app.services.patches import PatchProposalService
from app.services.projects import ProjectService
from app.services.rbac import (
    AGENT_MANAGE,
    AGENT_VIEW,
    PROJECT_MANAGE,
    PROJECT_VIEW,
    RUN_CANCEL,
    RUN_DISPATCH,
    TASK_APPROVE,
    TASK_UPDATE,
)
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.requirements import RequirementService
from app.services.runners import RepositoryService, RunnerService, RunnerView, clone_url
from app.services.runs import MessageService, RunService
from app.services.tasks import CARD_KIND_CLARIFICATION, CARD_KIND_DECOMPOSITION, TaskService
from app.settings import Settings, get_settings

router = APIRouter(
    prefix="/api",
    tags=["agents"],
    dependencies=[
        Depends(require_projects_enabled),
        Depends(require_agent_runs_enabled),
    ],
)


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


def _runner_dto(view: RunnerView) -> AgentRunnerDTO:
    runner = view.runner
    return AgentRunnerDTO(
        id=runner.id,
        node_id=runner.node_id,
        node_name=view.node.name,
        name=runner.name,
        runtimes=list(runner.runtimes or []),
        labels=list(runner.labels or []),
        run_untagged=runner.run_untagged,
        accept_secrets=runner.accept_secrets,
        max_concurrent=runner.max_concurrent,
        max_waiting=runner.max_waiting,
        enabled=runner.enabled,
        dedicated=runner.dedicated,
        online=view.online,
        active_runs=view.active_runs,
        waiting_runs=view.waiting_runs,
        assigned_cards=view.assigned_cards,
        blocked_reason=runner.blocked_reason,
        disk_used_bytes=runner.disk_used_bytes,
        disk_quota_bytes=runner.disk_quota_bytes,
        registered_at=runner.registered_at,
        last_registered_at=runner.last_registered_at,
    )


def _repository_dto(row: ProjectRepository) -> ProjectRepositoryDTO:
    return ProjectRepositoryDTO(
        id=row.id,
        project_id=row.project_id,
        scheme=row.scheme,
        host=row.host,
        path=row.path,
        default_branch=row.default_branch,
        label=row.label,
        url=clone_url(row),
        created_at=row.created_at,
    )


def _run_dto(
    run: TaskRun, *, runner_name: str | None, secret_names: list[str] | None = None
) -> TaskRunDTO:
    return TaskRunDTO(
        id=run.id,
        task_id=run.task_id,
        project_id=run.project_id,
        seq=run.seq,
        status=run.status,
        attempt=run.attempt,
        runner_id=run.runner_id,
        runner_name=runner_name,
        assigned_runner_id=run.assigned_runner_id,
        runtime=run.runtime,
        source_kind=run.source_kind,
        source_ref=run.source_ref,
        commit_sha=run.commit_sha,
        disk_bytes=run.disk_bytes,
        queued_at=run.queued_at,
        claimed_at=run.claimed_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        last_event_at=run.last_event_at,
        result=run.result,
        error_code=run.error_code,
        summary=run.summary,
        log_bytes=run.log_bytes,
        log_truncated_bytes=run.log_truncated_bytes,
        secret_names=sorted(secret_names or []),
    )


def _message_dto(message: TaskMessage, *, author_name: str | None) -> TaskMessageDTO:
    return TaskMessageDTO(
        id=message.id,
        task_id=message.task_id,
        run_id=message.run_id,
        author_kind=message.author_kind,
        author_user_id=message.author_user_id,
        author_name=author_name,
        author_runner_id=message.author_runner_id,
        body=message.body,
        kind=message.kind,
        event_kind=message.event_kind,
        created_at=message.created_at,
    )


async def _runner_names(session: AsyncSession, runs: list[TaskRun]) -> dict[uuid.UUID, str]:
    ids = {run.runner_id for run in runs if run.runner_id is not None}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AgentRunner.id, AgentRunner.name).where(AgentRunner.id.in_(ids))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _require_visible_task(session: AsyncSession, settings: Settings, task_id: uuid.UUID):
    """A card plus its project, or 404.

    Resolving the project is not decoration: every V2.2 read is scoped by the project's
    visibility, and a run id must never be usable to discover a card in a project the
    caller cannot see.
    """
    task = await TaskService(session).require_task(task_id)
    project = await ProjectService(session, settings=settings).require(task.project_id)
    return task, project


# --- agents ---------------------------------------------------------------


@router.get("/agents", response_model=list[AgentRunnerDTO])
async def list_agents(
    _user: User = Depends(require_action(AGENT_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> list[AgentRunnerDTO]:
    """Every runner in the fleet.

    Not filtered by project, and that is the platform's posture rather than an
    oversight: **the authorization boundary is enrollment, permanently.** A runner on
    any enrolled node can claim any project's card, pull any project's code and — from
    V2.3 — receive the secrets that card declares. Per-project authorization is not
    coming: the 2026-08-12 ruling cancelled `project_agents` rather than deferring it,
    and what bounds the radius instead is four compensating controls (ADR 0032 §0).
    The Agents page states this in words next to the list, because it is the kind of
    design that gets reported as a bug otherwise.
    """
    views = await RunnerService(session).list_views(is_online=registry.is_connected)
    return [_runner_dto(view) for view in views]


@router.get("/agents/{runner_id}", response_model=AgentRunnerDTO)
async def read_agent(
    runner_id: uuid.UUID,
    _user: User = Depends(require_action(AGENT_VIEW)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> AgentRunnerDTO:
    service = RunnerService(session)
    runner = await service.require(runner_id)
    return _runner_dto(await service.view(runner, is_online=registry.is_connected))


@router.patch("/agents/{runner_id}", response_model=AgentRunnerDTO)
async def update_agent(
    runner_id: uuid.UUID,
    body: UpdateAgentRequest,
    user: User = Depends(require_action(AGENT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> AgentRunnerDTO:
    """Enable/disable and concurrency — the disposition of compute, and nothing else.

    There is deliberately **no binding endpoint**, and there will not be one:
    `project_agents` was cancelled by the 2026-08-12 ruling rather than deferred, and
    the authorization boundary is permanently enrollment (ADR 0032 §0).

    **Tags are not editable here either**, which is a different reason from the same
    ruling: a tag is what the node's `agentd` config declares about itself, so a
    platform-side edit would be a second source of truth that `runner.register`
    silently overwrites on the next reconnect (ADR 0029 amendment B5). Changing a
    runner's tags means changing that machine's config file.
    """
    service = RunnerService(session)
    runner = await service.require(runner_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError("INVALID_ARGUMENT", "No fields to update", status.HTTP_400_BAD_REQUEST)
    await service.update(runner=runner, changes=changes, actor_id=user.id)
    await session.commit()
    await session.refresh(runner)
    return _runner_dto(await service.view(runner, is_online=registry.is_connected))


# --- project repositories -------------------------------------------------


@router.get("/projects/{project_id}/repositories", response_model=list[ProjectRepositoryDTO])
async def list_repositories(
    project_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ProjectRepositoryDTO]:
    project = await ProjectService(session, settings=settings).require(project_id)
    rows = await RepositoryService(session, settings=settings).list_for(project.id)
    return [_repository_dto(row) for row in rows]


@router.post(
    "/projects/{project_id}/repositories",
    response_model=ProjectRepositoryDTO,
    status_code=status.HTTP_201_CREATED,
)
async def create_repository(
    project_id: uuid.UUID,
    body: CreateRepositoryRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectRepositoryDTO:
    """Register where a project's code lives.

    This is the one path in the phase where a person's input becomes part of the
    daemon's git argv, so the validation in `RepositoryService` is a security
    requirement rather than an input-quality one — and the request body takes three
    fields instead of a URL so that a credential is **unrepresentable** rather than
    filtered out (ADR 0031 sec 5).
    """
    project = await ProjectService(session, settings=settings).require(project_id)
    row = await RepositoryService(session, settings=settings).create(
        project=project,
        scheme=body.scheme,
        host=body.host,
        path=body.path,
        default_branch=body.default_branch,
        label=body.label,
        actor_id=user.id,
    )
    await session.commit()
    await session.refresh(row)
    return _repository_dto(row)


@router.delete(
    "/projects/{project_id}/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_repository(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    await ProjectService(session, settings=settings).require(project_id)
    service = RepositoryService(session, settings=settings)
    repository = await service.require(project_id, repository_id)
    await service.delete(repository=repository, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- dispatch and runs ----------------------------------------------------


@router.post(
    "/tasks/{task_id}/dispatch",
    response_model=DispatchResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_task(
    task_id: uuid.UUID,
    body: DispatchRequest,
    user: User = Depends(require_action(RUN_DISPATCH)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> DispatchResponseDTO:
    """202, always — queueing is not the same as starting.

    Two failures that look alike to a caller are deliberately kept apart: a named agent
    that is *ineligible* is refused at dispatch with 409 naming the condition, while a
    named agent that is merely *offline* is queued with a `waiting_reason` the board
    turns into different words. Without that split, a person cannot tell "I
    misconfigured this" from "wait a moment" (ADR 0029 sec 3).
    """
    task, project = await _require_visible_task(session, settings, task_id)
    service = RunService(session, settings=settings)
    result = await service.dispatch(
        task=task,
        project=project,
        assigned_runner_id=body.assigned_runner_id,
        actor_id=user.id,
    )
    reason = await service.resolve_waiting_reason(result.run, is_online=registry.is_connected)
    await session.commit()
    return DispatchResponseDTO(
        run_id=result.run.id,
        status="queued",
        waiting_reason=reason.kind,
        missing_tags=list(reason.missing_tags),
        runner_name=reason.runner_name,
    )


@router.get("/tasks/{task_id}/runs", response_model=list[TaskRunDTO])
async def list_task_runs(
    task_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[TaskRunDTO]:
    await _require_visible_task(session, settings, task_id)
    runs = await RunService(session, settings=settings).for_task(task_id)
    names = await _runner_names(session, runs)
    return [_run_dto(run, runner_name=names.get(run.runner_id or uuid.uuid4())) for run in runs]


@router.get("/runs/{run_id}", response_model=TaskRunDTO)
async def read_run(
    run_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskRunDTO:
    run = await RunService(session, settings=settings).require(run_id)
    task, _project = await _require_visible_task(session, settings, run.task_id)
    names = await _runner_names(session, [run])
    return _run_dto(
        run,
        runner_name=names.get(run.runner_id or uuid.uuid4()),
        # Only the detail route carries them: the list route renders rows, and a card's
        # secret declaration is not something to repeat once per attempt.
        secret_names=list(task.required_secrets or []),
    )


@router.get("/runs/{run_id}/logs", response_model=RunLogPageDTO)
async def read_run_logs(
    run_id: uuid.UUID,
    after_seq: int = Query(default=-1, ge=-1),
    limit: int = Query(default=200, ge=1, le=1000),
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunLogPageDTO:
    """Paged, not streamed, and returned **unparsed**.

    Paged because a run's log lands at most every two seconds (Central aggregates
    before writing), so polling is enough — and the alternative would mean a second
    real-time channel next to the terminal relay, which is the single thing this phase
    should not touch.

    Unparsed because the JSONL event schema belongs to a third-party CLI and changes
    with its version; parsing it here would make that schema part of this API.
    """
    run = await RunService(session, settings=settings).require(run_id)
    await _require_visible_task(session, settings, run.task_id)
    rows = list(
        (
            await session.execute(
                select(RunLog)
                .where(RunLog.run_id == run_id, RunLog.seq > after_seq)
                .order_by(RunLog.seq)
                .limit(limit)
            )
        ).scalars()
    )
    return RunLogPageDTO(
        lines=[
            RunLogLineDTO(
                seq=row.seq, data=row.data, truncated=row.truncated, received_at=row.received_at
            )
            for row in rows
        ],
        next_after_seq=rows[-1].seq if rows else None,
        log_bytes=run.log_bytes,
        truncated_bytes=run.log_truncated_bytes,
    )


@router.post("/runs/{run_id}/cancel", response_model=TaskRunDTO)
async def cancel_run(
    run_id: uuid.UUID,
    user: User = Depends(require_action(RUN_CANCEL)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskRunDTO:
    service = RunService(session, settings=settings)
    run = await service.require(run_id)
    await _require_visible_task(session, settings, run.task_id)
    await service.cancel(run=run, actor_id=user.id)
    await session.commit()
    await session.refresh(run)
    names = await _runner_names(session, [run])
    return _run_dto(run, runner_name=names.get(run.runner_id or uuid.uuid4()))


# --- card messages --------------------------------------------------------


@router.get("/tasks/{task_id}/messages", response_model=list[TaskMessageDTO])
async def list_task_messages(
    task_id: uuid.UUID,
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[TaskMessageDTO]:
    """Readable with `project.view` — writing is not (see below)."""
    await _require_visible_task(session, settings, task_id)
    messages = await MessageService(session).list_for(task_id, since=since, limit=limit)
    return [_message_dto(message, author_name=None) for message in messages]


@router.post(
    "/tasks/{task_id}/messages",
    response_model=TaskMessageDTO,
    status_code=status.HTTP_201_CREATED,
)
async def post_task_message(
    task_id: uuid.UUID,
    body: PostMessageRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskMessageDTO:
    """`task.update`, **not** `project.view`.

    The upstream plan had this at `project.view`, which all three roles hold — and that
    would have been a Viewer write path, contradicting the read-only viewer the rest of
    the system promises. `task.update` also happens to be exactly what a run token
    already carries, so the agent's route (AR-08) requires the *same* action rather
    than a weaker one (plan/18/06-…md §1).
    """
    task, _project = await _require_visible_task(session, settings, task_id)
    message = await MessageService(session).post(
        task=task,
        body=body.body,
        kind=body.kind,
        author_kind=ACTOR_USER,
        author_user_id=user.id,
    )
    await session.commit()
    await session.refresh(message)
    return _message_dto(message, author_name=user.display_name)


# --- artifacts ------------------------------------------------------------


def _artifact_dto(row: TaskArtifact) -> TaskArtifactDTO:
    return TaskArtifactDTO(
        id=row.id,
        task_id=row.task_id,
        run_id=row.run_id,
        message_id=row.message_id,
        filename=row.filename,
        content_type=row.content_type,
        size=row.size,
        sha256=row.sha256,
        uploaded_by_kind=row.uploaded_by_kind,
        uploaded_by_user_id=row.uploaded_by_user_id,
        uploaded_by_runner_id=row.uploaded_by_runner_id,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        delete_reason=row.delete_reason,
        previewable=row.deleted_at is None and row.content_type in PREVIEWABLE,
    )


def _download_headers(filename: str) -> dict[str, str]:
    """The four headers, and none of them is optional.

    * `Content-Disposition: attachment` with **RFC 5987 percent-encoding**, not
      `filename="…"`. A filename may contain non-ASCII, and the quoted form is a header
      injection the moment one contains `"` or CRLF. Percent-encoding makes that
      unrepresentable rather than something to filter.
    * `Content-Type: application/octet-stream` **even when the database says
      `image/png`**. A download endpoint does not need the right type; it needs the
      browser not to try displaying it. The right type is served by `/preview`.
    * `nosniff`, because without it older engines sniff past the type anyway.
    * A `CSP` with `sandbox`, as a third layer: even if the first two were bypassed,
      the response has no script origin.
    """
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }


@router.get("/tasks/{task_id}/artifacts", response_model=list[TaskArtifactDTO])
async def list_task_artifacts(
    task_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[TaskArtifactDTO]:
    await _require_visible_task(session, settings, task_id)
    rows = await ArtifactService(session, settings=settings).list_for(task_id)
    return [_artifact_dto(row) for row in rows]


@router.post(
    "/tasks/{task_id}/artifacts",
    response_model=TaskArtifactDTO,
    status_code=status.HTTP_201_CREATED,
)
async def upload_task_artifact(
    task_id: uuid.UUID,
    # `Annotated`, not a call in the default: `B008` is right in general, and FastAPI's
    # own recommended form avoids it.
    file: Annotated[UploadFile, File()],
    sha256: Annotated[str, Form()] = "",
    message: Annotated[str, Form()] = "",
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskArtifactDTO:
    """`task.update`, like posting a message, and for the same reason: attaching a file
    to a card is a write, and `project.view` is held by every role."""
    task, _project = await _require_visible_task(session, settings, task_id)
    data = await file.read()
    message_id = None
    if message.strip():
        posted = await MessageService(session).post(
            task=task, body=message, author_kind=ACTOR_USER, author_user_id=user.id
        )
        message_id = posted.id
    artifact = await ArtifactService(session, settings=settings).attach(
        task=task,
        filename=file.filename or "artifact",
        data=data,
        declared_sha256=sha256,
        run_id=None,
        message_id=message_id,
        uploader_kind="user",
        user_id=user.id,
        runner_id=None,
    )
    await session.commit()
    await session.refresh(artifact)
    return _artifact_dto(artifact)


@router.get("/artifacts/{artifact_id}")
async def download_artifact(
    artifact_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Always a download. There is no query parameter, header or content type that
    turns this into a render, because a single-origin deployment has nowhere safe to
    render an uploaded file (ADR 0020, ADR 0030 Part B)."""
    service = ArtifactService(session, settings=settings)
    artifact = await service.require(artifact_id)
    await _require_visible_task(session, settings, artifact.task_id)
    data = await service.blob(artifact.id)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers=_download_headers(artifact.filename),
    )


@router.get("/artifacts/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Exists only for three kinds of content, and **404 for everything else**.

    404 rather than 403: whether a preview endpoint exists for a given file should not
    itself be a signal. `text/markdown` is served as `text/plain` — rendering it would
    execute embedded HTML, and a `.md` whose content is HTML passes every text check
    there is.
    """
    service = ArtifactService(session, settings=settings)
    artifact = await service.require(artifact_id)
    await _require_visible_task(session, settings, artifact.task_id)
    if artifact.deleted_at is not None or artifact.content_type not in PREVIEWABLE:
        raise ApiError("NOT_FOUND", "Not found", status.HTTP_404_NOT_FOUND)
    data = await service.blob(artifact.id)
    media = artifact.content_type
    if media.startswith("text/"):
        media = "text/plain; charset=utf-8"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.delete("/artifacts/{artifact_id}", response_model=TaskArtifactDTO)
async def delete_artifact(
    artifact_id: uuid.UUID,
    body: DeleteArtifactRequest,
    user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskArtifactDTO:
    """`project.manage`, a written reason, and an audit row.

    There is deliberately **no update route anywhere**: an attached artifact is
    immutable, and an OpenAPI assertion holds `/api/artifacts/{id}` to `GET` and
    `DELETE`.
    """
    service = ArtifactService(session, settings=settings)
    artifact = await service.require(artifact_id)
    await _require_visible_task(session, settings, artifact.task_id)
    await service.delete(artifact=artifact, reason=body.reason, actor_id=user.id)
    await session.commit()
    await session.refresh(artifact)
    return _artifact_dto(artifact)


# --- the run credential's surface ------------------------------------------
#
# A separate router on `/api/cli/runs`, not the same paths with a second dependency.
# A route that accepted either principal would need every handler under it to ask
# which one it got, and the first handler to forget is an agent doing something a
# person was meant to do. A distinct prefix makes the reachable set enumerable.
#
# Every one of these additionally checks `principal.task_id`: a run credential may only
# touch **its own card**, and a mismatch answers 404 rather than 403 so a token cannot
# be used to discover which cards exist elsewhere.

run_router = APIRouter(
    prefix="/api/cli/runs",
    tags=["agent"],
    dependencies=[
        Depends(require_projects_enabled),
        Depends(require_agent_runs_enabled),
    ],
)


def _own_task(principal: AgentPrincipal, task: Task) -> None:
    if principal.kind != KIND_RUN or principal.task_id != task.id:
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)


async def _run_task(session: AsyncSession, principal: AgentPrincipal) -> Task:
    if principal.task_id is None:
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
    task = await TaskService(session).require_task(principal.task_id)
    _own_task(principal, task)
    return task


@run_router.get("/messages", response_model=list[TaskMessageDTO])
async def agent_list_messages(
    since: datetime | None = Query(default=None),
    principal: AgentPrincipal = Depends(require_agent_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> list[TaskMessageDTO]:
    """`cliora task messages`. **Pull, never push.**

    There is no interrupt path to a running agent: the platform does not reach into a
    process to tell it something arrived. An agent that asked a question polls for the
    answer, which is also why `waiting_for_input` has its own 24-hour timer.
    """
    task = await _run_task(session, principal)
    messages = await MessageService(session).list_for(task.id, since=since)
    return [_message_dto(message, author_name=None) for message in messages]


@run_router.post("/messages", response_model=TaskMessageDTO, status_code=status.HTTP_201_CREATED)
async def agent_post_message(
    body: PostMessageRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskMessageDTO:
    """`cliora task say` and `cliora task ask`.

    The **same action** a person needs for the same endpoint (`task.update`), which is
    what makes "humans and agents share one channel" true in the authorization layer
    rather than only in the URL.
    """
    task = await _run_task(session, principal)
    message = await MessageService(session).post(
        task=task,
        body=body.body,
        kind=body.kind,
        author_kind=ACTOR_AGENT,
        run_id=principal.run_id,
    )
    if body.kind == "question" and principal.run_id is not None:
        # A question parks the run: it renews its lease, accrues no execution timeout,
        # and occupies `max_waiting` rather than `max_concurrent` — a run waiting on a
        # person is not running a process (ADR 0029 §5).
        run = await session.get(TaskRun, principal.run_id)
        if run is not None and run.status == "running":
            run.status = "waiting_for_input"
            run.waiting_since = now_utc()
    await session.commit()
    await session.refresh(message)
    return _message_dto(message, author_name=None)


@run_router.post("/artifacts", response_model=TaskArtifactDTO, status_code=status.HTTP_201_CREATED)
async def agent_upload_artifact(
    file: Annotated[UploadFile, File()],
    sha256: Annotated[str, Form()] = "",
    message: Annotated[str, Form()] = "",
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskArtifactDTO:
    """`cliora task attach`, and the path the daemon uses for the diff.

    The daemon's own `git diff` upload comes through here with the **same credential**
    and the **same endpoint** — a side benefit of artifacts being HTTP rather than a
    protocol message, which would have forced the daemon to implement a second upload
    path of its own (ADR 0030 Part B).
    """
    task = await _run_task(session, principal)
    data = await file.read()
    message_id = None
    if message.strip():
        posted = await MessageService(session).post(
            task=task, body=message, author_kind=ACTOR_AGENT, run_id=principal.run_id
        )
        message_id = posted.id
    artifact = await ArtifactService(session, settings=settings).attach(
        task=task,
        filename=file.filename or "artifact",
        data=data,
        declared_sha256=sha256,
        run_id=principal.run_id,
        message_id=message_id,
        uploader_kind="agent",
        user_id=None,
        runner_id=None,
    )
    await session.commit()
    await session.refresh(artifact)
    return _artifact_dto(artifact)


# --- execution plans, verification reports and evidence (DV-06) -----------
#
# **Read with `project.view`, write with `task.update`, and no update path anywhere.**
# The three tables are append-only, and in REST that property is expressed by the
# absence of PUT, PATCH and DELETE rather than by a comment — so this section has
# exactly two verbs.


def _plan_dto(plan: ExecutionPlan) -> ExecutionPlanDTO:
    return ExecutionPlanDTO(
        id=plan.id,
        seq=plan.seq,
        note=plan.note,
        steps=plan.steps or [],
        run_id=plan.run_id,
        created_by_kind=plan.created_by_kind,
        created_at=plan.created_at,
    )


def _report_dto(report: VerificationReport) -> VerificationReportDTO:
    return VerificationReportDTO(
        id=report.id,
        result=report.result,
        checks=report.checks or [],
        acceptance_criteria=report.acceptance_criteria or [],
        remaining_risks=report.remaining_risks or [],
        completion_summary=report.completion_summary,
        source=report.source,
        run_id=report.run_id,
        reported_by_kind=report.reported_by_kind,
        reported_at=report.reported_at,
    )


def _evidence_dto(item: EvidenceItem) -> EvidenceItemDTO:
    return EvidenceItemDTO(
        id=item.id,
        kind=item.kind,
        source=item.source,
        payload=item.payload or {},
        run_id=item.run_id,
        written_by_kind=item.written_by_kind,
        collected_at=item.collected_at,
    )


@router.get("/tasks/{task_id}/plans", response_model=list[ExecutionPlanDTO])
async def list_task_plans(
    task_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ExecutionPlanDTO]:
    await _require_visible_task(session, settings, task_id)
    return [_plan_dto(plan) for plan in await PlanService(session).list_for(task_id)]


@router.post(
    "/tasks/{task_id}/plans",
    response_model=ExecutionPlanDTO,
    status_code=status.HTTP_201_CREATED,
)
async def record_task_plan(
    task_id: uuid.UUID,
    body: RecordPlanRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ExecutionPlanDTO:
    task, _project = await _require_visible_task(session, settings, task_id)
    plan = await PlanService(session).record(
        task=task,
        steps=body.steps,
        note=body.note,
        run_id=None,
        actor_kind=ACTOR_USER,
        user_id=user.id,
        runner_id=None,
    )
    dto = _plan_dto(plan)
    await session.commit()
    return dto


@router.get("/tasks/{task_id}/verification", response_model=list[VerificationReportDTO])
async def list_task_verification(
    task_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[VerificationReportDTO]:
    await _require_visible_task(session, settings, task_id)
    return [_report_dto(r) for r in await VerificationService(session).list_for(task_id)]


@router.post(
    "/tasks/{task_id}/verification",
    response_model=VerificationReportDTO,
    status_code=status.HTTP_201_CREATED,
)
async def submit_task_verification(
    task_id: uuid.UUID,
    body: SubmitVerificationRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> VerificationReportDTO:
    """A submitted report is **always** `agent_reported`, even from a person.

    The level answers "who observed this", and a person typing a result into a form is
    not the platform observing it. `platform_observed` and `machine_verified` have their
    own writers inside the server (ADR 0033 §3b).
    """
    task, _project = await _require_visible_task(session, settings, task_id)
    report = await VerificationService(session).report_from_agent(
        task=task,
        payload=body.model_dump(),
        run_id=None,
        user_id=user.id,
        runner_id=None,
    )
    dto = _report_dto(report)
    await session.commit()
    return dto


@router.get("/tasks/{task_id}/evidence", response_model=list[EvidenceItemDTO])
async def list_task_evidence(
    task_id: uuid.UUID,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[EvidenceItemDTO]:
    """Every source in one list, contradictions included.

    An agent's account of which files changed and `git status` may disagree, and both
    rows stay with their sources named. There is no reconciliation rule: its verdict
    would be a judgement with nobody accountable for it (ADR 0033 §Consequences).
    """
    await _require_visible_task(session, settings, task_id)
    return [_evidence_dto(item) for item in await EvidenceService(session).list_for(task_id)]


@router.post(
    "/tasks/{task_id}/evidence",
    response_model=EvidenceItemDTO,
    status_code=status.HTTP_201_CREATED,
)
async def add_task_evidence(
    task_id: uuid.UUID,
    body: AddEvidenceRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EvidenceItemDTO:
    task, _project = await _require_visible_task(session, settings, task_id)
    item = await EvidenceService(session).add(
        task=task,
        kind=body.kind,
        payload=body.payload,
        run_id=None,
        actor_kind=ACTOR_USER,
        user_id=user.id,
        runner_id=None,
        agent_written=True,
    )
    dto = _evidence_dto(item)
    await session.commit()
    return dto


# --- the same three, for a run credential (`cliora plan|verify|evidence`) ---


@run_router.post("/plan", response_model=ExecutionPlanDTO, status_code=status.HTTP_201_CREATED)
async def agent_record_plan(
    body: RecordPlanRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> ExecutionPlanDTO:
    """`cliora plan snapshot`. Write-only: there is no read counterpart.

    An agent does not need to read back what it just wrote, and every read endpoint is
    another surface to authorize — the same restraint that left `approve` out of the CLI.
    """
    task = await _run_task(session, principal)
    plan = await PlanService(session).record(
        task=task,
        steps=body.steps,
        note=body.note,
        run_id=principal.run_id,
        actor_kind=ACTOR_AGENT,
        user_id=None,
        # `AgentPrincipal` deliberately carries no runner id — a run's identity is the
        # run — and the existing artifact path leaves this null for the same reason.
        runner_id=None,
    )
    dto = _plan_dto(plan)
    await session.commit()
    return dto


@run_router.post(
    "/verification", response_model=VerificationReportDTO, status_code=status.HTTP_201_CREATED
)
async def agent_submit_verification(
    body: SubmitVerificationRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> VerificationReportDTO:
    """`cliora verify report`. Stored as `agent_reported`, whatever the payload says.

    A claimed level is discarded **and recorded**: without the record, an agent
    overstating its evidence and an agent with a typo are indistinguishable afterwards.
    """
    task = await _run_task(session, principal)
    report = await VerificationService(session).report_from_agent(
        task=task,
        payload=body.model_dump(),
        run_id=principal.run_id,
        user_id=None,
        # `AgentPrincipal` deliberately carries no runner id — a run's identity is the
        # run — and the existing artifact path leaves this null for the same reason.
        runner_id=None,
    )
    dto = _report_dto(report)
    await session.commit()
    return dto


@run_router.post("/evidence", response_model=EvidenceItemDTO, status_code=status.HTTP_201_CREATED)
async def agent_add_evidence(
    body: AddEvidenceRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> EvidenceItemDTO:
    """`cliora evidence add`. Only the three `agent_*` kinds.

    A machine kind is **refused rather than downgraded**: a downgraded row would still
    assert something nobody observed.
    """
    task = await _run_task(session, principal)
    item = await EvidenceService(session).add(
        task=task,
        kind=body.kind,
        payload=body.payload,
        run_id=principal.run_id,
        actor_kind=ACTOR_AGENT,
        user_id=None,
        # `AgentPrincipal` deliberately carries no runner id — a run's identity is the
        # run — and the existing artifact path leaves this null for the same reason.
        runner_id=None,
        agent_written=True,
    )
    dto = _evidence_dto(item)
    await session.commit()
    return dto


# --- V2.5: the three writes a requirement-driven run makes (ADR 0034 §2) ----------
#
# Three more routes on the run credential's prefix, and the boundary is the same as the
# six above: `principal.task_id` names the card, the card names the requirement, and
# nothing in the URL can widen that. **This is why the existing human routes were not
# relaxed instead** — `POST /api/requirements/{id}/proposals` takes its requirement from
# the path with nothing binding it to the caller, so lowering it to `task.update` would
# let any run credential in the project write to any requirement, including a
# prompt-injected implementation run (ADR 0034, Alternatives rejected).


async def _run_requirement(
    session: AsyncSession, principal: AgentPrincipal, expected_kind: str
) -> tuple[Task, Requirement]:
    """This run's card and the requirement it is working on.

    `404` rather than `403` for a card that is not this run's, matching `_own_task`: a
    credential must not be usable to discover which cards exist elsewhere. The kind
    mismatch is a `409`, because that one is about the caller's own card and telling it
    the truth costs nothing.
    """
    task = await _run_task(session, principal)
    if task.card_kind != expected_kind:
        raise ApiError(
            "TASK_KIND_MISMATCH",
            f"這條路徑只服務 `{expected_kind}` 卡片，而這張卡是 `{task.card_kind}`",
            status.HTTP_409_CONFLICT,
            details={"card_kind": task.card_kind, "expected": expected_kind},
        )
    if task.requirement_id is None:
        raise ApiError(
            "TASK_KIND_NEEDS_REQUIREMENT",
            "這張卡沒有連到任何需求",
            status.HTTP_409_CONFLICT,
        )
    service = RequirementService(session)
    return task, await service.require(task.requirement_id)


@run_router.get("/requirement", response_model=RequirementDetailDTO)
async def agent_read_requirement(
    principal: AgentPrincipal = Depends(require_agent_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> RequirementDetailDTO:
    """`cliora requirement show`.

    The context pack is a snapshot taken at dispatch. A clarification run that has been
    going for forty minutes has submitted two specification versions that are **not** in
    it, and the agent is invoked statelessly — without this route it would have to
    remember what it wrote.
    """
    task = await _run_task(session, principal)
    if task.requirement_id is None:
        raise ApiError(
            "TASK_KIND_NEEDS_REQUIREMENT",
            "這張卡沒有連到任何需求",
            status.HTTP_409_CONFLICT,
        )
    return await requirement_detail(session, task.requirement_id)


@run_router.post("/spec", response_model=FeatureSpecDTO, status_code=status.HTTP_201_CREATED)
async def agent_submit_spec(
    body: CreateSpecRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureSpecDTO:
    """`cliora spec submit`. A version, never an edit.

    `authored_by` stays NULL and `authored_by_kind` becomes `runner`. The column exists
    so that a NULL author does not have to mean two things, and this is the writer it
    was added for: `AgentPrincipal` carries no `user_id`, deliberately, because a
    principal with one begins impersonating whoever dispatched the run.
    """
    _task, requirement = await _run_requirement(session, principal, CARD_KIND_CLARIFICATION)
    spec = await RequirementService(session).add_spec(
        requirement=requirement,
        actor_id=None,
        fields=body.model_dump(),
        authored_by_kind="runner",
        run_id=principal.run_id,
    )
    await session.refresh(spec)
    dto = _spec_dto(spec)
    await session.commit()
    return dto


@run_router.post("/proposal", response_model=TaskProposalDTO, status_code=status.HTTP_201_CREATED)
async def agent_submit_proposal(
    body: CreateProposalRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskProposalDTO:
    """`cliora proposal submit`. A proposal, and **never a card**.

    The requirement must already be approved. That is checked twice on purpose: once at
    dispatch, which saves a whole run, and once here, which covers a requirement sent
    back to unapproved after the run started.
    """
    _task, requirement = await _run_requirement(session, principal, CARD_KIND_DECOMPOSITION)
    proposal = await RequirementService(session).propose(
        requirement=requirement,
        actor_id=None,
        tree=body.tree,
        run_id=principal.run_id,
    )
    await session.refresh(proposal)
    dto = _proposal_dto(proposal, set())
    await session.commit()
    return dto


@run_router.post(
    "/patch-proposal",
    response_model=DocumentPatchProposalDTO,
    status_code=status.HTTP_201_CREATED,
)
async def agent_submit_patch_proposal(
    body: CreatePatchProposalRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> DocumentPatchProposalDTO:
    """`cliora patch propose`. The platform renders it and records a decision.

    **No `card_kind` restriction**, unlike the two routes above. A document is most often
    discovered to be wrong by the implementation card that ran into it, and refusing
    that would leave the agent able only to mention it in a comment.
    """
    task = await _run_task(session, principal)
    proposal = await PatchProposalService(session).submit(
        task=task, run_id=principal.run_id, payload=body.model_dump()
    )
    await session.refresh(proposal)
    dto = _patch_dto(proposal)
    await session.commit()
    return dto


# --- V2.5: the person's side of a patch proposal ---------------------------------


def _patch_dto(proposal: DocumentPatchProposal) -> DocumentPatchProposalDTO:
    return DocumentPatchProposalDTO(
        id=proposal.id,
        project_id=proposal.project_id,
        requirement_id=proposal.requirement_id,
        run_id=proposal.run_id,
        seq=proposal.seq,
        target_path=proposal.target_path,
        diff=proposal.diff,
        sections=proposal.sections or {},
        reason=proposal.reason,
        related_task_ids=list(proposal.related_task_ids or []),
        open_questions=list(proposal.open_questions or []),
        status=proposal.status,
        decided_by=proposal.decided_by,
        decided_at=proposal.decided_at,
        decision_note=proposal.decision_note,
        created_at=proposal.created_at,
    )


@router.get("/projects/{project_id}/patch-proposals", response_model=list[DocumentPatchProposalDTO])
async def list_patch_proposals(
    project_id: uuid.UUID,
    pending_only: bool = True,
    _user: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[DocumentPatchProposalDTO]:
    await ProjectService(session, settings=settings).require(project_id)
    rows = await PatchProposalService(session).listing(project_id, pending_only=pending_only)
    return [_patch_dto(row) for row in rows]


@router.post("/patch-proposals/{proposal_id}/accept", response_model=DocumentPatchProposalDTO)
async def accept_patch_proposal(
    proposal_id: uuid.UUID,
    body: DecidePatchProposalRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> DocumentPatchProposalDTO:
    """Accepting records a decision and **creates nothing**.

    Not even a card. Accepting a proposal and scheduling the work are two decisions: the
    second needs a target branch, tags and a priority, and one proposal may map to zero
    cards (someone edits the document themselves) or to three.
    """
    service = PatchProposalService(session)
    proposal = await service.require(proposal_id)
    await service.decide(proposal=proposal, actor_id=user.id, accept=True, note=body.note)
    dto = _patch_dto(proposal)
    await session.commit()
    return dto


@router.post("/patch-proposals/{proposal_id}/reject", response_model=DocumentPatchProposalDTO)
async def reject_patch_proposal(
    proposal_id: uuid.UUID,
    body: DecidePatchProposalRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> DocumentPatchProposalDTO:
    service = PatchProposalService(session)
    proposal = await service.require(proposal_id)
    await service.decide(proposal=proposal, actor_id=user.id, accept=False, note=body.note)
    dto = _patch_dto(proposal)
    await session.commit()
    return dto
