"""The run queue: dispatch, the atomic claim, the lease, and re-queueing.

This module is the queue half of V2.2 (FR-AGENT-003…008, ADR 0029). It owns three
things that are easy to get subtly wrong, and each is written here rather than spread
across the routes that use it.

**The claim happens at `runner.poll`, not at `run.accept`** (ADR 0029 sec 2). It is one
`UPDATE … WHERE runner_id IS NULL`, and that `WHERE` clause is the *entire* guarantee
that a card cannot be claimed twice. It is deliberately the only place in
`backend/app/` that assigns `runner_id` a value; `GATE-AR-SINGLE-CLAIM` asserts that by
scanning for a second one.

**Nothing here may call `registry.request()`.** The node WebSocket loop resolves its own
responses (`registry.py:276` ← `ws/nodes.py:276`), so awaiting a node reply from inside
a handler that loop invoked is a guaranteed timeout, not a slow path.
`GATE-AR-NO-REQUEST-IN-LOOP` scans this module for it.

**`authorize_workspace` is not imported here, and never should be.** After the
2026-08-10 ruling a run does not use a workspace binding at all: it clones into a
directory the daemon owns. That makes red line 2 apply to exactly one caller group
again, and `GATE-AR-NO-WORKSPACE-IN-RUNS` keeps this module free of the other one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import (
    AgentRunner,
    Project,
    ProjectRepository,
    Task,
    TaskDependency,
    TaskMessage,
    TaskRun,
)
from app.services import audit as audit_actions
from app.services.activity import (
    ACTOR_AGENT,
    ACTOR_SYSTEM,
    ACTOR_USER,
    RUN_DISPATCHED,
    TASK_MESSAGE_POSTED,
    ActivityService,
)
from app.services.audit import AuditService
from app.services.runners import RepositoryService, clone_url
from app.settings import Settings, get_settings

# Terminal for the purposes of "does this card already have a run in flight".
ACTIVE_STATUSES = ("queued", "claimed", "running", "waiting_for_input")
# What the lease sweep reclaims. `waiting_for_input` is **not** here: that run's runner
# is alive and renewing, and a person is the thing being waited on. Its own timer is
# `waiting_since` (ADR 0029 sec 5).
LEASED_STATUSES = ("claimed", "running")

# Declarations the phase cannot honour. Refused at dispatch rather than accepted and
# silently ignored — a declaration the platform ignores is worse than one it refuses
# (plan/18/00-…md D11). `source` is deliberately absent: after the ruling,
# `source: repo` is this phase's main path.
UNSUPPORTED_DELIVERIES = {
    "branch": "V2.3",
    "pull_request": "V2.4",
    "existing_pr": "V2.4",
}


@dataclass(frozen=True, slots=True)
class DispatchResult:
    run: TaskRun
    # "any" | "assigned_offline" | "no_eligible_runner" — the source of three pieces of
    # UI copy that must differ word for word, because a person cannot otherwise tell
    # "I misconfigured something" from "wait a moment" (plan/18/06-…md §2.2).
    waiting_reason: str


@dataclass(frozen=True, slots=True)
class RunOffer:
    """What a claiming runner is handed. Assembled from the run's **snapshot**."""

    run: TaskRun
    task: Task
    repository: ProjectRepository | None

    def spec(self) -> dict[str, Any]:
        source: dict[str, Any] = {"kind": self.run.source_kind or "none"}
        if self.repository is not None:
            source["url"] = clone_url(self.repository)
            source["ref"] = self.run.source_ref or self.repository.default_branch
        return {
            "run_id": str(self.run.id),
            "task_id": str(self.run.task_id),
            "project_id": str(self.run.project_id),
            "card_ref": self.task.card_ref,
            "title": self.task.title,
            "runtime": self.run.runtime,
            "attempt": self.run.attempt,
            "source": source,
            "delivery": self.task.delivery,
        }


