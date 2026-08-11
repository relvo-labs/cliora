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

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import (
    require_action,
    require_agent_runs_enabled,
    require_projects_enabled,
)
from app.api.http.schemas import (
    AgentRunnerDTO,
    CreateRepositoryRequest,
    DispatchRequest,
    DispatchResponseDTO,
    PostMessageRequest,
    ProjectRepositoryDTO,
    RunLogLineDTO,
    RunLogPageDTO,
    TaskMessageDTO,
    TaskRunDTO,
    UpdateAgentRequest,
)
from app.db.engine import get_session
from app.db.models import AgentRunner, ProjectRepository, RunLog, TaskMessage, TaskRun, User
from app.services.activity import ACTOR_USER
from app.services.projects import ProjectService
from app.services.rbac import (
    AGENT_MANAGE,
    AGENT_VIEW,
    PROJECT_MANAGE,
    PROJECT_VIEW,
    RUN_CANCEL,
    RUN_DISPATCH,
    TASK_UPDATE,
)
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.runners import RepositoryService, RunnerService, RunnerView, clone_url
from app.services.runs import MessageService, RunService
from app.services.tasks import TaskService
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
        max_concurrent=runner.max_concurrent,
        max_waiting=runner.max_waiting,
        enabled=runner.enabled,
        dedicated=runner.dedicated,
        online=view.online,
        active_runs=view.active_runs,
        waiting_runs=view.waiting_runs,
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


def _run_dto(run: TaskRun, *, runner_name: str | None) -> TaskRunDTO:
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

    Not filtered by project, and that is the phase's posture rather than an oversight:
    **V2.2's authorization boundary is enrollment.** A runner on any enrolled node can
    claim any project's card and pull any project's code, and per-project authorization
    arrives in V2.3 (ADR 0029 sec 3). The Agents page states this in words next to the
    list, because it is the kind of design that gets reported as a bug otherwise.
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
    """Enable/disable, concurrency and labels — and nothing else in this phase.

    There is deliberately **no binding endpoint**: `project_agents` arrives in V2.3
    together with the secrets it authorises. Creating the route now, against a table
    that authorises nothing, would cost V2.3's security review a real checkpoint.
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
    return DispatchResponseDTO(run_id=result.run.id, status="queued", waiting_reason=reason)


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
    await _require_visible_task(session, settings, run.task_id)
    names = await _runner_names(session, [run])
    return _run_dto(run, runner_name=names.get(run.runner_id or uuid.uuid4()))


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
