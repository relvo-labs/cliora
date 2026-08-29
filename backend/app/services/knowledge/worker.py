"""The ingestion loop: claim a hint, re-read the entity, write what is true now.

Shaped after `RunReaper` (`app/services/run_reaper.py`), because that file already paid
for the three properties a background loop in this system needs:

1. **Reconcile once before entering the loop.** Whatever changed while this process was
   not running still changed.
2. **Several transactions per round, not one.** A failure in the third must not roll
   back the first two.
3. **Every round is bounded.** A Central that was down for two days must not come back
   and rewrite thousands of rows in one statement.

Two things are different here and both are consequences of ADR 0038:

* **Claiming is `FOR UPDATE SKIP LOCKED`, so several replicas are correct by
  construction** and more of them is simply faster. The reconciler is the opposite —
  its cost is per replica and its benefit is not — so it takes a transaction-scoped
  advisory lock. A transaction lock rather than a leader row because commit, rollback or
  connection death releases it, and a Central killed with `SIGKILL` must not leave a
  permanent leader behind.
* **A job is a hint, not content.** Processing one means re-reading the entity's current
  state, so a retry is free and a duplicate is free. Nothing here replays events.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import timedelta

import sqlalchemy as sa

from app import metrics
from app.clock import now_utc
from app.db.engine import get_database
from app.db.models import KnowledgeJob, Project
from app.logging import get_logger
from app.services.knowledge import sources as source_handlers
from app.services.knowledge.outbox import KnowledgeOutbox
from app.settings import Settings

log = get_logger("cliora.knowledge.worker")

#: Jobs claimed per round. Much smaller than `RunReaper`'s 200: a job here reads an
#: entity, splits it and writes a GIN index, where a lease sweep updates one column.
BATCH = 32
#: Seconds between rounds. The freshness budget is P95 < 10s end to end, and this is the
#: largest single contributor to it.
INTERVAL_SECONDS = 3.0
RECONCILE_INTERVAL_SECONDS = 300.0
MAX_ATTEMPTS = 5
#: A `running` job older than this was interrupted, not slow. Ten minutes is far beyond
#: any legitimate job and far below the point where somebody notices by hand.
STUCK_AFTER = timedelta(minutes=10)
#: Rows the reconciler may enqueue per source type per round. It is a catch-up path, so
#: it is allowed to take several rounds; what it may not do is enqueue a hundred
#: thousand hints in one transaction when a large project is first switched on.
RECONCILE_BATCH = 200

#: Backoff before the next attempt, indexed by the attempt that just failed.
_BACKOFF_SECONDS = (5, 30, 120, 600)

#: A constant, because it names a lock rather than a row. Derived from nothing so that
#: it cannot accidentally collide with a future one chosen the same way.
_RECONCILE_LOCK = 0x4B4E5245_43303031  # "KNRE" + "C001"


def _next_attempt_delay(attempts: int) -> int:
    index = min(max(attempts, 1), len(_BACKOFF_SECONDS)) - 1
    return _BACKOFF_SECONDS[index]


class KnowledgeWorker:
    """Owns the loop. One per Central process; several processes are fine."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._task: asyncio.Task[None] | None = None
        self._rounds_until_reconcile = 0
        # Only the provider pass needs it (for the API host allowlist and the secret
        # service). Optional and lazily defaulted so that every existing construction site
        # — `main.py`'s lifespan and a dozen tests — keeps working unchanged.
        self._settings = settings or Settings()

    async def start(self) -> None:
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
        while True:
            try:
                await asyncio.sleep(INTERVAL_SECONDS)
                await self.sweep()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 - one bad round must not end the loop
                log.warning(
                    "knowledge_worker_failed",
                    extra={"event": "knowledge_worker_failed", "error": type(exc).__name__},
                )

    async def sweep(self) -> int:
        """One round. Returns how many jobs were processed, for tests and for the log."""
        await self._recover_stuck()
        processed = await self._drain()
        self._rounds_until_reconcile -= 1
        if self._rounds_until_reconcile <= 0:
            self._rounds_until_reconcile = int(RECONCILE_INTERVAL_SECONDS / INTERVAL_SECONDS)
            await self.reconcile()
        return processed

    # --- claiming -----------------------------------------------------------

    async def _recover_stuck(self) -> None:
        """Return interrupted jobs to `pending`, **without counting an attempt**.

        A Central killed mid-job did not produce a failure; it produced no conclusion.
        Counting it would send healthy jobs to the dead letter after three restarts, and
        the dead letter is the one signal an operator is asked to trust.
        """
        async with get_database().session() as session:
            result = await session.execute(
                sa.update(KnowledgeJob)
                .where(
                    KnowledgeJob.state == "running",
                    KnowledgeJob.started_at < now_utc() - STUCK_AFTER,
                )
                .values(state="pending", started_at=None)
            )
            if result.rowcount:
                log.info(
                    "knowledge_jobs_recovered",
                    extra={"event": "knowledge_jobs_recovered", "count": result.rowcount},
                )
            await session.commit()

    async def _claim(self) -> list[KnowledgeJob]:
        now = now_utc()
        async with get_database().session() as session:
            claimable = (
                sa.select(KnowledgeJob.id)
                .where(
                    KnowledgeJob.state == "pending",
                    sa.or_(
                        KnowledgeJob.next_attempt_at.is_(None),
                        KnowledgeJob.next_attempt_at <= now,
                    ),
                )
                .order_by(KnowledgeJob.created_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
            rows = (
                (
                    await session.execute(
                        sa.update(KnowledgeJob)
                        .where(KnowledgeJob.id.in_(claimable.scalar_subquery()))
                        .values(
                            state="running",
                            attempts=KnowledgeJob.attempts + 1,
                            started_at=now,
                            updated_at=now,
                        )
                        .returning(KnowledgeJob.__table__)
                    )
                )
                .mappings()
                .all()
            )
            await session.commit()
        return [KnowledgeJob(**dict(row)) for row in rows]

    async def _drain(self) -> int:
        jobs = await self._claim()
        for job in jobs:
            # One transaction per job, so a poisonous entity cannot take the batch with
            # it. That is the same reason `RunReaper` splits its three jobs.
            await self._process(job)
        return len(jobs)

    # --- processing ---------------------------------------------------------

    async def _process(self, job: KnowledgeJob) -> None:
        started = now_utc()
        try:
            async with get_database().session() as session:
                enabled = await session.scalar(
                    sa.select(Project.knowledge_enabled).where(Project.id == job.project_id)
                )
                if not enabled:
                    # The switch may have been turned off between enqueue and claim.
                    # Finishing rather than failing: nothing is wrong, there is simply
                    # nothing to do.
                    await self._finish(session, job, outcome="skipped")
                    await session.commit()
                    return
                outcome = await source_handlers.ingest(
                    session,
                    project_id=job.project_id,
                    source_type=job.source_type,
                    external_id=job.external_id,
                    payload=job.payload or {},
                )
                await self._finish(session, job, outcome="done")
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - recorded on the job, not raised
            await self._fail(job, exc)
            return

        metrics.observe(
            metrics.KNOWLEDGE_JOB_DURATION,
            (now_utc() - started).total_seconds(),
            type=job.source_type,
        )
        for occurred_at in outcome.occurred_ats:
            metrics.observe(
                metrics.KNOWLEDGE_INGEST_LAG_SECONDS,
                max(0.0, (now_utc() - occurred_at).total_seconds()),
                type=job.source_type,
            )

    async def _finish(self, session, job: KnowledgeJob, *, outcome: str) -> None:
        await session.execute(
            sa.update(KnowledgeJob)
            .where(KnowledgeJob.id == job.id)
            .values(state="done", last_error=None, updated_at=now_utc(), started_at=None)
        )
        metrics.increment(metrics.KNOWLEDGE_JOBS_TOTAL, type=job.source_type, status=outcome)

    async def _fail(self, job: KnowledgeJob, exc: Exception) -> None:
        dead = job.attempts >= MAX_ATTEMPTS
        now = now_utc()
        # Type name and one line, never a traceback and never the entity's content: this
        # string is shown on the Source health panel, whose readers hold `project.view`.
        detail = f"{type(exc).__name__}: {str(exc)[:200]}"
        async with get_database().session() as session:
            await session.execute(
                sa.update(KnowledgeJob)
                .where(KnowledgeJob.id == job.id)
                .values(
                    state="dead" if dead else "pending",
                    last_error=detail,
                    dead_lettered_at=now if dead else None,
                    next_attempt_at=(
                        None if dead else now + timedelta(seconds=_next_attempt_delay(job.attempts))
                    ),
                    started_at=None,
                    updated_at=now,
                )
            )
            await session.commit()
        metrics.increment(
            metrics.KNOWLEDGE_JOBS_TOTAL,
            type=job.source_type,
            status="dead" if dead else "failed",
        )
        log.warning(
            "knowledge_job_failed",
            extra={
                "event": "knowledge_job_failed",
                "source_type": job.source_type,
                "attempts": job.attempts,
                "dead": dead,
                "error": type(exc).__name__,
            },
        )

    # --- reconciliation -----------------------------------------------------

    async def reconcile(self) -> int:
        """The correctness path: find entities the event path never mentioned.

        It is also the **backfill** path, which is why no backfill script exists
        anywhere (ADR 0038 §7). Switching a project on makes every one of its entities
        look like something the event path missed, and this fills them in. One filling
        routine is more correct than two that have to agree forever.
        """
        enqueued = 0
        async with get_database().session() as session:
            # Transaction-scoped is essential. A session-level lock followed by
            # ``commit(); unlock()`` is unsound with a pool: commit returns the owning
            # connection, then unlock may run on another connection and leave the first
            # one locked forever. The one-hour provider-lag observation reproduced that
            # exact failure after six rounds (PostgreSQL: "you don't own a lock").
            got_lock = await session.scalar(
                sa.text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": _RECONCILE_LOCK},
            )
            if not got_lock:
                return 0
            projects = (
                (
                    await session.execute(
                        sa.select(Project.id).where(Project.knowledge_enabled.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            outbox = KnowledgeOutbox(session)
            for project_id in projects:
                enqueued += await self._reconcile_project(session, outbox, project_id)
            # **Provider reads happen here, in the pass that already exists** (ADR 0043
            # §2). Not a second loop: this one already holds the advisory lock, already
            # runs at the 300-second cadence the freshness promise is stated in, and is
            # already safe to run twice or to miss. A loop of its own would need its
            # own copy of each of those and its own way of getting them wrong.
            #
            # Failures are absorbed per repository and stored as a reason, so an
            # unwell provider cannot abort reconciliation for the other projects.
            enqueued += await self._sync_providers(session)
            # Commit releases ``pg_try_advisory_xact_lock`` on the same transaction;
            # rollback/session close does the same on every exceptional path.
            await session.commit()
        if enqueued:
            log.info(
                "knowledge_reconciled",
                extra={"event": "knowledge_reconciled", "count": enqueued},
            )
        return enqueued

    async def _sync_providers(self, session) -> int:
        """One provider pass per project that asked for one.

        Separate from `knowledge_enabled`: a project may index its own facts without
        talking to anybody else's server, and ADR 0043 §5 makes provider sync its own
        per-project switch for that reason.

        Also where the freshness promise is recorded. `provider_sync` returns the gap
        between each changed provider entity's event timestamp and this ingestion round;
        first-pass history is excluded. Observing a just-written `provider_synced_at`
        would always report roughly zero and could never prove the 300-second promise.
        """
        from app.services.knowledge import provider_sync

        rows = (
            (
                await session.execute(
                    sa.select(Project.id).where(Project.provider_sync_enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        written = 0
        for project_id in rows:
            outcome = await provider_sync.sync_project(
                session, project_id=project_id, settings=self._settings
            )
            written += outcome.sources
            for lag in outcome.reconcile_lags_seconds:
                metrics.observe(metrics.PROVIDER_RECONCILE_LAG_SECONDS, lag)
        return written

    async def _reconcile_project(
        self, session, outbox: KnowledgeOutbox, project_id: uuid.UUID
    ) -> int:
        enqueued = 0
        for source_type, stale in source_handlers.WATERMARKS.items():
            external_ids = await stale(session, project_id, RECONCILE_BATCH)
            for external_id in external_ids:
                await outbox.enqueue(
                    project_id=project_id, source_type=source_type, external_id=external_id
                )
                enqueued += 1
        return enqueued


_worker: KnowledgeWorker | None = None


def get_knowledge_worker() -> KnowledgeWorker:
    global _worker  # noqa: PLW0603 - one loop per process, same shape as get_run_reaper
    if _worker is None:
        _worker = KnowledgeWorker()
    return _worker