class RunService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)
        self._activity = ActivityService(session)

    # --- reads ---------------------------------------------------------------

    async def require(self, run_id: uuid.UUID) -> TaskRun:
        run = await self._session.get(TaskRun, run_id)
        if run is None:
            raise ApiError("NOT_FOUND", "Run not found", status.HTTP_404_NOT_FOUND)
        return run

    async def for_task(self, task_id: uuid.UUID) -> list[TaskRun]:
        return list(
            (
                await self._session.execute(
                    select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.seq.desc())
                )
            ).scalars()
        )

    async def active_for_task(self, task_id: uuid.UUID) -> TaskRun | None:
        return (
            await self._session.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task_id, TaskRun.status.in_(ACTIVE_STATUSES))
                .order_by(TaskRun.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # --- dispatch ------------------------------------------------------------

    async def dispatch(
        self,
        *,
        task: Task,
        project: Project,
        assigned_runner_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> DispatchResult:
        """Queue a card. The order of these checks is fixed, and it is fixed for
        readability of the refusal rather than for correctness (ADR 0029, D13).

        After the ruling the first authorization-shaped refusal a person can hit is
        "this project has no repository registered" — something they fix in Project
        Settings — so the error carries a hint pointing there rather than saying
        "missing configuration".
        """
        # ① can this card be dispatched at all
        if task.stage != "ready":
            raise ApiError(
                "TASK_NOT_READY",
                "Only a card in the ready lane can be dispatched to an agent",
                status.HTTP_409_CONFLICT,
            )
        blocking = await self._unsatisfied_dependencies(task.id)
        if blocking:
            raise ApiError(
                "TASK_DEPENDENCY_UNSATISFIED",
                "These cards must be done first: " + ", ".join(blocking),
                status.HTTP_409_CONFLICT,
            )
        if await self.active_for_task(task.id) is not None:
            raise ApiError(
                "RUN_ALREADY_ACTIVE",
                "This card already has a run in progress",
                status.HTTP_409_CONFLICT,
            )

        # ② declarations this phase cannot honour
        if task.required_secrets:
            raise ApiError(
                "TASK_REQUIRES_SECRETS",
                "Cards that declare required secrets can be dispatched from V2.3",
                status.HTTP_409_CONFLICT,
                details={"phase": "V2.3", "required_secrets": list(task.required_secrets)},
            )
        if task.delivery in UNSUPPORTED_DELIVERIES:
            phase = UNSUPPORTED_DELIVERIES[task.delivery]
            raise ApiError(
                "TASK_DELIVERY_UNSUPPORTED",
                f"Delivery mode '{task.delivery}' takes effect from {phase}",
                status.HTTP_409_CONFLICT,
                details={"phase": phase, "delivery": task.delivery},
            )

        # ③ the project has to know where its code is
        repository: ProjectRepository | None = None
        if task.source != "none":
            repositories = RepositoryService(self._session, settings=self._settings)
            if task.repository_id is not None:
                repository = await repositories.require(project.id, task.repository_id)
            else:
                candidates = await repositories.list_for(project.id)
                repository = candidates[0] if candidates else None
            if repository is None:
                raise ApiError(
                    "PROJECT_NO_REPOSITORY",
                    "This project has no repository registered, so an agent has "
                    "nowhere to fetch the code from",
                    status.HTTP_409_CONFLICT,
                    details={"settings_hint": f"/projects/{project.id}#repositories"},
                )
            if not repositories.host_allowed(repository.host):
                raise ApiError(
                    "REPOSITORY_HOST_NOT_ALLOWED",
                    f"This deployment does not allow repositories on {repository.host}",
                    status.HTTP_409_CONFLICT,
                    details={"host": repository.host},
                )

        # ④ the named runner, if one was named
        waiting_reason = "any"
        if assigned_runner_id is not None:
            runner = await self._session.get(AgentRunner, assigned_runner_id)
            if runner is None:
                raise ApiError("NOT_FOUND", "Agent not found", status.HTTP_404_NOT_FOUND)
            if not runner.enabled:
                raise ApiError(
                    "AGENT_DISABLED",
                    f"Agent '{runner.name}' is disabled",
                    status.HTTP_409_CONFLICT,
                    details={"runner_name": runner.name},
                )
            required_runtime = self._runtime_for(task)
            if required_runtime is not None and required_runtime not in (runner.runtimes or []):
                raise ApiError(
                    "AGENT_RUNTIME_MISMATCH",
                    f"Agent '{runner.name}' does not offer the {required_runtime} runtime",
                    status.HTTP_409_CONFLICT,
                    details={"runner_name": runner.name, "runtime": required_runtime},
                )

        # ⑤ queue it
        seq = await self._next_seq(task.id)
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            seq=seq,
            status="queued",
            attempt=1,
            # Snapshots, all four. A run executes the card as it was at dispatch; the
            # card stays editable and those edits affect the *next* dispatch.
            assigned_runner_id=assigned_runner_id,
            repository_id=repository.id if repository is not None else None,
            source_kind=task.source,
            source_ref=(
                task.base_branch
                if task.source == "existing_branch"
                else (repository.default_branch if repository is not None else None)
            ),
            runtime=self._runtime_for(task),
            created_by=actor_id,
        )
        self._session.add(run)
        await self._session.flush()

        await self._audit.record(
            audit_actions.RUN_DISPATCH,
            user_id=actor_id,
            metadata={
                "run_id": str(run.id),
                "task_id": str(task.id),
                "assigned_runner_id": str(assigned_runner_id) if assigned_runner_id else None,
            },
        )
        await self._activity.record(
            RUN_DISPATCHED,
            project_id=project.id,
            task_id=task.id,
            actor_user_id=actor_id,
            payload={"run_id": str(run.id), "card_ref": task.card_ref, "attempt": 1},
        )
        return DispatchResult(run=run, waiting_reason=waiting_reason)

    async def resolve_waiting_reason(self, run: TaskRun, *, is_online) -> str:  # noqa: ANN001 - predicate
        """Why this run is still queued, as one of three words.

        Computed on the server because it needs the eligibility query, which the
        browser does not have. It is a **hint**, not a gate: a runner may register
        three seconds later, and nothing about the run changes if it does.
        """
        if run.assigned_runner_id is not None:
            runner = await self._session.get(AgentRunner, run.assigned_runner_id)
            if runner is None or not is_online(runner.node_id):
                return "assigned_offline"
            return "any"
        eligible = await self._eligible_runner_count(run, is_online=is_online)
        return "any" if eligible else "no_eligible_runner"

    async def _eligible_runner_count(self, run: TaskRun, *, is_online) -> int:  # noqa: ANN001
        runners = list(
            (
                await self._session.execute(
                    select(AgentRunner).where(AgentRunner.enabled.is_(True))
                )
            ).scalars()
        )
        return sum(
            1
            for runner in runners
            if is_online(runner.node_id)
            and (run.runtime is None or run.runtime in (runner.runtimes or []))
        )

    def _runtime_for(self, task: Task) -> str | None:
        """Which CLI this card needs, or None for "any".

        V2.2 has no per-card runtime field, so this is None today and the eligibility
        query's runtime condition passes for every runner. The indirection exists so
        that adding the field later is one function rather than four call sites.
        """
        return None

    async def _next_seq(self, task_id: uuid.UUID) -> int:
        highest = (
            await self._session.execute(
                select(func.max(TaskRun.seq)).where(TaskRun.task_id == task_id)
            )
        ).scalar()
        return int(highest or 0) + 1

    async def _unsatisfied_dependencies(self, task_id: uuid.UUID) -> list[str]:
        rows = (
            await self._session.execute(
                select(Task.card_ref)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task_id, Task.stage != "done")
                .order_by(Task.card_ref)
            )
        ).scalars()
        return list(rows)

    # --- cancel --------------------------------------------------------------

    async def cancel(self, *, run: TaskRun, actor_id: uuid.UUID) -> TaskRun:
        if run.status not in ACTIVE_STATUSES:
            raise ApiError(
                "RUN_NOT_ACTIVE",
                "This run has already finished",
                status.HTTP_409_CONFLICT,
            )
        # The row is marked here; the node is told separately, because a run that was
        # never claimed has no node to tell. A claimed run's daemon learns from
        # `run.cancel` on its own socket (AR-06/AR-07).
        run.status = "cancelled"
        run.result = "cancelled"
        run.finished_at = now_utc()
        run.logs_expire_at = now_utc() + timedelta(days=14)
        await self._session.flush()
        await self._audit.record(
            audit_actions.RUN_CANCEL,
            user_id=actor_id,
            metadata={"run_id": str(run.id), "task_id": str(run.task_id)},
        )
        return run


