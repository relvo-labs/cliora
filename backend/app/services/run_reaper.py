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
from app.db.models import RunLog, Task, TaskRun
from app.logging import get_logger
from app.services.activity import ACTOR_SYSTEM, RUN_FINISHED, ActivityService
from app.services.run_logs import get_run_log_buffer
from app.services.runs import LEASED_STATUSES, MessageService, RunService
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
                        )
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not runs:
                return
            messages = MessageService(session)
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
                task.stage = "blocked"
                await messages.post_event(
                    task=task,
                    body=(
                        f"Agent 的提問超過 {settings.run_waiting_timeout_hours} 小時未獲回覆，"
                        "這張卡已退回「阻塞」。回覆之後可以重新派工。"
                    ),
                    event_kind="run.waiting_timeout",
                )
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
