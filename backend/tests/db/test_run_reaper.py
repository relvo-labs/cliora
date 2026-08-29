"""What Central does when a runner stops answering (AR-05, ADR 0029 §5).

The sweep is the only part of the phase that acts with nobody watching *on the platform
side*, and each of its three jobs answers a different question. The tests are separate
for the same reason the jobs are in separate transactions: a failure in one must not be
able to look like a failure in another.

The one property worth stating up front, because it is what a reader would otherwise
merge: **the lease answers "is the runner alive" and nothing else.** A hung child is
the daemon's problem and produces a different outcome — `RUN_IDLE_TIMEOUT`, no re-queue.
`test_a_lost_runner_and_a_hung_child_end_differently` is exit condition 14d.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.clock import now_utc
from app.db.models import AgentRunner, Node, Project, Role, RunLog, Task, TaskRun, User
from app.security.passwords import hash_password
from app.services.run_reaper import RunReaper

pytestmark = pytest.mark.asyncio


async def _fixture(maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A project, a card and a runner, committed. Returns their ids."""
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        name = f"reap-{uuid.uuid4().hex[:8]}"
        user = User(
            id=uuid.uuid4(),
            username=name,
            display_name=name,
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid.uuid4(),
            name=name,
            slug=name,
            status="active",
            owner_user_id=user.id,
            next_card_seq=1,
        )
        session.add(project)
        await session.flush()
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=f"TASK-{uuid.uuid4().hex[:4]}",
            title="a card",
            stage="ready",
            source="none",
            delivery="none",
        )
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add_all([task, node])
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(), node_id=node.id, name=name, runtimes=["claude"], labels=[]
        )
        session.add(runner)
        await session.commit()
        return project.id, task.id, runner.id


async def _run(maker, project_id, task_id, **fields) -> uuid.UUID:
    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task_id,
            project_id=project_id,
            seq=fields.pop("seq", 1),
            source_kind="none",
            **fields,
        )
        session.add(run)
        await session.commit()
        return run.id


async def _runs(maker, task_id) -> list[TaskRun]:
    async with maker() as session:
        return list(
            (
                await session.execute(
                    sa.select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.seq)
                )
            ).scalars()
        )


async def _cleanup(maker, project_id) -> None:
    async with maker() as session:
        await session.execute(
            sa.delete(RunLog).where(
                RunLog.run_id.in_(sa.select(TaskRun.id).where(TaskRun.project_id == project_id))
            )
        )
        await session.execute(sa.delete(TaskRun).where(TaskRun.project_id == project_id))
        await session.execute(sa.delete(Task).where(Task.project_id == project_id))
        await session.commit()


async def test_an_expired_lease_is_lost_and_requeued(api: tuple, db_url: str) -> None:
    """Exit condition 11's Central half.

    `lost` is terminal and the retry is a **new row**: reusing this one would erase
    where the previous attempt failed, and showing that is the Run detail page's whole
    job.
    """
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        await _run(
            maker,
            project,
            task,
            status="running",
            runner_id=runner,
            assigned_runner_id=runner,
            lease_expires_at=now_utc() - timedelta(minutes=5),
        )

        await RunReaper().sweep()

        rows = await _runs(maker, task)
        assert [row.status for row in rows] == ["lost", "queued"]
        assert rows[1].seq == 2
        assert rows[1].attempt == 2
        # The retry keeps the assignment the **run** carried, not whatever the card
        # says now — the snapshot column's only reason to exist.
        assert rows[1].assigned_runner_id == runner
    finally:
        await _cleanup(maker, project)


async def test_a_run_waiting_on_a_person_is_not_reclaimed_by_the_lease(
    api: tuple, db_url: str
) -> None:
    """Its runner is alive and renewing; the thing being waited on is a human.

    Reclaiming it here would re-queue a card somebody is in the middle of answering.
    """
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        await _run(
            maker,
            project,
            task,
            status="waiting_for_input",
            runner_id=runner,
            lease_expires_at=now_utc() - timedelta(hours=1),
            waiting_since=now_utc(),
        )

        await RunReaper().sweep()

        rows = await _runs(maker, task)
        assert [row.status for row in rows] == ["waiting_for_input"]
    finally:
        await _cleanup(maker, project)


