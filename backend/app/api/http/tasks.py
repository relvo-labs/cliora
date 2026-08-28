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
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import (
    may_perform,
    require_action,
    require_agent_action,
    require_projects_enabled,
)
from app.api.http.schemas import (
    AddDependencyRequest,
    CreateEpicRequest,
    CreateTaskRequest,
    CreateUserStoryRequest,
    GateDecisionRequest,
    GateDTO,
    ProcessDTO,
    ProcessOverridesRequest,
    ProjectVerificationDTO,
    ProjectVerificationRequest,
    RankRequest,
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
    VerificationCommandsRequest,
)
from app.db.engine import get_session
from app.db.models import Epic, Task, User, UserStory
from app.services.agent_auth import AGENT_FORBIDDEN_FIELDS, AgentPrincipal, SessionTokenService
from app.services.evidence import validate_commands
from app.services.process import EffectiveProcess, ProcessService
from app.services.projects import ProjectService
from app.services.rbac import (
    PROCESS_MANAGE,
    PROJECT_MANAGE,
    PROJECT_VIEW,
    TASK_APPROVE,
    TASK_CREATE,
    TASK_FORCE_DONE,
    TASK_UPDATE,
)
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.tasks import TaskService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(require_projects_enabled)])


def _tasks(session: AsyncSession, settings: Settings | None = None) -> TaskService:
    """Settings are passed in, never resolved inside the service.

    Only the routes that reach a flag-dependent rule need to supply them; the rest keep
    the one-argument call. The Done Gate is the first such rule (ADR 0033 §5).
    """
    return TaskService(session, settings=settings)


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


async def _project(session: AsyncSession, settings: Settings, project_id: uuid.UUID):
    return await ProjectService(session, settings=settings).require(project_id)


