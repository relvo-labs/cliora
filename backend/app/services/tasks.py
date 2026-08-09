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
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import Epic, Project, Task, UserStory
from app.repositories.tasks import BoardCard, TaskRepository
from app.services import audit as audit_actions
from app.services.activity import (
    EPIC_CREATED,
    TASK_CREATED,
    TASK_GATE_APPROVED,
    TASK_STAGE_CHANGED,
    TASK_UPDATED,
    USER_STORY_CREATED,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.process import DEPENDENCY_GATED_STAGES, STAGES, EffectiveProcess, ProcessService

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
        # Declared in V2.1, inert until V2.3/V2.4 (ADR 0028 sec 9). Editable now
        # because people state the intent now.
        "source",
        "repository_id",
        "base_branch",
        "delivery",
        "target_branch",
        "existing_pr_ref",
        "required_secrets",
        "assigned_runner_id",
    }
)

# `gates` is deliberately absent above: approval has its own endpoint, its own action
# and its own audit record. A gate reachable through a generic field update would be a
# gate an agent could set with `task.update`.
FORBIDDEN_PATCH_FIELDS = frozenset({"gates", "card_ref", "version", "project_id"})

RISKS = frozenset({"low", "medium", "high", "critical"})
PRIORITIES = frozenset({"low", "normal", "high"})
SOURCES = frozenset({"none", "repo", "existing_branch"})
DELIVERIES = frozenset({"none", "artifact", "branch", "pull_request", "existing_pr"})

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
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TaskRepository(session)
        self._audit = AuditService(session)
        self._activity = ActivityService(session)
        self._process = ProcessService(session)

    # --- reads ------------------------------------------------------------------

    async def process(self) -> EffectiveProcess:
        return await self._process.effective()

    async def board(self, project_id: uuid.UUID) -> list[BoardCard]:
        return await self._repo.board_cards(project_id)

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

        card_ref = await self._repo.allocate_card_ref(project.id, "TASK")
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=card_ref,
            stage=stage,
            epic_id=epic_id,
            user_story_id=story_id,
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

    # --- update -----------------------------------------------------------------

    async def update_task(
        self,
        *,
        task: Task,
        actor_id: uuid.UUID | None,
        actor_kind: str,
        expected_version: int,
        changes: dict[str, Any],
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
        stage_change: str | None = None
        if "stage" in changes:
            stage = _require_stage(str(changes["stage"]))
            if stage != task.stage:
                await self._check_dependencies_for(task, stage)
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
        values.pop("stage", None)
        return values

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
