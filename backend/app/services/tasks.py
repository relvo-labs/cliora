"""Epics, user stories and task cards: the rules the board actually enforces (TK-04).

Three of them, and the *narrowness* is the design (ADR 0028 sec 1):

1. **A card may not enter `ready` or beyond while a dependency is unfinished**, and
   the refusal names the blocking `card_ref`s. This is the one rule where the platform
   holds every fact needed to be certain.
2. **Every write carries a version.** A mismatch is a 409 that returns the card's
   current value, so the caller can re-render without a second request — and, more
   importantly, nothing half-written lands.
3. **A review gate always records a human.** The action layer is one half; the other
   is that a session credential never reaches this module's approval path at all
   (`services/agent_auth.py`).

Everything else — the seven readiness items, the WIP advice — **warns**. Enforcing all
seven from day one is how a board stops being written to, and a board nobody writes to
is a source of truth that lies (research/02/03, the risk table's last row).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Epic, Project, Requirement, Task, TaskRun, UserStory
from app.repositories.tasks import TaskRepository
from app.services import audit as audit_actions
from app.services.activity import (
    EPIC_CREATED,
    TASK_CREATED,
    TASK_FORCED_DONE,
    TASK_GATE_APPROVED,
    TASK_STAGE_CHANGED,
    TASK_UPDATED,
    USER_STORY_CREATED,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.done_gate import CRITERION_RESULTS, DoneGateService
from app.services.process import DEPENDENCY_GATED_STAGES, STAGES, EffectiveProcess, ProcessService
from app.services.work.ranking import (
    INITIAL_RANK,
    INLINE_REBALANCE_THRESHOLD,
    REBALANCE_THRESHOLD,
    rank_between,
    rebalanced_ranks,
)
from app.settings import Settings, get_settings

# Fields a `PATCH` may set. Anything outside this set is refused by name rather than
# ignored: a silently dropped field is a change the caller believes it made.
EDITABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "objective",
        "scope",
        "non_goals",
        "stage",
        "risk",
        "priority",
        "owner_user_id",
        "epic_id",
        "user_story_id",
        "readiness",
        "acceptance_criteria",
        "links",
        "required_labels",
        # Declared in V2.1 and inert until V2.3; **live from V2.4**, when all five
        # delivery modes started working (ADR 0033 §1).
        "source",
        "repository_id",
        "base_branch",
        "delivery",
        "target_branch",
        "existing_pr_ref",
        "required_secrets",
        "assigned_runner_id",
        # V2-P1 (ADR 0040 §1, ADR 0042 §5). Three of the four are in
        # `AGENT_FORBIDDEN_FIELDS`: unblocking a card and reordering the queue are both
        # human acts, and an agent doing either to its own card would bypass a rule
        # rather than exercise a permission. `blocking_message` is free text nobody acts
        # on programmatically, so an agent explaining why it is stuck is allowed.
        "is_blocked",
        "blocking_reason",
        "blocking_message",
        "rank",
        # V2.5 (ADR 0034 §5). Editable so a card filed under the wrong kind can be
        # corrected, but **only until it has been run**: `_require_kind_unlocked` below
        # refuses once any `task_runs` row exists, because a clarification card that
        # became an implementation card after the fact would carry a specification and a
        # question thread that its kind no longer explains.
        #
        # It is in `AGENT_FORBIDDEN_FIELDS` for a sharper reason: a clarification run
        # able to rewrite its own card's kind would have cleared the secret refusal for
        # the next dispatch.
        "card_kind",
    }
)

# `verification_commands` is deliberately **not** editable here (V2.4, ADR 0033 §3b).
# It has its own endpoint requiring `task.approve`, an action `RUN_TOKEN_SCOPES` never
# contains. Reachable through this patch it would be writable with `task.update`, which
# a run credential *does* hold — and the agent being verified would choose what verifies
# it. Every exit code would stay real and every one would be worthless.
#
# The boundary is the existing token scope, not a check on the principal's type: this
# module's docstring rejects a dependency that inspects who is calling, and it is right
# to.
VERIFICATION_COMMANDS_FIELD = "verification_commands"

# `gates` is deliberately absent above: approval has its own endpoint, its own action
# and its own audit record. A gate reachable through a generic field update would be a
# gate an agent could set with `task.update`.
FORBIDDEN_PATCH_FIELDS = frozenset({"gates", "card_ref", "version", "project_id"})

# The one lane the Done Gate guards. A constant rather than a literal because it is
# named in three places here and a typo would silently disable the gate.
DONE_STAGE = "done"

RISKS = frozenset({"low", "medium", "high", "critical"})
PRIORITIES = frozenset({"low", "normal", "high"})
SOURCES = frozenset({"none", "repo", "existing_branch"})
DELIVERIES = frozenset({"none", "artifact", "branch", "pull_request", "existing_pr"})

# What a card *is* (ADR 0034 §5). Kept next to `SOURCES` and `DELIVERIES` because it is
# the third field of the same kind — a small closed vocabulary the dispatch path reads —
# and deliberately apart from `required_labels`, which decides *which machine* claims
# the card and is free text.
CARD_KIND_IMPLEMENTATION = "implementation"
CARD_KIND_CLARIFICATION = "clarification"
CARD_KIND_DECOMPOSITION = "decomposition"
CARD_KIND_MOCKUP = "mockup"
CARD_KINDS = frozenset(
    {
        CARD_KIND_IMPLEMENTATION,
        CARD_KIND_CLARIFICATION,
        CARD_KIND_DECOMPOSITION,
        CARD_KIND_MOCKUP,
    }
)
# The two that drive a requirement rather than a repository. Both need a requirement to
# work on, carry no secret, and may only deliver inertly.
REQUIREMENT_KINDS = frozenset({CARD_KIND_CLARIFICATION, CARD_KIND_DECOMPOSITION})
# Deliveries a non-implementation card may declare. `branch`, `pull_request` and
# `existing_pr` are absent because none of these kinds produces a code change; a card
# that declared one would fail at delivery having already spent a whole run.
INERT_DELIVERIES = frozenset({"none", "artifact"})

# Leaves room in the 4096-byte context pack for its mandatory title, three CLI
# instructions, headings and the explicit omission notice. Count the rendered UTF-8
# form, not JSON storage bytes: this is the representation the daemon writes.
MAX_ACCEPTANCE_CRITERIA_CONTEXT_BYTES = 2300


def _task_snapshot(task: Task) -> dict[str, Any]:
    """The persisted card shape returned with an optimistic-lock conflict."""
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "card_ref": task.card_ref,
        "title": task.title,
        "description": task.description,
        "objective": task.objective,
        "scope": task.scope,
        "non_goals": task.non_goals,
        "stage": task.stage,
        "risk": task.risk,
        "priority": task.priority,
        "owner_user_id": str(task.owner_user_id) if task.owner_user_id else None,
        "epic_id": str(task.epic_id) if task.epic_id else None,
        "user_story_id": str(task.user_story_id) if task.user_story_id else None,
        "readiness": task.readiness or {},
        "gates": task.gates or {},
        "acceptance_criteria": task.acceptance_criteria or [],
        "links": task.links or {},
        "required_labels": task.required_labels or [],
        "version": task.version,
        "source": task.source,
        "repository_id": str(task.repository_id) if task.repository_id else None,
        "base_branch": task.base_branch,
        "delivery": task.delivery,
        "target_branch": task.target_branch,
        "existing_pr_ref": task.existing_pr_ref,
        "required_secrets": task.required_secrets or [],
        "assigned_runner_id": str(task.assigned_runner_id) if task.assigned_runner_id else None,
        "requirement_id": str(task.requirement_id) if task.requirement_id else None,
        "proposal_id": str(task.proposal_id) if task.proposal_id else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


@dataclass(slots=True)
class WriteResult:
    """A card plus whatever the platform wants to say without refusing.

    Warnings are a first-class part of the response rather than a log line: the
    Definition of Ready reports here, and a report nobody surfaces is the same as no
    report at all.
    """

    task: Task
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _require_stage(stage: str) -> str:
    if stage not in STAGES:
        raise ApiError(
            "TASK_STAGE_INVALID",
            "Unknown lane",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return stage


def _require_choice(value: str, allowed: frozenset[str], code: str, message: str) -> str:
    if value not in allowed:
        raise ApiError(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


class TaskService:
    """Board rules. **Settings arrive from the caller**, they are not read here.

    The Done Gate is bound to `CLIORA_AGENT_RUNS_ENABLED`, and a service that resolved
    that itself through ``get_settings()`` would not see a dependency override — so the
    gate would be silently off in every test that turns the flag on through FastAPI, and
    the suite would go green while measuring nothing. `plan/20/08` §3 item 5 recorded
    this exact trap for `secret_envelope`; the fix there was an environment variable
    because that module is reached outside a request, and the fix here is simpler
    because this one always is: take it as a parameter.
    """

    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = TaskRepository(session)
        self._audit = AuditService(session)
        self._activity = ActivityService(session)
        self._process = ProcessService(session)

    # --- reads ------------------------------------------------------------------

    async def process(self, project: Project | None = None) -> EffectiveProcess:
        return await self._process.effective(project=project)

    async def roadmap(
        self, project_id: uuid.UUID
    ) -> tuple[list[Epic], list[UserStory], list[Task]]:
        return (
            await self._repo.epics(project_id),
            await self._repo.stories(project_id),
            await self._repo.tasks(project_id),
        )

    async def require_task(self, task_id: uuid.UUID) -> Task:
        task = await self._repo.get(task_id)
        if task is None:
            raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
        return task

    async def by_ref(self, project_id: uuid.UUID, card_ref: str) -> Task:
        task = await self._repo.get_by_ref(project_id, card_ref)
        if task is None:
            raise ApiError("TASK_NOT_FOUND", "Task not found", status.HTTP_404_NOT_FOUND)
        return task

    async def blocking_refs(self, task_id: uuid.UUID) -> list[str]:
        return await self._repo.unfinished_dependencies(task_id)

    async def dependencies(self, task_id: uuid.UUID) -> list[Task]:
        return await self._repo.dependencies(task_id)

    async def refresh(self, task: Task) -> Task:
        """Reload the row before serialising it.

        `tasks.updated_at` carries `onupdate=func.now()`, so any flush that touched the
        row leaves that column expired — and reading an expired column is a SELECT,
        which asyncpg cannot issue from inside a plain attribute access. Every write
        path calls this before building its DTO rather than each one remembering which
        of its columns the database generated.
        """
        await self._session.refresh(task)
        return task

    # --- creation ---------------------------------------------------------------

    def _require_open(self, project: Project) -> None:
        if project.status == "archived":
            raise ApiError(
                "PROJECT_ARCHIVED",
                "This project is archived",
                status.HTTP_409_CONFLICT,
            )

    async def create_epic(
        self, *, project: Project, actor_id: uuid.UUID, title: str, description: str | None
    ) -> Epic:
        self._require_open(project)
        card_ref = await self._repo.allocate_card_ref(project.id, "EPIC")
        epic = Epic(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=card_ref,
            title=title,
            description=description,
            created_by=actor_id,
        )
        self._repo.add(epic)
        await self._session.flush()
        await self._record(
            project_id=project.id,
            actor_id=actor_id,
            audit_action=audit_actions.TASK_CREATE,
            kind=EPIC_CREATED,
            payload={"card_ref": card_ref, "kind": "epic", "title": title},
        )
        return epic

    async def create_story(
        self,
        *,
        project: Project,
        actor_id: uuid.UUID,
        title: str,
        narrative: str | None,
        epic_id: uuid.UUID | None,
    ) -> UserStory:
        self._require_open(project)
        if epic_id is not None:
            await self._require_epic(project, epic_id)
        card_ref = await self._repo.allocate_card_ref(project.id, "US")
        story = UserStory(
            id=uuid.uuid4(),
            project_id=project.id,
            epic_id=epic_id,
            card_ref=card_ref,
            title=title,
            narrative=narrative,
            created_by=actor_id,
        )
        self._repo.add(story)
        await self._session.flush()
        await self._record(
            project_id=project.id,
            actor_id=actor_id,
            audit_action=audit_actions.TASK_CREATE,
            kind=USER_STORY_CREATED,
            payload={"card_ref": card_ref, "kind": "user_story", "title": title},
        )
        return story

    async def update_epic(
        self, *, epic_id: uuid.UUID, actor_id: uuid.UUID, changes: dict[str, Any]
    ) -> Epic:
        epic = await self._repo.get_epic(epic_id)
        if epic is None:
            raise ApiError("TASK_NOT_FOUND", "Epic not found", status.HTTP_404_NOT_FOUND)
        project = await self._repo.project(epic.project_id)
        assert project is not None
        self._require_open(project)
        for field_name in ("title", "description", "order_index", "status"):
            if field_name in changes:
                setattr(epic, field_name, changes[field_name])
        await self._session.flush()
        await self._session.refresh(epic)
        await self._record(
            project_id=epic.project_id,
            actor_id=actor_id,
            audit_action=audit_actions.TASK_UPDATE,
            kind=TASK_UPDATED,
            payload={"card_ref": epic.card_ref, "kind": "epic", "fields": sorted(changes)},
        )
        return epic

    async def update_story(
        self, *, story_id: uuid.UUID, actor_id: uuid.UUID, changes: dict[str, Any]
    ) -> UserStory:
        story = await self._repo.get_story(story_id)
        if story is None:
            raise ApiError("TASK_NOT_FOUND", "User story not found", status.HTTP_404_NOT_FOUND)
        project = await self._repo.project(story.project_id)
        assert project is not None
        self._require_open(project)
        if "epic_id" in changes and changes["epic_id"] is not None:
            await self._require_epic(project, changes["epic_id"])
        for field_name in ("title", "narrative", "epic_id", "order_index", "status"):
            if field_name in changes:
                setattr(story, field_name, changes[field_name])
        await self._session.flush()
        await self._session.refresh(story)
        await self._record(
            project_id=story.project_id,
            actor_id=actor_id,
            audit_action=audit_actions.TASK_UPDATE,
            kind=TASK_UPDATED,
            payload={
                "card_ref": story.card_ref,
                "kind": "user_story",
                "fields": sorted(changes),
            },
        )
        return story

    async def create_task(
        self, *, project: Project, actor_id: uuid.UUID, fields: dict[str, Any]
    ) -> WriteResult:
        self._require_open(project)
        payload = dict(fields)
        stage = _require_stage(str(payload.pop("stage", "backlog")))
        if stage in DEPENDENCY_GATED_STAGES and stage != "ready":
            # A brand-new card has no dependencies, so only `ready` is a meaningful
            # starting lane beyond `backlog`; anything further is a card claiming
            # progress that has not happened.
            raise ApiError(
                "TASK_STAGE_INVALID",
                "A new card starts in backlog, blocked or ready",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        epic_id = payload.pop("epic_id", None)
        story_id = payload.pop("user_story_id", None)
        if epic_id is not None:
            await self._require_epic(project, epic_id)
        if story_id is not None:
            await self._require_story(project, story_id)
        requirement_id = payload.pop("requirement_id", None)
        kind = str(payload.get("card_kind") or CARD_KIND_IMPLEMENTATION)
        payload["card_kind"] = kind
        if requirement_id is not None:
            await self._require_requirement(project, requirement_id)
        elif kind in REQUIREMENT_KINDS:
            # **At create, not only at dispatch.** `RunService` refuses the same thing,
            # and keeping both is deliberate: the dispatch check covers a card whose kind
            # was corrected afterwards, and this one stops a card existing that can only
            # ever be refused. A card nobody can dispatch is worse than an error, because
            # it looks like progress.
            raise ApiError(
                "TASK_KIND_NEEDS_REQUIREMENT",
                f"A `{kind}` card must name the requirement it works on",
                status.HTTP_409_CONFLICT,
                details={"card_kind": kind},
            )

        card_ref = await self._repo.allocate_card_ref(project.id, "TASK")
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=card_ref,
            stage=stage,
            epic_id=epic_id,
            user_story_id=story_id,
            requirement_id=requirement_id,
            rank=await self._rank_for_new_card(project.id),
            created_by=actor_id,
            **self._validated(payload),
        )
        self._repo.add(task)
        await self._session.flush()
        warnings = await self._readiness_warnings(task)
        await self._record(
            project_id=project.id,
            actor_id=actor_id,
            task_id=task.id,
            audit_action=audit_actions.TASK_CREATE,
            kind=TASK_CREATED,
            payload={"card_ref": card_ref, "kind": "task", "title": task.title, "stage": stage},
        )
        return WriteResult(task=task, warnings=warnings)

    async def _rank_for_new_card(self, project_id: uuid.UUID) -> str:
        """A new card goes to the **top** of its project (V2-P1, ADR 0042 §5).

        Top rather than bottom, because that is where a new card already appeared: the
        V1 board is `ORDER BY updated_at DESC` and the `0043` backfill assigned ranks in
        that same order, so the newest card holds the smallest rank. Sending new cards to
        the bottom would put them behind a two-hundred-card backlog on the first screen
        after the upgrade.

        **Two concurrent creates can produce the same rank.** There is no unique
        constraint on the column and this is deliberate: the collision costs a tie broken
        by the secondary sort key, while a constraint would cost a retry loop on the
        create path. The background rebalance separates them the next time it runs.
        """
        lowest = (
            await self._session.execute(
                select(func.min(Task.rank)).where(Task.project_id == project_id)
            )
        ).scalar_one_or_none()
        return rank_between(None, lowest) if lowest else INITIAL_RANK

    # --- update -----------------------------------------------------------------

    async def update_task(
        self,
        *,
        task: Task,
        actor_id: uuid.UUID | None,
        actor_kind: str,
        expected_version: int,
        changes: dict[str, Any],
        force: bool = False,
        force_reason: str | None = None,
        may_force: bool = False,
    ) -> WriteResult:
        """Apply a patch under the optimistic lock.

        The order matters: rules are checked **before** the conditional `UPDATE`, so a
        refusal never leaves half a change behind, and the version check is the write
        itself rather than a read followed by a write.
        """
        project = await self._repo.project(task.project_id)
        assert project is not None
        self._require_open(project)

        forbidden = sorted(FORBIDDEN_PATCH_FIELDS & changes.keys())
        if forbidden:
            raise ApiError(
                "FORBIDDEN_FIELD",
                f"These fields cannot be set this way: {', '.join(forbidden)}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        unknown = sorted(set(changes) - EDITABLE_FIELDS)
        if unknown:
            raise ApiError(
                "FORBIDDEN_FIELD",
                f"Unknown fields: {', '.join(unknown)}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        values = self._validated(changes)
        if "card_kind" in values and values["card_kind"] != task.card_kind:
            await self._require_kind_unlocked(task)
        stage_change: str | None = None
        forced = False
        if "stage" in changes:
            stage = _require_stage(str(changes["stage"]))
            if stage != task.stage:
                await self._check_dependencies_for(task, stage)
                if stage == DONE_STAGE:
                    forced = await self._check_done_gate(
                        task,
                        project,
                        force=force,
                        force_reason=force_reason,
                        may_force=may_force,
                        actor_id=actor_id,
                    )
                    if forced:
                        values["force_done_reason"] = (force_reason or "").strip()[:2000]
                        values["force_done_by"] = actor_id
                        values["force_done_at"] = now_utc()
                elif task.force_done_at is not None:
                    # Leaving `done` clears the mark, and that is **the only way it is
                    # cleared**. There is no endpoint that removes these three columns
                    # on their own: a record that can be erased by itself is not a
                    # record (ADR 0033 §5).
                    values["force_done_reason"] = None
                    values["force_done_by"] = None
                    values["force_done_at"] = None
                stage_change = stage
            values["stage"] = stage
        if "epic_id" in changes and changes["epic_id"] is not None:
            await self._require_epic(project, changes["epic_id"])
        if "user_story_id" in changes and changes["user_story_id"] is not None:
            await self._require_story(project, changes["user_story_id"])

        result = await self._session.execute(
            update(Task)
            .where(Task.id == task.id, Task.version == expected_version)
            .values(**values, version=Task.version + 1)
        )
        if result.rowcount == 0:
            # The card moved under us. Return its current state so the caller can
            # re-render without another round trip — a board that only says "conflict"
            # leaves the user staring at a card they know is wrong.
            fresh = await self._reload(task.id)
            raise ApiError(
                "TASK_VERSION_CONFLICT",
                "This card was changed by someone else",
                status.HTTP_409_CONFLICT,
                details={
                    # Compatibility keys for existing clients plus the complete
                    # current persisted card, so a board can re-render without a
                    # follow-up GET (FR-TASK-003.AC-02).
                    "card_ref": fresh.card_ref,
                    "version": fresh.version,
                    "current": _task_snapshot(fresh),
                },
            )
        await self._session.refresh(task)

        payload: dict[str, Any] = {"card_ref": task.card_ref, "fields": sorted(changes)}
        if stage_change is not None:
            payload["to"] = stage_change
        if forced:
            # A second, separate row. The stage change says the card moved; this says
            # the completion criteria were skipped and why — and it is the row the
            # third cross-project metric counts.
            await self._activity.record(
                TASK_FORCED_DONE,
                project_id=task.project_id,
                task_id=task.id,
                actor_user_id=actor_id,
                payload={
                    "card_ref": task.card_ref,
                    "reason": (force_reason or "").strip()[:2000],
                },
            )
            await self._audit.record(
                audit_actions.TASK_FORCE_DONE,
                user_id=actor_id,
                metadata={
                    "task_id": str(task.id),
                    "card_ref": task.card_ref,
                    "reason": (force_reason or "").strip()[:2000],
                },
            )
        await self._record(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_kind=actor_kind,
            task_id=task.id,
            audit_action=audit_actions.TASK_UPDATE,
            kind=TASK_STAGE_CHANGED if stage_change else TASK_UPDATED,
            payload=payload,
        )
        return WriteResult(task=task, warnings=await self._readiness_warnings(task))

    async def _check_done_gate(
        self,
        task: Task,
        project: Project,
        *,
        force: bool,
        force_reason: str | None,
        may_force: bool,
        actor_id: uuid.UUID | None,
    ) -> bool:
        """The board's second hard refusal, and the one exit around it.

        Returns whether the move was forced. The gate is evaluated **even when forcing**
        — an exit that skips the evaluation cannot record what it skipped, and the whole
        value of this exit is that every use of it is visible (ADR 0033 §5).
        """
        result = await DoneGateService(self._session, settings=self._settings).evaluate(
            task, project
        )
        if result.satisfied:
            return False
        if not force:
            raise ApiError(
                "TASK_DONE_GATE_UNMET",
                f"這張卡還缺 {len(result.missing)} 項完成證據",
                status.HTTP_409_CONFLICT,
                details={
                    # Every missing item, not the first. The action a person takes for a
                    # missing summary and a missing report are different, and one
                    # sentence would send half the readers to the wrong page.
                    "missing": [{"key": m.key, "text": m.text} for m in result.missing]
                },
            )
        if not may_force:
            raise ApiError(
                "FORBIDDEN",
                "Forcing a card into done requires the task.force_done action",
                status.HTTP_403_FORBIDDEN,
            )
        if not (force_reason or "").strip():
            raise ApiError(
                "TASK_FORCE_REASON_REQUIRED",
                "強制推進必須填寫理由，而它會永久顯示在這張卡上",
                status.HTTP_400_BAD_REQUEST,
            )
        return True

    async def _check_dependencies_for(self, task: Task, stage: str) -> None:
        """The one hard refusal in V2.1 (FR-TASK-002.AC-02).

        `blocked` is not in the gated set on purpose: moving a card there is how a
        person *says* it is blocked, and refusing that would be refusing the truth.
        """
        if stage not in DEPENDENCY_GATED_STAGES:
            return
        blocking = await self._repo.unfinished_dependencies(task.id)
        if blocking:
            raise ApiError(
                "TASK_DEPENDENCY_UNSATISFIED",
                f"{', '.join(blocking)} must be done first",
                status.HTTP_409_CONFLICT,
                details={"blocking_refs": blocking},
            )

    # --- gates ------------------------------------------------------------------

    async def approve_gate(self, *, task: Task, gate_key: str, actor: Any, approve: bool) -> Task:
        """Tick or untick one review gate.

        Two refusals, and they are different: a gate the process does not define is a
        404, while one that is derived-disabled is a 409 — the first is a typo, the
        second is a state of the deployment (ADR 0028 sec 8).

        Un-approval exists deliberately. A tick that can never be undone is a tick
        nobody dares to make.
        """
        process = await self._process.effective()
        gate = process.gate(gate_key)
        if gate is None:
            raise ApiError("GATE_UNKNOWN", "Unknown review gate", status.HTTP_404_NOT_FOUND)
        if not gate.enabled:
            raise ApiError(
                "GATE_DISABLED",
                "This gate is unavailable in this deployment",
                status.HTTP_409_CONFLICT,
                details={"reason": gate.disabled_reason},
            )
        if gate.requires_human and getattr(actor, "id", None) is None:
            # Belt and braces: an agent principal cannot reach this route at all
            # (`services/agent_auth.py`), so this is the second line, not the first.
            raise ApiError(
                "GATE_REQUIRES_HUMAN_ACTOR",
                "A review gate must be approved by a person",
                status.HTTP_403_FORBIDDEN,
            )

        gates = dict(task.gates or {})
        if approve:
            from app.clock import now_utc

            gates[gate_key] = {
                "approved_by": str(actor.id),
                "approved_at": now_utc().isoformat(),
            }
        else:
            gates.pop(gate_key, None)
        task.gates = gates
        task.version += 1
        await self._session.flush()
        await self._record(
            project_id=task.project_id,
            actor_id=actor.id,
            task_id=task.id,
            audit_action=audit_actions.TASK_GATE_APPROVE,
            kind=TASK_GATE_APPROVED,
            payload={"card_ref": task.card_ref, "gate": gate_key, "approved": approve},
        )
        return task

    # --- ordering (V2-P1, ADR 0042 sec 5) ---------------------------------------

    async def reorder(
        self,
        *,
        task: Task,
        actor_id: uuid.UUID,
        expected_version: int,
        previous_task_id: uuid.UUID | None,
        next_task_id: uuid.UUID | None,
        stage: str | None = None,
    ) -> Task:
        """Put this card between two named neighbours. **One `UPDATE tasks`.**

        The neighbours are **identifiers, not an index**. On a filtered board an index
        does not mean what the server would take it to mean — position 3 of a filtered
        list is not position 3 of the lane — and the defect that produces is a card that
        lands somewhere the person did not point at.

        `RANK_NEIGHBOR_STALE` is raised when the pair the caller described no longer
        exists: a neighbour was deleted, moved to another project, or somebody else
        reordered so that the two are no longer in the stated order. **The refusal
        carries the neighbours' current ranks**, so the browser can re-render and retry
        rather than asking the user to work out what happened.

        **No activity row.** `_record` writes both trails, and this deliberately writes
        only the audit one: reordering does not change what a card *says*, and a hundred
        drags would bury the card's real history under its own arrangement. The audit log
        is where "who rearranged the board" belongs.
        """
        if task.version != expected_version:
            fresh = await self.require_task(task.id)
            raise ApiError(
                "TASK_VERSION_CONFLICT",
                "This card was changed by someone else",
                status.HTTP_409_CONFLICT,
                details={
                    "card_ref": fresh.card_ref,
                    "version": fresh.version,
                    "current": _task_snapshot(fresh),
                },
            )
        previous = await self._rank_neighbour(task, previous_task_id)
        following = await self._rank_neighbour(task, next_task_id)
        if previous is not None and following is not None and previous >= following:
            raise ApiError(
                "RANK_NEIGHBOR_STALE",
                "The cards you dropped between are no longer next to each other",
                status.HTTP_409_CONFLICT,
                details={"previous_rank": previous, "next_rank": following},
            )
        try:
            rank = rank_between(previous, following)
        except ValueError as invalid:
            # A stored rank that violates an invariant is a data defect, not a bad
            # request — but it reaches the user as this move failing, so it must say
            # something actionable rather than a 500.
            raise ApiError(
                "RANK_NEIGHBOR_STALE",
                "A neighbouring card's position is not usable; reload the board",
                status.HTTP_409_CONFLICT,
                details={"previous_rank": previous, "next_rank": following},
            ) from invalid

        if stage is not None and stage != task.stage:
            # **Through `update_task`, not by assigning the column.** `task.stage` has one
            # writer and `GATE-DV-SINGLE-DONE-PATH` scans for a second: a card crossing
            # into `done` from a drag must meet the Done Gate's six conditions exactly as
            # it would from the card detail page. So the lane change goes the long way and
            # the rank goes the short way, in one transaction.
            await self.update_task(
                task=task,
                actor_id=actor_id,
                actor_kind="user",
                expected_version=expected_version,
                changes={"stage": stage},
            )
            # `update_task` already advanced the version and recorded both trails.
            task.rank = rank
            await self._session.flush()
            return task

        task.rank = rank
        task.version += 1
        await self._session.flush()
        await self._audit.record(
            audit_actions.TASK_UPDATE,
            user_id=actor_id,
            metadata={
                "task_id": str(task.id),
                "card_ref": task.card_ref,
                "fields": ["rank"],
                "previous_task_id": str(previous_task_id) if previous_task_id else None,
                "next_task_id": str(next_task_id) if next_task_id else None,
            },
        )
        if len(rank) >= INLINE_REBALANCE_THRESHOLD:
            # The safety valve. Past this the strings are long enough that the next
            # insertion at the same spot keeps growing them, so the project is
            # rebalanced inside this request rather than hoping a background pass
            # arrives first. It costs one UPDATE per card and it is rare: reaching 48
            # characters takes roughly 240 consecutive inserts at one position.
            await self.rebalance(project_id=task.project_id)
            await self._session.refresh(task)
        return task

    async def _rank_neighbour(self, task: Task, neighbour_id: uuid.UUID | None) -> str | None:
        """The neighbour's current rank, or None for "this end of the list"."""
        if neighbour_id is None:
            return None
        if neighbour_id == task.id:
            raise ApiError(
                "RANK_NEIGHBOR_STALE",
                "A card cannot be dropped next to itself",
                status.HTTP_409_CONFLICT,
                details={"task_id": str(task.id)},
            )
        neighbour = await self._repo.get(neighbour_id)
        if neighbour is None or neighbour.project_id != task.project_id:
            raise ApiError(
                "RANK_NEIGHBOR_STALE",
                "One of the cards you dropped between is no longer in this project",
                status.HTTP_409_CONFLICT,
                details={"neighbour_task_id": str(neighbour_id)},
            )
        return neighbour.rank

    async def rebalance(self, *, project_id: uuid.UUID) -> int:
        """Space every card in a project evenly, **without changing any relative order**.

        Returns the number of rows written. Idempotent: an already balanced project
        rebalances to the same values, so a second pass writes nothing — which is what
        makes it safe to call from a background job on a schedule.

        `version` is deliberately **not** bumped. A rebalance is the platform tidying its
        own representation; incrementing every card's version would invalidate every open
        editor in the deployment and make a maintenance pass look like two hundred people
        editing at once.
        """
        rows = list(
            (
                await self._session.execute(
                    select(Task.id, Task.rank)
                    .where(Task.project_id == project_id)
                    .order_by(Task.rank, Task.id)
                )
            ).all()
        )
        if not rows:
            return 0
        written = 0
        for (task_id, current), fresh in zip(rows, rebalanced_ranks(len(rows)), strict=True):
            if current == fresh:
                continue
            await self._session.execute(update(Task).where(Task.id == task_id).values(rank=fresh))
            written += 1
        return written

    async def projects_needing_rebalance(self) -> list[uuid.UUID]:
        """Projects holding a rank at or past the background threshold.

        The threshold is on the *longest* rank rather than on a count of cards: length is
        what actually runs out of room, and a project with a thousand evenly spaced cards
        is in better shape than one with ten cards inserted at the same spot forty times.
        """
        rows = (
            await self._session.execute(
                select(Task.project_id)
                .where(func.length(Task.rank) >= REBALANCE_THRESHOLD)
                .group_by(Task.project_id)
            )
        ).scalars()
        return list(rows)

    # --- dependencies -----------------------------------------------------------

    async def add_dependency(
        self, *, task: Task, depends_on_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        blocker = await self.require_task(depends_on_id)
        if blocker.project_id != task.project_id:
            raise ApiError(
                "TASK_NOT_FOUND",
                "Task not found",
                status.HTTP_404_NOT_FOUND,
            )
        if blocker.id == task.id:
            raise ApiError(
                "TASK_DEPENDENCY_CYCLE",
                "A card cannot depend on itself",
                status.HTTP_409_CONFLICT,
                details={"path": [task.card_ref, task.card_ref]},
            )
        # Would the new edge close a loop? It does if the blocker already reaches this
        # card. Checked before the insert so the refusal can name the path it found.
        path = await self._repo.reaches(blocker.id, task.id)
        if path:
            raise ApiError(
                "TASK_DEPENDENCY_CYCLE",
                "That would create a circular dependency",
                status.HTTP_409_CONFLICT,
                details={"path": [task.card_ref, *path]},
            )
        await self._repo.add_dependency(task_id=task.id, depends_on=blocker.id, actor_id=actor_id)
        await self._session.flush()
        await self._record(
            project_id=task.project_id,
            actor_id=actor_id,
            task_id=task.id,
            audit_action=audit_actions.TASK_UPDATE,
            kind=TASK_UPDATED,
            payload={"card_ref": task.card_ref, "depends_on": blocker.card_ref},
        )

    async def remove_dependency(
        self, *, task: Task, depends_on_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        removed = await self._repo.remove_dependency(task_id=task.id, depends_on=depends_on_id)
        if removed == 0:
            raise ApiError("TASK_NOT_FOUND", "Dependency not found", status.HTTP_404_NOT_FOUND)
        await self._record(
            project_id=task.project_id,
            actor_id=actor_id,
            task_id=task.id,
            audit_action=audit_actions.TASK_UPDATE,
            kind=TASK_UPDATED,
            payload={"card_ref": task.card_ref, "dependency_removed": str(depends_on_id)},
        )

    # --- helpers ----------------------------------------------------------------

    def _validated(self, changes: dict[str, Any]) -> dict[str, Any]:
        values = dict(changes)
        if "acceptance_criteria" in values:
            criteria = values["acceptance_criteria"] or []
            if not isinstance(criteria, list) or any(
                not isinstance(item, dict) for item in criteria
            ):
                raise ApiError(
                    "TASK_ACCEPTANCE_CRITERIA_INVALID",
                    "Acceptance criteria must be a list of objects",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            # Closed to four values by migration 0036. Before that this was a free
            # string, so the Done Gate's "every criterion has a result" would have been
            # satisfied by any text at all — the closure and the gate are one change
            # (ADR 0033 §5).
            for item in criteria:
                result = item.get("result")
                if result is not None and result not in CRITERION_RESULTS:
                    raise ApiError(
                        "TASK_ACCEPTANCE_CRITERIA_INVALID",
                        "Unknown acceptance criterion result: " + str(result),
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        details={"allowed": sorted(CRITERION_RESULTS)},
                    )
            rendered = "".join(
                f"- [{item.get('result') or '未驗'}] {item.get('text', '')}\n" for item in criteria
            )
            rendered_bytes = len(rendered.encode())
            if rendered_bytes > MAX_ACCEPTANCE_CRITERIA_CONTEXT_BYTES:
                raise ApiError(
                    "TASK_CONTEXT_TOO_LARGE",
                    "Acceptance criteria do not fit the task context budget",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details={
                        "acceptance_criteria_bytes": rendered_bytes,
                        "maximum_bytes": MAX_ACCEPTANCE_CRITERIA_CONTEXT_BYTES,
                    },
                )
        if "risk" in values:
            _require_choice(str(values["risk"]), RISKS, "TASK_STAGE_INVALID", "Unknown risk")
        if "priority" in values:
            _require_choice(
                str(values["priority"]), PRIORITIES, "TASK_STAGE_INVALID", "Unknown priority"
            )
        if "source" in values:
            _require_choice(str(values["source"]), SOURCES, "TASK_STAGE_INVALID", "Unknown source")
        if "delivery" in values:
            _require_choice(
                str(values["delivery"]), DELIVERIES, "TASK_STAGE_INVALID", "Unknown delivery"
            )
        if "card_kind" in values:
            _require_choice(
                str(values["card_kind"]), CARD_KINDS, "TASK_STAGE_INVALID", "Unknown card kind"
            )
        values.pop("stage", None)
        return values

    async def _require_requirement(self, project: Project, requirement_id: uuid.UUID) -> None:
        """The requirement must exist **and be this project's**.

        The project check is the whole reason this is a method rather than an FK. The FK
        says the row exists; it does not say the caller may point one project's card at
        another project's requirement — and a clarification run reads its requirement
        through the run credential, so the link *is* the read authorization.

        A 404 rather than a 403 for a foreign requirement, because "not in this project"
        and "does not exist" are the same fact from where the caller stands, and the
        difference between the two answers confirms the existence of a row they cannot see.
        """
        requirement = await self._session.get(Requirement, requirement_id)
        if requirement is None or requirement.project_id != project.id:
            raise ApiError(
                "REQUIREMENT_NOT_FOUND",
                "Requirement not found",
                status.HTTP_404_NOT_FOUND,
                details={"requirement_id": str(requirement_id)},
            )

    async def _require_kind_unlocked(self, task: Task) -> None:
        """A card's kind is fixed once it has ever been run (ADR 0034 §5).

        **"Ever", not "currently".** A clarification card that finished and then became
        an implementation card would still carry its specification versions, its
        question thread and its run log — and an auditor reading it later would see an
        implementation card that inexplicably produced a specification. History cannot
        be edited, so the field that explains it cannot be either.
        """
        existing = await self._session.scalar(
            select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task.id)
        )
        if existing:
            raise ApiError(
                "TASK_KIND_LOCKED",
                "這張卡已經執行過，卡片種類不能再改；要換種類請建立新卡",
                status.HTTP_409_CONFLICT,
                details={"card_kind": task.card_kind, "runs": int(existing)},
            )

    async def _readiness_warnings(self, task: Task) -> list[dict[str, Any]]:
        """What the Definition of Ready would say, without refusing anything.

        Returned on every write rather than only on the move into `ready`: a card is
        made ready over several edits, and telling someone only at the last one is
        telling them too late.
        """
        process = await self._process.effective()
        readiness = task.readiness or {}
        missing = [key for key in process.readiness_keys() if not readiness.get(key)]
        if not missing:
            return []
        return [{"code": "READINESS_INCOMPLETE", "missing": missing}]

    async def _require_epic(self, project: Project, epic_id: uuid.UUID) -> Epic:
        epic = await self._repo.get_epic(epic_id)
        if epic is None or epic.project_id != project.id:
            raise ApiError("TASK_NOT_FOUND", "Epic not found", status.HTTP_404_NOT_FOUND)
        return epic

    async def _require_story(self, project: Project, story_id: uuid.UUID) -> UserStory:
        story = await self._repo.get_story(story_id)
        if story is None or story.project_id != project.id:
            raise ApiError("TASK_NOT_FOUND", "User story not found", status.HTTP_404_NOT_FOUND)
        return story

    async def _reload(self, task_id: uuid.UUID) -> Task:
        self._session.expire_all()
        fresh = await self._repo.get(task_id)
        assert fresh is not None
        return fresh

    async def _record(
        self,
        *,
        project_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        audit_action: str,
        kind: str,
        payload: dict[str, Any],
        task_id: uuid.UUID | None = None,
        actor_kind: str = "user",
    ) -> None:
        """Both trails, on every write (the shape `services/projects.py` established).

        `actor_kind` is what keeps an agent's write from reading as a person's: the
        audit row carries no `user_id` for one, and the timeline says which kind it
        was (ADR 0028 sec 3).
        """
        metadata = dict(payload)
        if task_id is not None:
            metadata["task_id"] = str(task_id)
        if actor_kind != "user":
            metadata["actor_kind"] = actor_kind
        await self._audit.record(
            audit_action,
            user_id=actor_id if actor_kind == "user" else None,
            metadata=metadata,
        )
        await self._activity.record(
            kind,
            project_id=project_id,
            actor_user_id=actor_id if actor_kind == "user" else None,
            actor_kind=actor_kind,
            task_id=task_id,
            payload=payload,
        )