def _process_dto(
    process: EffectiveProcess, *, overrides: dict[str, Any] | None = None
) -> ProcessDTO:
    return ProcessDTO(
        overrides=overrides or {},
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
        # An Epic and a User Story are containers, not work. `implementation` is the
        # column's own default and the only honest answer: they have no kind because
        # nothing dispatches them.
        card_kind="implementation",
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
        # An Epic and a User Story are containers, not work. `implementation` is the
        # column's own default and the only honest answer: they have no kind because
        # nothing dispatches them.
        card_kind="implementation",
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
        card_kind=task.card_kind,
        requirement_id=task.requirement_id,
        proposal_id=task.proposal_id,
        depends_on=[
            TaskDependencyDTO(
                id=item.id, card_ref=item.card_ref, title=item.title, stage=item.stage
            )
            for item in dependencies
        ],
        blocking_refs=await service.blocking_refs(task.id),
        conversation_seq=task.conversation_seq,
        open_question_count=task.open_question_count,
        waiting_for_actor=task.waiting_for_actor,
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
    project = await _project(session, settings, project_id)
    return _process_dto(
        await _tasks(session).process(project), overrides=dict(project.process_overrides or {})
    )


@router.put("/projects/{project_id}/process/overrides", response_model=ProcessDTO)
async def set_process_overrides(
    project_id: uuid.UUID,
    body: ProcessOverridesRequest,
    user: User = Depends(require_action(PROCESS_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProcessDTO:
    """Turn existing process items off, or adjust WIP advice. Nothing else.

    `process.manage` rather than `project.manage`: a project's settings describe one
    project, while the process definition is the vocabulary every board and every
    cross-project metric is expressed in (ADR 0033 §5).

    Returns the **applied** definition, not the stored switches alone — the screen that
    made the change is the screen that has to show its effect.
    """
    project = await _project(session, settings, project_id)
    service = ProcessService(session)
    stored = await service.set_overrides(project, body.model_dump(), actor_id=user.id)
    dto = _process_dto(await service.effective(project=project), overrides=stored)
    await session.commit()
    return dto


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
    may_force: bool = Depends(may_perform(TASK_FORCE_DONE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskWriteDTO:
    """Move or edit a card, under the version it was read at.

    A dragged card sends `{stage, version}`; the console applies the move
    optimistically and rolls it back on any refusal, which is why the 409 body carries
    the card's current version (`plan/17/07-…md` §2.2).
    """
    service = _tasks(session, settings)
    task = await service.require_task(task_id)
    changes = body.model_dump(exclude_unset=True)
    changes.pop("version", None)
    force = bool(changes.pop("force", False))
    force_reason = changes.pop("force_reason", None)
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
        force=force,
        force_reason=force_reason,
        may_force=may_force,
    )
    # Serialise before committing: `expire_on_commit` means every column read after
    # the commit is a fresh SELECT, and the DTO already holds everything it needs.
    dto = TaskWriteDTO(task=await _task_dto(service, result.task), warnings=result.warnings)
    await session.commit()
    return dto


@router.put("/projects/{project_id}/verification-commands", response_model=ProjectVerificationDTO)
async def set_project_verification_commands(
    project_id: uuid.UUID,
    body: ProjectVerificationRequest,
    _user: User = Depends(require_action(PROJECT_MANAGE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectVerificationDTO:
    """The project's checks, and the optional requirement that one of them ran.

    `project.manage` rather than `process.manage`: these describe *this* project's
    definition of verified, while the process definition is the vocabulary shared across
    projects (ADR 0033 §5).

    `require_project_verification` is **off by default**, and turning it on is what
    converges the flexibility the card store buys: a card that ran only its own checks
    then cannot reach `done`. Off by default because a switch that blocks people on day
    one teaches them to stop using the feature it guards.
    """
    project = await _project(session, settings, project_id)
    project.verification_commands = validate_commands(
        [command.model_dump() for command in body.commands], origin="project"
    )
    project.require_project_verification = body.require_project_verification
    await session.flush()
    dto = ProjectVerificationDTO(
        commands=project.verification_commands,
        require_project_verification=project.require_project_verification,
    )
    await session.commit()
    return dto


@router.put("/tasks/{task_id}/verification-commands", response_model=TaskDTO)
async def set_task_verification_commands(
    task_id: uuid.UUID,
    body: VerificationCommandsRequest,
    user: User = Depends(require_action(TASK_APPROVE)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TaskDTO:
    """This card's own checks — **`task.approve`, not `task.update`**.

    That is the entire security argument for letting a card declare verification at all.
    `RUN_TOKEN_SCOPES` is `{project.view, task.update}` and never contains
    `task.approve`; `services/agent_auth.py` records that the two actions are held by
    the same people on purpose and were separated precisely so a credential's scope
    could exclude one. So a person may declare a check here and **the agent being
    verified may not** — which is what keeps both origins `machine_verified`
    (ADR 0033 §3b).

    Its own endpoint rather than a field on `PATCH` for the same reason: reachable
    through that body it would be writable with `task.update`.
    """
    service = _tasks(session, settings)
    task = await service.require_task(task_id)
    await _project(session, settings, task.project_id)
    task.verification_commands = validate_commands(
        [command.model_dump() for command in body.commands], origin="card"
    )
    await session.flush()
    dto = await _task_dto(service, task)
    await session.commit()
    return dto


@router.post("/tasks/{task_id}/rank", response_model=TaskDTO)
async def rank_task(
    task_id: uuid.UUID,
    body: RankRequest,
    user: User = Depends(require_action(TASK_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> TaskDTO:
    """Move a card to a position between two named neighbours (V2-P1, `FR-WORK-006`).

    Its own route rather than a `PATCH` field, for two reasons that are the same reason:
    the payload is a *pair of neighbours* rather than a value, and the response has to be
    able to refuse with `RANK_NEIGHBOR_STALE` — a refusal that means "the board moved
    under you", which is not what `TASK_VERSION_CONFLICT` means. `rank` is still in
    `EDITABLE_FIELDS` so a person can set one directly, and it is in
    `AGENT_FORBIDDEN_FIELDS` because an agent that can reorder the queue has made
    first-in-first-out advisory.

    `task.update`, the same action a drag already needed. ~~`read_board` and
    `BoardCardDTO` are untouched (D48)~~ — both were **deleted** in `beta.2` (ADR 0044);
    `work-items` is the only board read now.
    """
    service = _tasks(session)
    task = await service.require_task(task_id)
    moved = await service.reorder(
        task=task,
        actor_id=user.id,
        expected_version=body.version,
        previous_task_id=body.previous_task_id,
        next_task_id=body.next_task_id,
        stage=body.stage,
    )
    dto = await _task_dto(service, moved)
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
    settings: Settings = Depends(get_settings),
) -> TaskWriteDTO:
    """`cliora task update`. The only write an agent can make.

    Two refusals stack here, and the second is not redundant: the gate endpoint is
    already unreachable, and this closes the open-shaped `PATCH` body behind it. An
    agent cannot set `gates`, an owner, a runner or a secret list — those are people's
    decisions (ADR 0028 sec 3).
    """
    service = _tasks(session, settings)
    task = await service.require_task(task_id)
    _same_project(principal, task)
    changes = body.model_dump(exclude_unset=True)
    changes.pop("version", None)
    # Popped rather than left to default: an agent that sends `force: true` gets the
    # same 403 as one that sends `gates`, and the reason shows up in the list below
    # instead of being silently ignored.
    if changes.pop("force", False) or changes.pop("force_reason", None):
        raise ApiError(
            "FORBIDDEN_FIELD",
            "An agent may not force a card into done",
            status.HTTP_403_FORBIDDEN,
        )
    changes.pop("force", None)
    changes.pop("force_reason", None)
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
