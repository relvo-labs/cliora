"""Phase A: building one page of :class:`WorkRow` in a bounded number of queries.

The budget is **four queries and it does not grow with the board** (plan/26/03 §3):

    1  cards + owner name
    1  blocking counts            (existing `TaskRepository.blocking_counts`)
    1  blocking refs              (only for the cards that have a blocker)
    1  runners                    (phase B, only when something is queued)

plus the two lateral-shaped projections `active_runs()`, `latest_run_statuses()` and
`latest_verification_results()` — which is where the count above is honest about being a
budget for the *read model's own* queries rather than a promise about the whole request.
`GATE-PX-…` does not police this; the measurement in `scripts/px/measure_attention.py`
does, and it is the number `plan/26/12` §5 records.

**The effective process is resolved once per project, never once per card.** It is
per-project data (a project may switch readiness items and gates off), so the naive
version is one process read *and one integration lookup* per card — 400 round trips on a
200-card board. That is the N+1 `plan/26/03` §1.B names.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import AgentRunner, Project, Task, User
from app.repositories.tasks import ActiveRunProjection, TaskRepository
from app.services.process import EffectiveProcess, ProcessService
from app.services.work.attention import RuntimeSignals, resolve_runtime_signals
from app.services.work.projection import (
    WorkRow,
    is_stale,
    missing_readiness,
    project_execution,
    project_human_decision,
    project_is_blocked,
    project_lifecycle,
    project_readiness,
)


class WorkRowReader:
    """Reads the cards of one project as the read model sees them.

    Wave 0 runs before migration ``0043``, so there is no ``tasks.is_blocked`` column to
    read: :func:`project_is_blocked` is given ``None`` and answers from the stage alone.
    That is not a temporary shim — D102 makes ``stage='blocked'`` win over the column
    permanently, so the wave-2 caller passes the column and gets the same answer for
    every card the platform's three legacy writers touched.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TaskRepository(session)

    async def for_project(
        self,
        project: Project,
        *,
        is_online: Callable[[uuid.UUID], bool] | None = None,
    ) -> tuple[list[WorkRow], RuntimeSignals | None]:
        """Every card in the project, plus phase B's answer.

        ``is_online`` is optional and its absence is meaningful: a caller with no node
        registry (a background job, a migration, a test without an app) gets ``None``
        back, and :func:`derive_attention` then omits levels 5 and 6 rather than
        reporting them as absent.
        """
        process = await ProcessService(self._session).effective(project=project)
        rows = (
            await self._session.execute(
                select(Task, User.display_name)
                .join(User, User.id == Task.owner_user_id, isouter=True)
                .where(Task.project_id == project.id)
                .order_by(Task.updated_at.desc(), Task.id.desc())
            )
        ).all()
        tasks = {task.id: task for task, _ in rows}
        blocking = await self._repository.blocking_counts(project.id)
        refs = await self._repository.blocking_refs([task_id for task_id in blocking])
        active = await self._repository.active_runs(project.id)
        latest_runs = await self._repository.latest_run_statuses(project.id)
        latest_reports = await self._repository.latest_verification_results(project.id)

        over_wip = self._over_wip_stages(
            Counter(task.stage for task in tasks.values()), process=process
        )
        readiness_keys = process.readiness_keys()
        gate_keys = [gate.key for gate in process.gates if gate.enabled]
        now = now_utc()

        work_rows: list[WorkRow] = []
        for task, owner_name in rows:
            lifecycle = project_lifecycle(task.stage)
            missing = missing_readiness(task.readiness, readiness_keys)
            run = active.get(task.id)
            gates = task.gates or {}
            work_rows.append(
                WorkRow(
                    task_id=task.id,
                    project_id=task.project_id,
                    card_ref=task.card_ref,
                    title=task.title,
                    card_kind=task.card_kind,
                    stage=task.stage,
                    lifecycle=lifecycle,
                    is_blocked=project_is_blocked(task.stage, getattr(task, "is_blocked", None)),
                    readiness=project_readiness(missing, len(readiness_keys)),
                    readiness_missing=missing,
                    blocking_reason=getattr(task, "blocking_reason", None),
                    blocking_message=getattr(task, "blocking_message", None),
                    blocking_count=blocking.get(task.id, 0),
                    blocking_refs=refs.get(task.id, ()),
                    execution=project_execution(run, latest_runs.get(task.id)),
                    human_decision=project_human_decision(gates, required_gate_keys=gate_keys),
                    gates_approved_count=sum(1 for value in gates.values() if value),
                    gates_required_count=len(gate_keys),
                    active_run=run,
                    latest_run_status=latest_runs.get(task.id),
                    latest_verification_result=latest_reports.get(task.id),
                    owner_user_id=task.owner_user_id,
                    owner_name=owner_name,
                    risk=task.risk,
                    priority=task.priority,
                    delivery=task.delivery,
                    labels=tuple(task.required_labels or ()),
                    requirement_id=task.requirement_id,
                    epic_id=task.epic_id,
                    user_story_id=task.user_story_id,
                    conversation_seq=task.conversation_seq,
                    open_question_count=task.open_question_count,
                    waiting_for_actor=task.waiting_for_actor,
                    over_wip=task.stage in over_wip,
                    stale=is_stale(lifecycle, task.updated_at, now=now),
                    rank=getattr(task, "rank", None),
                    version=task.version,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )

        runtime = None
        if is_online is not None:
            runtime = await self.runtime_signals(
                [run for run in active.values() if run.status == "queued"],
                tasks,
                is_online=is_online,
            )
        return work_rows, runtime

    async def runtime_signals(
        self,
        queued: Sequence[ActiveRunProjection],
        tasks: dict[uuid.UUID, Task],
        *,
        is_online: Callable[[uuid.UUID], bool],
    ) -> RuntimeSignals:
        """Phase B, with its one query.

        The query is skipped entirely when nothing is queued, which is the common case:
        the fixed dataset has 6 queued runs against 200 cards, and D92's claim is that
        phase B's cost tracks the queue rather than the board.
        """
        if not queued:
            return RuntimeSignals({})
        runners = list(
            (
                await self._session.execute(
                    select(AgentRunner).where(AgentRunner.enabled.is_(True))
                )
            ).scalars()
        )
        return resolve_runtime_signals(queued, tasks, runners, is_online=is_online)

    @staticmethod
    def _over_wip_stages(counts: Counter[str], *, process: EffectiveProcess) -> frozenset[str]:
        """Which lanes are over the process's suggested limit.

        WIP is a property of the lane, so every card in an over-full lane carries the
        signal. That is the intent — the lane is the thing to fix — and it is also why
        level 8 is last in `ATTENTION_ORDER`: a signal shared by twelve cards must never
        outrank one that names a single stalled agent.
        """
        over: set[str] = set()
        for stage, count in counts.items():
            limit = process.wip_for(stage)
            if limit is not None and count > limit:
                over.add(stage)
        return frozenset(over)