async def test_an_unanswered_question_blocks_the_card_and_says_why(api: tuple, db_url: str) -> None:
    """Exit condition 15's tail. A different timer from the lease, because it answers a
    different question: is the *person* still there."""
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        await _run(
            maker,
            project,
            task,
            status="waiting_for_input",
            runner_id=runner,
            lease_expires_at=now_utc() + timedelta(minutes=5),
            waiting_since=now_utc() - timedelta(days=3),
        )

        await RunReaper().sweep()

        rows = await _runs(maker, task)
        assert rows[0].status == "failed"
        assert rows[0].error_code == "RUN_WAITING_TIMEOUT"
        async with maker() as session:
            card = await session.get(Task, task)
            # **`is_blocked`, not the stage** (`HD-06`, `0045`/`0046`). This assertion
            # named one of the three writers that made `tasks.is_blocked` unreadable —
            # and it passed the whole time, because it was checking the wrong column
            # against the wrong intent. The card keeps the lane it was working in: a run
            # giving up does not move work backwards, it marks it as needing a person.
            assert card is not None
            assert card.is_blocked is True
            assert card.blocking_reason == "human_input"
            assert card.stage != "blocked", "blocked is not a lane any more"
            bodies = (
                await session.execute(
                    sa.text("select body from task_messages where task_id = :task_id"),
                    {"task_id": task},
                )
            ).scalars()
            # The card carries the reason. A card that went to `blocked` with nothing
            # written on it is a card nobody can act on.
            assert any("未獲回覆" in body for body in bodies)
    finally:
        await _cleanup(maker, project)


async def test_the_last_attempt_blocks_the_card_instead_of_retrying_forever(
    api: tuple, db_url: str
) -> None:
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        await _run(
            maker,
            project,
            task,
            status="running",
            attempt=3,
            runner_id=runner,
            lease_expires_at=now_utc() - timedelta(minutes=5),
        )

        await RunReaper().sweep()

        rows = await _runs(maker, task)
        assert len(rows) == 1, "a fourth attempt was created"
        assert rows[0].status == "lost"
        async with maker() as session:
            card = await session.get(Task, task)
            assert card is not None
            assert card.is_blocked is True
            # **`run_failed`, and the difference from the test above is the point.**
            # That one is "an agent asked and nobody answered"; this one is "the run
            # exhausted its attempts". Both used to land on `stage='blocked'`, which
            # said neither — the whole reason `HD-06` gives each writer a reason to
            # supply rather than a lane to move to.
            assert card.blocking_reason == "run_failed"
    finally:
        await _cleanup(maker, project)


async def test_expired_logs_are_deleted_per_run_and_the_counters_survive(
    api: tuple, db_url: str
) -> None:
    """Retention deletes a run's rows **as a group**.

    Deleting by `received_at` would leave half a log behind, and half a log is harder
    to explain than none. The byte counters stay: "this run produced 4 MB" is still
    true after the log itself is gone.
    """
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        expired = await _run(
            maker,
            project,
            task,
            status="succeeded",
            seq=1,
            log_bytes=4096,
            logs_expire_at=now_utc() - timedelta(days=1),
        )
        kept = await _run(
            maker,
            project,
            task,
            status="succeeded",
            seq=2,
            logs_expire_at=now_utc() + timedelta(days=1),
        )
        async with maker() as session:
            session.add_all(
                [
                    RunLog(id=uuid.uuid4(), run_id=expired, seq=0, data="a"),
                    RunLog(id=uuid.uuid4(), run_id=expired, seq=1, data="b"),
                    RunLog(id=uuid.uuid4(), run_id=kept, seq=0, data="c"),
                ]
            )
            await session.commit()

        await RunReaper().sweep()

        async with maker() as session:
            remaining = (
                await session.execute(sa.select(RunLog.run_id).order_by(RunLog.seq))
            ).scalars()
            assert set(remaining) == {kept}, "an expired run's log was only half removed"
            row = await session.get(TaskRun, expired)
            assert row is not None
            assert row.log_bytes == 4096
            assert row.logs_expire_at is None, "the run would be swept again every round"
    finally:
        await _cleanup(maker, project)


async def test_a_lost_runner_and_a_hung_child_end_differently(api: tuple, db_url: str) -> None:
    """Exit condition 14d, and the reason the three timers are kept apart.

    A **runner** that died is Central's to notice, and the card is re-queued. A **child**
    that hung is the daemon's to notice, and the run simply fails — re-queueing it would
    hand the same stuck work to another machine. Making lease renewal conditional on
    child activity would collapse these two into one.
    """
    _client, maker = api
    project, task, runner = await _fixture(maker)
    try:
        # The daemon already reported the hung child; the sweep must leave it alone.
        await _run(
            maker,
            project,
            task,
            seq=1,
            status="failed",
            error_code="RUN_IDLE_TIMEOUT",
            runner_id=runner,
            lease_expires_at=now_utc() - timedelta(hours=2),
        )
        await RunReaper().sweep()
        rows = await _runs(maker, task)
        assert len(rows) == 1, "an idle-timed-out run was re-queued"
        assert rows[0].error_code == "RUN_IDLE_TIMEOUT"

        # A lost runner, by contrast, produces a second row.
        await _run(
            maker,
            project,
            task,
            seq=2,
            status="running",
            runner_id=runner,
            lease_expires_at=now_utc() - timedelta(minutes=5),
        )
        await RunReaper().sweep()
        rows = await _runs(maker, task)
        assert [row.status for row in rows] == ["failed", "lost", "queued"]
    finally:
        await _cleanup(maker, project)
