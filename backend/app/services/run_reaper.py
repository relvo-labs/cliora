"""The lease sweep: what Central does when a runner stops answering (ADR 0029 sec 5).

A **periodic sweep**, not a per-item timer in the shape of `shell_reaper.py`. That
file's "This is not a scheduler" comment is right about shells, which have exactly one
idle trigger each; a lease is different in three ways that all point the same way: it
is reset every thirty seconds, a `waiting_for_input` run's 24-hour clock outlives a
Central restart, and `lease_expires_at` is already a column with an index on it.

Three jobs per round, in three transactions rather than one, because a failure in the
third must not roll back the first two:

    A. leases that expired      → `lost`, then re-queue (a new row, ADR 0029 sec 4)
    B. answers nobody gave      → `failed`, card back to `blocked`
    C. logs past their retention → deleted, per run, in batches

**A answers "is the runner alive", never "is the child working".** The second question
belongs to the daemon, which has the event stream; the two are kept apart deliberately,
because making lease renewal conditional on child activity would make a dead runner and
a hung child look identical to Central while their recoveries differ.

Each round is bounded. A Central that was down for two days must not come back and
rewrite thousands of rows in one transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

from sqlalchemy import delete, select

from app.clock import now_utc
from app.db.engine import get_database
from app.db.models import RunLog, Task, TaskQuestion, TaskRun
from app.logging import get_logger
from app.services.activity import ACTOR_SYSTEM, RUN_FINISHED, ActivityService
from app.services.conversation import ConversationService
from app.services.deliveries import DeliveryService
from app.services.run_logs import get_run_log_buffer
from app.services.runs import LEASED_STATUSES, RunService
from app.settings import get_settings

_logger = get_logger("cliora.run_reaper")

# Rows touched per round, per job. Deliberately small: the point is to make progress
# every round, not to finish in one.
BATCH = 200


class RunReaper:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Reconcile once, then loop. The reconcile is what `main.py:73` already does
        for idle shells, and for the same reason: whatever expired while this process
        was not running is still expired."""
        await self.sweep()
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        # A third of the lease, so a lease can never expire and sit unnoticed for a
        # whole period.
        interval = max(5.0, get_settings().run_lease_timeout_seconds / 3)
        while True:
            try:
                await asyncio.sleep(interval)
                await self.sweep()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 - a sweep failure must not end the loop
                _logger.warning(
                    "run_reaper_failed",
                    extra={"event": "run_reaper_failed", "error": type(exc).__name__},
                )

    async def sweep(self) -> None:
        await self._reclaim_leases()
        await self._expire_waiting()
        await self._expire_parked_runs()
        await self._deliver_pending_pull_requests()
        await self._flush_stale_log_buffers()
        await self._delete_expired_logs()

    async def _reclaim_leases(self) -> None:
        now = now_utc()
        async with get_database().session() as session:
            runs = list(
                (
                    await session.execute(
                        select(TaskRun)
                        .where(
                            TaskRun.status.in_(LEASED_STATUSES),
                            TaskRun.lease_expires_at.is_not(None),
                            TaskRun.lease_expires_at < now,
                        )
                        .order_by(TaskRun.lease_expires_at)
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not runs:
                return
            service = RunService(session)
            for run in runs:
                await service.requeue_lost(run)
            await session.commit()
            _logger.info(
                "run_leases_reclaimed",
                extra={"event": "run_leases_reclaimed", "count": len(runs)},
            )

    async def _expire_waiting(self) -> None:
        """Job B, and V2-C1 moved what it sweeps (ADR 0035, `plan/23/04-…md` §4).

        It used to scan runs for ``status='waiting_for_input'``. That misses the shape
        this phase introduced: a run that asked a question and **exited**, whose card
        is still waiting while the run itself is terminal. Sweeping questions catches
        both, because a question is the thing that is actually waiting.

        The run half is kept for the live case: an agent that never exited still holds
        a lease and a capacity slot, and those have to be released by failing the run
        exactly as before. Everything a person sees — twenty-four hours, the card going
        back to `blocked`, the sentence on the card — is unchanged.

        **The question is expired, not deleted** (`FR-CONV-003.AC-03`). Somebody reading
        the card tomorrow should find the question that went unanswered, not a gap.
        """
        settings = get_settings()
        cutoff = now_utc() - timedelta(hours=settings.run_waiting_timeout_hours)
        async with get_database().session() as session:
            questions = list(
                (
                    await session.execute(
                        select(TaskQuestion)
                        .where(
                            TaskQuestion.state == "open",
                            TaskQuestion.created_at < cutoff,
                        )
                        .order_by(TaskQuestion.created_at)
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not questions:
                return
            conversation = ConversationService(session)
            activity = ActivityService(session)
            for question in questions:
                await conversation.expire_question(question)
                task = await session.get(Task, question.task_id)
                if task is None:  # pragma: no cover - the FK makes this unreachable
                    continue
                run = (
                    await session.get(TaskRun, question.run_id)
                    if question.run_id is not None
                    else None
                )
                if run is not None and run.status == "waiting_for_input":
                    # The live case: a process is still up, holding a lease it will
                    # never use. Ending the run is what releases both.
                    run.status = "failed"
                    run.result = "failed"
                    run.error_code = "RUN_WAITING_TIMEOUT"
                    run.finished_at = now_utc()
                    run.logs_expire_at = now_utc() + timedelta(days=14)
                # `is_blocked`, not the stage (`0045`/`0046`, ADR 0040's amendment).
                # This was one of the three writers that made `tasks.is_blocked` give the
                # wrong answer when read directly, for three phases. The card keeps the
                # stage it was working in — a run giving up does not move work backwards,
                # it marks it as needing a person.
                task.is_blocked = True
                task.blocking_reason = "human_input"
                await conversation.post_event(
                    task=task,
                    body=(
                        f"Agent 的提問超過 {settings.run_waiting_timeout_hours} 小時未獲回覆，"
                        "這張卡已退回「阻塞」。回覆之後可以重新派工。"
                    ),
                    event_kind="run.waiting_timeout",
                )
                await conversation.reproject(task)
                await activity.record(
                    RUN_FINISHED,
                    project_id=task.project_id,
                    task_id=task.id,
                    actor_kind=ACTOR_SYSTEM,
                    payload={
                        "run_id": str(run.id) if run is not None else None,
                        "card_ref": task.card_ref,
                        "result": "failed",
                        "error_code": "RUN_WAITING_TIMEOUT",
                        "question_id": str(question.id),
                    },
                )
            await session.commit()

    async def _expire_parked_runs(self) -> None:
        """Job B′: a run parked on `waiting_for_input` with no question row behind it.

        Two ways in. A daemon may set the state through `run.progress`'s
        `waiting_for_input` flag without any question having been asked, and a card
        upgraded mid-flight can be parked from before `0040` existed. Neither has a row
        for the question sweep to find, and neither should hold a lease for ever.

        Kept as a second pass rather than folded into the first, because the two are
        answering different questions — "nobody answered this question" and "this run is
        parked on nothing" — and a single query that did both would obscure which case
        fired.
        """
        settings = get_settings()
        cutoff = now_utc() - timedelta(hours=settings.run_waiting_timeout_hours)
        async with get_database().session() as session:
            runs = list(
                (
                    await session.execute(
                        select(TaskRun)
                        .where(
                            TaskRun.status == "waiting_for_input",
                            TaskRun.waiting_since.is_not(None),
                            TaskRun.waiting_since < cutoff,
                            ~select(TaskQuestion.id)
                            .where(TaskQuestion.run_id == TaskRun.id)
                            .exists(),
                        )
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not runs:
                return
            conversation = ConversationService(session)
            activity = ActivityService(session)
            for run in runs:
                run.status = "failed"
                run.result = "failed"
                run.error_code = "RUN_WAITING_TIMEOUT"
                run.finished_at = now_utc()
                run.logs_expire_at = now_utc() + timedelta(days=14)
                task = await session.get(Task, run.task_id)
                if task is None:  # pragma: no cover - the FK makes this unreachable
                    continue
                # `is_blocked`, not the stage (`0045`/`0046`, ADR 0040's amendment).
                # This was one of the three writers that made `tasks.is_blocked` give the
                # wrong answer when read directly, for three phases. The card keeps the
                # stage it was working in — a run giving up does not move work backwards,
                # it marks it as needing a person.
                task.is_blocked = True
                task.blocking_reason = "human_input"
                await conversation.post_event(
                    task=task,
                    body=(
                        f"Agent 的提問超過 {settings.run_waiting_timeout_hours} 小時未獲回覆，"
                        "這張卡已退回「阻塞」。回覆之後可以重新派工。"
                    ),
                    event_kind="run.waiting_timeout",
                )
                await conversation.reproject(task)
                await activity.record(
                    RUN_FINISHED,
                    project_id=run.project_id,
                    task_id=task.id,
                    actor_kind=ACTOR_SYSTEM,
                    payload={
                        "run_id": str(run.id),
                        "card_ref": task.card_ref,
                        "result": "failed",
                        "error_code": "RUN_WAITING_TIMEOUT",
                    },
                )
            await session.commit()

    async def _deliver_pending_pull_requests(self) -> None:
        """Job D: open the pull requests `finish()` asked for.

        **Here rather than in `finish()`** because this is where a network call is
        allowed to take twenty seconds: the receive loop is not (ADR 0033 §3).

        Three bounds, and the third is the one that is easy to leave out:

        * **at most `provider_max_concurrent` per round** — the work is sequential
          here, so the bound is the batch size, and a burst of finished runs does not
          become a burst of API calls;
        * **no retry** — `deliver()` settles every run it takes, into `delivered` or
          `branch_only`, so nothing stays in `pending_pr` to be picked up again. A
          retry would be a second pull request, because creation is not idempotent;
        * **a visible backlog ceiling** — past `provider_pending_limit` the worker
          stops taking new work and says so. A queue nobody can see becomes fifty pull
          requests the moment the provider recovers.
        """
        settings = get_settings()
        async with get_database().session() as session:
            service = DeliveryService(session, settings=settings)
            pending = await service.pending_count()
            if pending > settings.provider_pending_limit:
                _logger.warning(
                    "pull request backlog above the limit; not taking more this round",
                    extra={"pending": pending, "limit": settings.provider_pending_limit},
                )
                return
            runs = await service.claim_batch(settings.provider_max_concurrent)
            for run in runs:
                outcome = await service.deliver(run)
                if outcome.state != "delivered":
                    task = await session.get(Task, run.task_id)
                    if task is not None:
                        await ConversationService(session).post_event(
                            task=task,
                            body=(
                                "分支已推送，但合併請求未能建立："
                                f"{outcome.reason or '未知原因'}。可以手動開 PR。"
                            ),
                            event_kind="run.delivered_branch_only",
                        )
            if runs:
                await session.commit()

    async def _flush_stale_log_buffers(self) -> None:
        """Write out buffers whose run went quiet.

        Without this, a run that produces its last output and then thinks for a minute
        leaves that segment invisible until it finishes — which is exactly the window
        somebody watching the log is staring at.
        """
        buffer = get_run_log_buffer()
        now = asyncio.get_running_loop().time()
        due = buffer.due(now)
        if not due:
            return
        async with get_database().session() as session:
            for run_id in due:
                await buffer.flush(session, run_id, now=now)
            await session.commit()

    async def _delete_expired_logs(self) -> None:
        """Retention, per run rather than per row.

        Deleting by `received_at` would leave half a run's log behind, and half a log
        is harder to explain than none of it (ADR 0030 Part A).
        """
        now = now_utc()
        async with get_database().session() as session:
            run_ids = list(
                (
                    await session.execute(
                        select(TaskRun.id)
                        .where(
                            TaskRun.logs_expire_at.is_not(None),
                            TaskRun.logs_expire_at < now,
                        )
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not run_ids:
                return
            await session.execute(delete(RunLog).where(RunLog.run_id.in_(run_ids)))
            # Cleared so the same runs are not selected again next round; the counters
            # stay, because "this run produced 4 MB of log" is still true after the log
            # itself is gone.
            for run_id in run_ids:
                run = await session.get(TaskRun, run_id)
                if run is not None:
                    run.logs_expire_at = None
            await session.commit()
            _logger.info(
                "run_logs_expired",
                extra={"event": "run_logs_expired", "runs": len(run_ids)},
            )


_reaper = RunReaper()


def get_run_reaper() -> RunReaper:
    return _reaper
