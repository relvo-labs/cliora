"""The queue's load-bearing guarantees (AR-05, FR-AGENT-003/004/008, ADR 0029).

What is asserted here is what the *database and the service* hold, not what a review
can be persuaded of. Five of these fail silently if they are ever broken, which is why
each has its own test rather than being folded into an end-to-end run:

* **a double claim is impossible**, and the guarantee is one `WHERE runner_id IS NULL`
  rather than a handshake — so the test races real sessions instead of mocking one;
* **a card assigned to A is not even a candidate for B** — "B claimed it and was
  refused" would be a different, weaker property;
* **the queue is first-in-first-out and nothing else** — that single `ORDER BY` is what
  "the platform does not schedule" looks like in code, so a higher-risk card queued
  second must still be offered second;
* **a re-queue keeps the assignment the run was created with**, not the one the card
  carries now — the snapshot column exists for exactly this and would otherwise look
  redundant enough to delete;
* **`waiting_for_input` does not occupy execution capacity** — the alternative is three
  runs waiting on a human taking a node offline for work.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.clock import now_utc
from app.db.models import AgentRunner, Node, Project, Role, Task, TaskRun, User
from app.security.passwords import hash_password
from app.services.runs import RunService, claim
from app.settings import Settings

pytestmark = pytest.mark.asyncio


async def _admin(session: AsyncSession, username: str) -> User:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User, slug: str) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name=slug,
        slug=slug,
        status="active",
        owner_user_id=owner.id,
        next_card_seq=1,
    )
    session.add(project)
    await session.flush()
    return project


async def _node(session: AsyncSession, name: str) -> Node:
    node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
    session.add(node)
    await session.flush()
    return node


async def _runner(
    session: AsyncSession, name: str, *, runtimes: list[str] | None = None
) -> AgentRunner:
    node = await _node(session, name)
    runner = AgentRunner(
        id=uuid.uuid4(),
        node_id=node.id,
        name=name,
        runtimes=runtimes if runtimes is not None else ["claude"],
        labels=[],
    )
    session.add(runner)
    await session.flush()
    return runner


async def _card(session: AsyncSession, project: Project, ref: str, *, risk: str = "medium") -> Task:
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref=ref,
        title=ref,
        stage="ready",
        risk=risk,
        source="none",
        delivery="none",
    )
    session.add(task)
    await session.flush()
    return task


async def _queued(
    session: AsyncSession,
    task: Task,
    *,
    assigned_runner_id: uuid.UUID | None = None,
    seq: int = 1,
) -> TaskRun:
    run = TaskRun(
        id=uuid.uuid4(),
        task_id=task.id,
        project_id=task.project_id,
        seq=seq,
        status="queued",
        attempt=1,
        assigned_runner_id=assigned_runner_id,
        source_kind="none",
    )
    session.add(run)
    await session.flush()
    return run


async def test_only_one_runner_can_claim_a_run(db_url: str) -> None:
    """Two runners, one card, fifty interleaved attempts — one winner every time.

    Real sessions rather than one transaction: the `WHERE runner_id IS NULL` clause is
    only a guarantee if two connections actually contend for the row, and a test that
    shares a session proves nothing about that.
    """
    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as setup:
            owner = await _admin(setup, f"claimrace-{uuid.uuid4().hex[:8]}")
            project = await _project(setup, owner, f"claimrace-{uuid.uuid4().hex[:8]}")
            runner_a = await _runner(setup, f"a-{uuid.uuid4().hex[:8]}")
            runner_b = await _runner(setup, f"b-{uuid.uuid4().hex[:8]}")
            runs = []
            for index in range(50):
                task = await _card(setup, project, f"RACE-{index}")
                runs.append(await _queued(setup, task))
            await setup.commit()
            run_ids = [run.id for run in runs]
            ids = (project.id, runner_a.id, runner_b.id)
            node_ids = (runner_a.node_id, runner_b.node_id)

        async def attempt(runner_id: uuid.UUID, run_id: uuid.UUID) -> bool:
            async with maker() as session:
                won = await claim(
                    session,
                    run_id=run_id,
                    runner_id=runner_id,
                    runtime="claude",
                    lease_seconds=180,
                )
                await session.commit()
                return won

        for run_id in run_ids:
            results = await asyncio.gather(
                attempt(ids[1], run_id),
                attempt(ids[2], run_id),
            )
            assert sum(results) == 1, "both runners claimed the same run"

        async with maker() as check:
            rows = (
                await check.execute(sa.select(TaskRun).where(TaskRun.id.in_(run_ids)))
            ).scalars()
            for row in rows:
                assert row.runner_id is not None
                assert row.status == "claimed"
    finally:
        # This test commits, so it cleans up after itself rather than relying on the
        # rolled-back `session` fixture. Reverse foreign-key order.
        async with maker() as cleanup:
            await cleanup.execute(sa.delete(TaskRun).where(TaskRun.id.in_(run_ids)))
            await cleanup.execute(sa.delete(Task).where(Task.project_id == ids[0]))
            await cleanup.execute(sa.delete(AgentRunner).where(AgentRunner.id.in_(ids[1:])))
            await cleanup.execute(sa.delete(Node).where(Node.id.in_(node_ids)))
            await cleanup.execute(sa.delete(Project).where(Project.id == ids[0]))
            await cleanup.commit()
        await engine.dispose()


async def test_a_card_assigned_to_one_runner_is_not_a_candidate_for_another(
    session: AsyncSession,
) -> None:
    owner = await _admin(session, f"assigned-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"assigned-{uuid.uuid4().hex[:8]}")
    runner_a = await _runner(session, f"a-{uuid.uuid4().hex[:8]}")
    runner_b = await _runner(session, f"b-{uuid.uuid4().hex[:8]}")
    task = await _card(session, project, "ASSIGNED-1")
    await _queued(session, task, assigned_runner_id=runner_a.id)

    service = RunService(session, settings=Settings())
    # Not "B claims it and is refused" — B must not see it at all, which is the form
    # the exit condition names (ADR 0029 sec 3).
    assert await service.poll(runner=runner_b, capacity=5) is None
    offer = await service.poll(runner=runner_a, capacity=5)
    assert offer is not None and offer.task.card_ref == "ASSIGNED-1"


async def test_the_queue_is_first_in_first_out_and_ignores_risk(session: AsyncSession) -> None:
    """No priority, no load balancing, no round-robin. One `ORDER BY queued_at`."""
    owner = await _admin(session, f"fifo-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"fifo-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")

    first = await _card(session, project, "FIFO-1", risk="low")
    first_run = await _queued(session, first)
    first_run.queued_at = now_utc().replace(microsecond=0)
    second = await _card(session, project, "FIFO-2", risk="critical")
    second_run = await _queued(session, second)
    second_run.queued_at = first_run.queued_at.replace(microsecond=500000)
    await session.flush()

    service = RunService(session, settings=Settings())
    offer = await service.poll(runner=runner, capacity=1)
    assert offer is not None
    assert offer.task.card_ref == "FIFO-1", "a higher-risk card queued second was offered first"


async def test_a_disabled_runner_sees_nothing(session: AsyncSession) -> None:
    owner = await _admin(session, f"disabled-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"disabled-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")
    runner.enabled = False
    task = await _card(session, project, "DISABLED-1")
    await _queued(session, task)

    assert await RunService(session, settings=Settings()).poll(runner=runner, capacity=5) is None


async def test_one_runner_claims_cards_from_two_projects(session: AsyncSession) -> None:
    """V2.2's posture, asserted rather than assumed.

    There is no project↔agent binding: **the authorization boundary is enrollment**, so
    one runner is eligible for every project's queued work. When V2.3 adds the binding
    this test is the one that has to change, and it should be hard to change by
    accident.
    """
    owner = await _admin(session, f"twoproj-{uuid.uuid4().hex[:8]}")
    left = await _project(session, owner, f"left-{uuid.uuid4().hex[:8]}")
    right = await _project(session, owner, f"right-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")
    await _queued(session, await _card(session, left, "L-1"))
    await _queued(session, await _card(session, right, "R-1"))

    service = RunService(session, settings=Settings())
    first = await service.poll(runner=runner, capacity=1)
    second = await service.poll(runner=runner, capacity=1)
    assert first is not None and second is not None
    assert {first.run.project_id, second.run.project_id} == {left.id, right.id}


async def test_decline_returns_the_run_without_spending_an_attempt(session: AsyncSession) -> None:
    owner = await _admin(session, f"decline-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"decline-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")
    task = await _card(session, project, "DECLINE-1")
    run = await _queued(session, task)

    service = RunService(session, settings=Settings())
    offer = await service.poll(runner=runner, capacity=1)
    assert offer is not None
    await service.apply_event(
        node_id=runner.node_id, message_type="run.decline", payload={"run_id": str(run.id)}
    )
    await session.refresh(run)
    assert run.status == "queued"
    assert run.runner_id is None
    # A decline is a release, not a failure: the runner may simply have filled up.
    assert run.attempt == 1
    # And the same runner does not pick it straight back up on its next poll.
    assert await service.poll(runner=runner, capacity=1) is None


async def test_a_lost_run_is_requeued_as_a_new_row_keeping_the_original_assignment(
    session: AsyncSession,
) -> None:
    """The snapshot column's only reason to exist.

    The card's assignment is changed **between** the loss and the re-queue, exactly as a
    person editing a card mid-run would. The retry must still name the runner the run
    was created with; without this test that column looks redundant enough to delete.
    """
    owner = await _admin(session, f"lost-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"lost-{uuid.uuid4().hex[:8]}")
    runner_a = await _runner(session, f"a-{uuid.uuid4().hex[:8]}")
    runner_b = await _runner(session, f"b-{uuid.uuid4().hex[:8]}")
    task = await _card(session, project, "LOST-1")
    run = await _queued(session, task, assigned_runner_id=runner_a.id)
    run.status = "running"
    run.runner_id = runner_a.id
    await session.flush()

    task.assigned_runner_id = runner_b.id
    await session.flush()

    retry = await RunService(session, settings=Settings()).requeue_lost(run)
    assert retry is not None
    assert run.status == "lost"
    assert retry.seq == run.seq + 1
    assert retry.attempt == 2
    assert retry.assigned_runner_id == runner_a.id, "the retry followed the card, not the run"


async def test_the_last_attempt_blocks_the_card_and_names_the_agent(
    session: AsyncSession,
) -> None:
    owner = await _admin(session, f"exhaust-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"exhaust-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")
    task = await _card(session, project, "EXHAUST-1")
    run = await _queued(session, task, assigned_runner_id=runner.id)
    run.attempt = 3
    run.status = "running"
    run.runner_id = runner.id
    await session.flush()

    settings = Settings()
    assert await RunService(session, settings=settings).requeue_lost(run) is None
    await session.refresh(task)
    # `is_blocked` with a reason, not a lane (`HD-06`). The third of the three writers,
    # and the only one in `runs.py` — the file `GATE-DV-SINGLE-DONE-PATH` already scans,
    # which is why it was the one closest to being caught and still was not: that gate
    # watches for `'done'`.
    assert task.is_blocked is True
    assert task.blocking_reason == "run_failed"
    assert task.stage != "blocked"
    messages = (
        await session.execute(
            sa.select(sa.text("body"))
            .select_from(sa.text("task_messages"))
            .where(sa.text("task_id = :task_id")),
            {"task_id": task.id},
        )
    ).scalars()
    bodies = list(messages)
    assert bodies, "the card says nothing about why it is blocked"
    # Named vs unnamed is two different sentences, for the same reason the dispatch
    # copy has two: they lead a person to do different things.
    assert runner.name in bodies[0]


async def test_a_run_waiting_for_input_does_not_occupy_execution_capacity(
    session: AsyncSession,
) -> None:
    from app.services.runners import RunnerService

    owner = await _admin(session, f"waiting-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"waiting-{uuid.uuid4().hex[:8]}")
    runner = await _runner(session, f"r-{uuid.uuid4().hex[:8]}")
    task = await _card(session, project, "WAIT-1")
    run = await _queued(session, task)
    run.status = "waiting_for_input"
    run.runner_id = runner.id
    run.waiting_since = now_utc()
    await session.flush()

    view = await RunnerService(session).view(runner, is_online=lambda _node_id: True)
    assert view.waiting_runs == 1
    assert view.active_runs == 0, "a run waiting on a person is holding execution capacity"