class MessageService:
    """A card's conversation: human, agent and system in one thread (FR-AGENT-007).

    The two write paths — a person's session and a run token — reach this through two
    separate dependencies and two separate route functions, and both require the
    **same action** (`task.update`). That is the point of "one channel": it holds in
    the authorization layer and not merely in the URL. What it must never become is a
    single dependency that inspects the principal's type, because that would undo the
    structural separation of `get_current_user` and `get_agent_principal`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._activity = ActivityService(session)

    async def list_for(
        self, task_id: uuid.UUID, *, since: Any | None = None, limit: int = 200
    ) -> list[TaskMessage]:
        query = select(TaskMessage).where(TaskMessage.task_id == task_id)
        if since is not None:
            query = query.where(TaskMessage.created_at > since)
        query = query.order_by(TaskMessage.created_at, TaskMessage.id).limit(limit)
        return list((await self._session.execute(query)).scalars())

    async def post(
        self,
        *,
        task: Task,
        body: str,
        kind: str = "message",
        author_kind: str = ACTOR_USER,
        author_user_id: uuid.UUID | None = None,
        author_runner_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        event_kind: str | None = None,
    ) -> TaskMessage:
        if kind not in {"message", "question", "answer", "event"}:
            raise ApiError("INVALID_ARGUMENT", "Unknown message kind", status.HTTP_400_BAD_REQUEST)
        if not body.strip():
            raise ApiError("INVALID_ARGUMENT", "Message body is empty", status.HTTP_400_BAD_REQUEST)
        message = TaskMessage(
            id=uuid.uuid4(),
            task_id=task.id,
            run_id=run_id,
            author_kind=author_kind,
            author_user_id=author_user_id,
            author_runner_id=author_runner_id,
            body=body,
            kind=kind,
            event_kind=event_kind,
        )
        self._session.add(message)
        await self._session.flush()
        if author_kind in {ACTOR_USER, ACTOR_AGENT}:
            # System events are not recorded on the timeline from here — they already
            # *are* activity, and a second row would double every one of them.
            await self._activity.record(
                TASK_MESSAGE_POSTED,
                project_id=task.project_id,
                task_id=task.id,
                actor_user_id=author_user_id,
                actor_kind=author_kind,
                payload={"card_ref": task.card_ref, "kind": kind},
            )
        return message

    async def post_event(self, *, task: Task, body: str, event_kind: str) -> TaskMessage:
        return await self.post(
            task=task,
            body=body,
            kind="event",
            author_kind=ACTOR_SYSTEM,
            event_kind=event_kind,
        )


async def claim(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    runner_id: uuid.UUID,
    runtime: str | None,
    lease_seconds: int,
) -> bool:
    """The atomic claim. **The only place `runner_id` is assigned a value.**

    Returning False means somebody else got there first — the caller moves to the next
    candidate. The `WHERE runner_id IS NULL AND status = 'queued'` pair is the entire
    guarantee against a double claim, and it holds inside one statement rather than
    across a handshake, so the race window is not narrowed but closed.

    A free function rather than a method so the scan behind `GATE-AR-SINGLE-CLAIM` has
    exactly one thing to find.
    """
    now = now_utc()
    result = await session.execute(
        update(TaskRun)
        .where(
            TaskRun.id == run_id,
            TaskRun.runner_id.is_(None),
            TaskRun.status == "queued",
        )
        .values(
            runner_id=runner_id,
            status="claimed",
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            runtime=runtime,
        )
    )
    return bool(result.rowcount)
