"""Board, roadmap, cards, dependencies and review gates (TK-04, ADR 0028).

Mounted unconditionally with `require_projects_enabled` on the router, the same shape
`projects.py` uses and for the same reason: `test_every_mounted_route_is_in_the_matrix`
reads the import-time route table, so a conditionally mounted router would make
`make check` pass or fail according to the environment it ran in (ADR 0027 sec 3).

Routes stay thin — authorization at the boundary, rules in `services/tasks.py`,
queries in `repositories/tasks.py`. Two things are decided here rather than in the
service, because both depend on the *caller* rather than on the resource:

* who may see an actor's name on the timeline (inherited from `projects.py`);
* which principal is writing — a person through `require_action`, or a session's
  agent through `require_actor_action` (`services/agent_auth.py`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import (
    require_action,
    require_agent_action,
    require_projects_enabled,
)
from app.api.http.schemas import (
    AddDependencyRequest,
    BoardCardDTO,
    BoardDTO,
    BoardLaneDTO,
    CreateEpicRequest,
    CreateTaskRequest,
    CreateUserStoryRequest,
    GateDecisionRequest,
    GateDTO,
    ProcessDTO,
    RoadmapDTO,
    RoadmapEpicDTO,
    RoadmapStoryDTO,
    RoadmapTaskDTO,
    TaskDependencyDTO,
    TaskDTO,
    TaskWriteDTO,
    UpdateEpicRequest,
    UpdateTaskRequest,
    UpdateUserStoryRequest,
)
from app.db.engine import get_session
from app.db.models import Epic, Task, User, UserStory
from app.services.agent_auth import AGENT_FORBIDDEN_FIELDS, AgentPrincipal, SessionTokenService
from app.services.process import EffectiveProcess
from app.services.projects import ProjectService
from app.services.rbac import PROJECT_VIEW, TASK_APPROVE, TASK_CREATE, TASK_UPDATE
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.tasks import TaskService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(require_projects_enabled)])


def _tasks(session: AsyncSession) -> TaskService:
    return TaskService(session)


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


async def _project(session: AsyncSession, settings: Settings, project_id: uuid.UUID):
    return await ProjectService(session, settings=settings).require(project_id)


def _process_dto(process: EffectiveProcess) -> ProcessDTO:
    return ProcessDTO(
        key=process.key,
        version=process.version,
        source=process.source,
        lanes=process.lanes,
        readiness=process.readiness,
        gates=[
            GateDTO(
                key=gate.key,
                label=gate.label,
                order=gate.order,
                requires_human=gate.requires_human,
                enabled=gate.enabled,
                disabled_reason=gate.disabled_reason,
            )
            for gate in process.gates
        ],
        templates=process.templates,
    )


def _epic_dto(epic: Epic) -> TaskDTO:
    return TaskDTO(
        id=epic.id,
        project_id=epic.project_id,
        card_ref=epic.card_ref,
        title=epic.title,
        description=epic.description,
        objective=None,
        scope=None,
        non_goals=None,
        stage="backlog",
        risk="medium",
        priority="normal",
        owner_user_id=None,
        epic_id=None,
        user_story_id=None,
        readiness={},
        gates={},
        acceptance_criteria=[],
        links={},
        required_labels=[],
        version=1,
        source="none",
        repository_id=None,
        base_branch=None,
        delivery="none",
        target_branch=None,
        existing_pr_ref=None,
        required_secrets=[],
        assigned_runner_id=None,
        requirement_id=None,
        proposal_id=None,
        depends_on=[],
        blocking_refs=[],
        created_at=epic.created_at,
        updated_at=epic.updated_at,
    )


def _story_dto(story: UserStory) -> TaskDTO:
    return TaskDTO(
        id=story.id,
        project_id=story.project_id,
        card_ref=story.card_ref,
        title=story.title,
        description=story.narrative,
        objective=None,
        scope=None,
        non_goals=None,
        stage="backlog",
        risk="medium",
        priority="normal",
        owner_user_id=None,
        epic_id=story.epic_id,
        user_story_id=None,
        readiness={},
        gates={},
        acceptance_criteria=[],
        links={},
        required_labels=[],
        version=1,
        source="none",
        repository_id=None,
        base_branch=None,
        delivery="none",
        target_branch=None,
        existing_pr_ref=None,
        required_secrets=[],
        assigned_runner_id=None,
        requirement_id=None,
        proposal_id=None,
        depends_on=[],
        blocking_refs=[],
        created_at=story.created_at,
        updated_at=story.updated_at,
    )


async def _task_dto(service: TaskService, task: Task) -> TaskDTO:
    await service.refresh(task)
    dependencies = await service.dependencies(task.id)
    return TaskDTO(
        id=task.id,
        project_id=task.project_id,
        card_ref=task.card_ref,
        title=task.title,
        description=task.description,
        objective=task.objective,
        scope=task.scope,
        non_goals=task.non_goals,
        stage=task.stage,
        risk=task.risk,
        priority=task.priority,
        owner_user_id=task.owner_user_id,
        epic_id=task.epic_id,
        user_story_id=task.user_story_id,
        readiness=task.readiness or {},
        gates=task.gates or {},
        acceptance_criteria=task.acceptance_criteria or [],
        links=task.links or {},
        required_labels=task.required_labels or [],
        version=task.version,
        source=task.source,
        repository_id=task.repository_id,
        base_branch=task.base_branch,
        delivery=task.delivery,
        target_branch=task.target_branch,
        existing_pr_ref=task.existing_pr_ref,
        required_secrets=task.required_secrets or [],
        assigned_runner_id=task.assigned_runner_id,
        requirement_id=task.requirement_id,
        proposal_id=task.proposal_id,
        depends_on=[
            TaskDependencyDTO(
                id=item.id, card_ref=item.card_ref, title=item.title, stage=item.stage
            )
            for item in dependencies
        ],
        blocking_refs=await service.blocking_refs(task.id),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


# --- reads -----------------------------------------------------------------------


@router.get("/projects/{project_id}/process", response_model=ProcessDTO)
async def read_process(
    project_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProcessDTO:
    """The process as it applies here, integration-dependent gates already resolved.

    Per project in the URL even though V2.1 has one global definition: the caller's
    question is "what applies to this board", and V2.4's per-project override should
    not change the shape of the request.
    """
    await _project(session, settings, project_id)
    return _process_dto(await _tasks(session).process())


@router.get("/projects/{project_id}/board", response_model=BoardDTO)
async def read_board(
    project_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> BoardDTO:
    """Every card in the project, grouped by lane. One response, no paging.

    M1 (`plan/17/10-…md` §1): the summary shape is 74 KB at 200 cards and 180 KB at
    500, while the full card is 439 KB and over a megabyte. Moving acceptance criteria
    and gate detail out of the card bought what paging would have, without a cursor,
    a scroll loader or an e2e for either.
    """
    await _project(session, settings, project_id)
    service = _tasks(session)
    process = await service.process()
    cards = await service.board(project_id, is_online=registry.is_connected)
    grouped: dict[str, list[BoardCardDTO]] = {lane["stage"]: [] for lane in process.lanes}
    for card in cards:
        grouped.setdefault(card.task.stage, []).append(
            BoardCardDTO(
                id=card.task.id,
                card_ref=card.task.card_ref,
                title=card.task.title,
                stage=card.task.stage,
                risk=card.task.risk,
                priority=card.task.priority,
                owner_user_id=card.task.owner_user_id,
                owner_name=card.owner_name,
                delivery=card.task.delivery,
                blocking_count=card.blocking_count,
                gates_approved_count=card.gates_approved_count,
                active_run_status=card.active_run_status,
                active_run_runner_name=card.active_run_runner_name,
                waiting_reason=card.waiting_reason,
                version=card.task.version,
                updated_at=card.task.updated_at,
            )
        )
    lanes = [
        BoardLaneDTO(
            stage=lane["stage"],
            label=lane.get("label", lane["stage"]),
            wip_suggested=lane.get("wip_suggested"),
            count=len(grouped.get(lane["stage"], [])),
            cards=grouped.get(lane["stage"], []),
        )
        for lane in process.lanes
    ]
    return BoardDTO(lanes=lanes)


@router.get("/projects/{project_id}/roadmap", response_model=RoadmapDTO)
async def read_roadmap(
    project_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RoadmapDTO:
    """Epic → story → card, with two unclassified buckets.

    Two, not one: a card filed under an epic but under no story belongs to that epic's
    bucket, and a card with neither belongs to the top-level one. Monstrare defines
    both, and a card must never disappear because of how it was filed (D4).
    """
    await _project(session, settings, project_id)
    epics, stories, tasks = await _tasks(session).roadmap(project_id)
    return _roadmap_dto(epics, stories, tasks)


def _roadmap_dto(epics: list[Epic], stories: list[UserStory], tasks: list[Task]) -> RoadmapDTO:
    def card(task: Task) -> RoadmapTaskDTO:
        return RoadmapTaskDTO(
            id=task.id, card_ref=task.card_ref, title=task.title, stage=task.stage
        )

    by_story: dict[uuid.UUID, list[Task]] = {}
    epic_unclassified: dict[uuid.UUID, list[Task]] = {}
    loose: list[Task] = []
    for task in tasks:
        if task.user_story_id is not None:
            by_story.setdefault(task.user_story_id, []).append(task)
        elif task.epic_id is not None:
            epic_unclassified.setdefault(task.epic_id, []).append(task)
        else:
            loose.append(task)

    def story_dto(story: UserStory) -> RoadmapStoryDTO:
        items = by_story.get(story.id, [])
        return RoadmapStoryDTO(
            id=story.id,
            card_ref=story.card_ref,
            title=story.title,
            done_count=sum(1 for item in items if item.stage == "done"),
            total_count=len(items),
            tasks=[card(item) for item in items],
        )

    epic_dtos = []
    for epic in epics:
        epic_stories = [story_dto(story) for story in stories if story.epic_id == epic.id]
        extra = epic_unclassified.get(epic.id, [])
        done = sum(dto.done_count for dto in epic_stories) + sum(
            1 for item in extra if item.stage == "done"
        )
        total = sum(dto.total_count for dto in epic_stories) + len(extra)
        epic_dtos.append(
            RoadmapEpicDTO(
                id=epic.id,
                card_ref=epic.card_ref,
                title=epic.title,
                done_count=done,
                total_count=total,
                stories=epic_stories,
                unclassified=[card(item) for item in extra],
            )
        )
    return RoadmapDTO(
        epics=epic_dtos,
        orphan_stories=[story_dto(story) for story in stories if story.epic_id is None],
        unclassified=[card(item) for item in loose],
        done_count=sum(1 for task in tasks if task.stage == "done"),
        total_count=len(tasks),
    )


@router.get("/projects/{project_id}/tasks", response_model=list[TaskDTO])
async def list_tasks(
    project_id: uuid.UUID,
    ref: str | None = Query(default=None, max_length=32),
    stage: str | None = Query(default=None, max_length=16),
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[TaskDTO]:
    """Cards in a project, optionally by `card_ref`.

    `card_ref` is a query parameter rather than a path segment because it is only
    unique *within a project*, and because the repository's other path parameters are
    all ids — one field with two meanings is the shape this codebase keeps refusing.
    The CLI pays one extra round trip for that (`plan/17/03-…md` §3.2).
    """
    await _project(session, settings, project_id)
    service = _tasks(session)
    if ref is not None:
        return [await _task_dto(service, await service.by_ref(project_id, ref))]
    # Not `_, _, tasks`: `_` is the injected user in this signature, and rebinding it
    # here made mypy read the roadmap tuple as a `User`.
    _epics, _stories, tasks = await service.roadmap(project_id)
    if stage is not None:
        tasks = [task for task in tasks if task.stage == stage]
    return [await _task_dto(service, task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=TaskDTO)
async def read_task(
    task_id: uuid.UUID,
    _: User = Depends(require_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    service = _tasks(session)
    return await _task_dto(service, await service.require_task(task_id))


# --- writes ----------------------------------------------------------------------


@router.post("/projects/{project_id}/epics", response_model=TaskDTO, status_code=201)
async def create_epic(
    project_id: uuid.UUID,
    body: CreateEpicRequest,
    response: Response,
    user: User = Depends(require_action(TASK_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskDTO:
    project = await _project(session, settings, project_id)
    service = _tasks(session)
    epic = await service.create_epic(
        project=project, actor_id=user.id, title=body.title, description=body.description
    )
    await session.commit()
    response.headers["Location"] = f"/api/projects/{project_id}/roadmap"
    # An epic is not a card, so it borrows the card DTO only for its identifiers; the
    # roadmap is where it is actually read.
    return _epic_dto(epic)


@router.post("/projects/{project_id}/user-stories", response_model=TaskDTO, status_code=201)
async def create_user_story(
    project_id: uuid.UUID,
    body: CreateUserStoryRequest,
    user: User = Depends(require_action(TASK_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskDTO:
    project = await _project(session, settings, project_id)
    story = await _tasks(session).create_story(
        project=project,
        actor_id=user.id,
        title=body.title,
        narrative=body.narrative,
        epic_id=body.epic_id,
    )
    await session.commit()
    return _story_dto(story)


@router.patch("/epics/{epic_id}", response_model=TaskDTO)
async def update_epic(
    epic_id: uuid.UUID,
    body: UpdateEpicRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    epic = await _tasks(session).update_epic(
        epic_id=epic_id,
        actor_id=user.id,
        changes=body.model_dump(exclude_unset=True),
    )
    dto = _epic_dto(epic)
    await session.commit()
    return dto


@router.patch("/user-stories/{story_id}", response_model=TaskDTO)
async def update_user_story(
    story_id: uuid.UUID,
    body: UpdateUserStoryRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    story = await _tasks(session).update_story(
        story_id=story_id,
        actor_id=user.id,
        changes=body.model_dump(exclude_unset=True),
    )
    dto = _story_dto(story)
    await session.commit()
    return dto


@router.post("/projects/{project_id}/tasks", response_model=TaskWriteDTO, status_code=201)
async def create_task(
    project_id: uuid.UUID,
    body: CreateTaskRequest,
    user: User = Depends(require_action(TASK_CREATE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskWriteDTO:
    project = await _project(session, settings, project_id)
    service = _tasks(session)
    result = await service.create_task(
        project=project, actor_id=user.id, fields=body.model_dump(exclude_none=False)
    )
    # Serialise before committing: `expire_on_commit` means every column read after
    # the commit is a fresh SELECT, and the DTO already holds everything it needs.
    dto = TaskWriteDTO(task=await _task_dto(service, result.task), warnings=result.warnings)
    await session.commit()
    return dto


@router.patch("/tasks/{task_id}", response_model=TaskWriteDTO)
async def update_task(
    task_id: uuid.UUID,
    body: UpdateTaskRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskWriteDTO:
    """Move or edit a card, under the version it was read at.

    A dragged card sends `{stage, version}`; the console applies the move
    optimistically and rolls it back on any refusal, which is why the 409 body carries
    the card's current version (`plan/17/07-…md` §2.2).
    """
    service = _tasks(session)
    task = await service.require_task(task_id)
    changes = body.model_dump(exclude_unset=True)
    changes.pop("version", None)
    if not changes:
        raise ApiError(
            "INVALID_ARGUMENT",
            "Nothing to change",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    result = await service.update_task(
        task=task,
        actor_id=user.id,
        actor_kind="user",
        expected_version=body.version,
        changes=changes,
    )
    # Serialise before committing: `expire_on_commit` means every column read after
    # the commit is a fresh SELECT, and the DTO already holds everything it needs.
    dto = TaskWriteDTO(task=await _task_dto(service, result.task), warnings=result.warnings)
    await session.commit()
    return dto


@router.post("/tasks/{task_id}/dependencies", response_model=TaskDTO, status_code=201)
async def add_dependency(
    task_id: uuid.UUID,
    body: AddDependencyRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    service = _tasks(session)
    task = await service.require_task(task_id)
    await service.add_dependency(task=task, depends_on_id=body.depends_on_task_id, actor_id=user.id)
    # Serialise before committing: `expire_on_commit` means every column read after
    # the commit is a fresh SELECT, and the DTO already holds everything it needs.
    dto = await _task_dto(service, task)
    await session.commit()
    return dto


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_dependency(
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _tasks(session)
    task = await service.require_task(task_id)
    await service.remove_dependency(task=task, depends_on_id=depends_on_id, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tasks/{task_id}/gates/{gate_key}", response_model=TaskDTO)
async def decide_gate(
    task_id: uuid.UUID,
    gate_key: str,
    body: GateDecisionRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    """Tick or untick a review gate. Always a person (ADR 0028 sec 1).

    `task.approve` is a separate action from `task.update` even though the same two
    roles hold both — that split is what lets a session credential's scope exclude
    approval, and an agent principal cannot reach this route at all.

    Un-ticking is the same action and is audited the same way: a tick that can never
    be undone is a tick nobody dares make.
    """
    service = _tasks(session)
    task = await service.require_task(task_id)
    await service.approve_gate(task=task, gate_key=gate_key, actor=user, approve=body.approved)
    # Serialise before committing: `expire_on_commit` means every column read after
    # the commit is a fresh SELECT, and the DTO already holds everything it needs.
    dto = await _task_dto(service, task)
    await session.commit()
    return dto


# --- the agent surface -----------------------------------------------------------
#
# Four endpoints, on their own prefix — named for the client rather than for the
# caller's nature, because `/api/agent/…` collides with SCOPE-001's guard against any
# surface that models a runtime's internal agent concepts. Narrowing a second scope
# guard to fit a route name would be the wrong trade.
#
# Not the same paths with a second dependency:
# a route that accepts either principal would need every handler below it to ask which
# one it got, and the first handler to forget is an agent doing something a person was
# meant to. A separate prefix makes the reachable set enumerable — and
# `test_the_agent_surface_is_exactly_four_routes` pins its size.
#
# Every one of them additionally checks `principal.project_id`: a credential may only
# touch cards in the project its session belongs to, and a mismatch answers 404 rather
# than 403 so a token cannot be used to discover which cards exist elsewhere.

agent_router = APIRouter(
    prefix="/api/cli", tags=["agent"], dependencies=[Depends(require_projects_enabled)]
)


def _same_project(principal: AgentPrincipal, task: Task) -> None:
    if task.project_id != principal.project_id:
        raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)


@agent_router.get("/tasks", response_model=list[TaskDTO])
async def agent_list_tasks(
    ref: str | None = Query(default=None, max_length=32),
    stage: str | None = Query(default=None, max_length=16),
    principal: AgentPrincipal = Depends(require_agent_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> list[TaskDTO]:
    """`cliora task list` and the first half of `cliora task get <ref>`.

    No project in the path: the credential already names one, and letting the caller
    supply it would mean checking that it matches — one more place to get wrong.
    """
    service = _tasks(session)
    if ref is not None:
        task = await service.by_ref(principal.project_id, ref)
        return [await _task_dto(service, task)]
    _epics, _stories, tasks = await service.roadmap(principal.project_id)
    if stage is not None:
        tasks = [task for task in tasks if task.stage == stage]
    return [await _task_dto(service, task) for task in tasks]


@agent_router.get("/tasks/{task_id}", response_model=TaskDTO)
async def agent_read_task(
    task_id: uuid.UUID,
    principal: AgentPrincipal = Depends(require_agent_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    service = _tasks(session)
    task = await service.require_task(task_id)
    _same_project(principal, task)
    return await _task_dto(service, task)


@agent_router.patch("/tasks/{task_id}", response_model=TaskWriteDTO)
async def agent_update_task(
    task_id: uuid.UUID,
    body: UpdateTaskRequest,
    principal: AgentPrincipal = Depends(require_agent_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskWriteDTO:
    """`cliora task update`. The only write an agent can make.

    Two refusals stack here, and the second is not redundant: the gate endpoint is
    already unreachable, and this closes the open-shaped `PATCH` body behind it. An
    agent cannot set `gates`, an owner, a runner or a secret list — those are people's
    decisions (ADR 0028 sec 3).
    """
    service = _tasks(session)
    task = await service.require_task(task_id)
    _same_project(principal, task)
    changes = body.model_dump(exclude_unset=True)
    changes.pop("version", None)
    forbidden = sorted(AGENT_FORBIDDEN_FIELDS & changes.keys())
    if forbidden:
        raise ApiError(
            "FORBIDDEN_FIELD",
            f"An agent may not set: {', '.join(forbidden)}",
            status.HTTP_403_FORBIDDEN,
        )
    if not changes:
        raise ApiError(
            "INVALID_ARGUMENT", "Nothing to change", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    result = await service.update_task(
        task=task,
        actor_id=None,
        actor_kind="agent",
        expected_version=body.version,
        changes=changes,
    )
    dto = TaskWriteDTO(task=await _task_dto(service, result.task), warnings=result.warnings)
    await SessionTokenService(session).touch(principal.token_id)
    await session.commit()
    return dto


@agent_router.get("/process", response_model=ProcessDTO)
async def agent_read_process(
    _: AgentPrincipal = Depends(require_agent_action(PROJECT_VIEW)),
    session: AsyncSession = Depends(get_session),
) -> ProcessDTO:
    """What the lanes and gates are, so the CLI can say what it is doing."""
    return _process_dto(await _tasks(session).process())
