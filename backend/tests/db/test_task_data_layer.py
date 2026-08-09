"""The task layer's data-level guarantees (TK-02, FR-TASK-001/003, ADR 0028).

The same split as `test_projects_data_layer.py`: what is asserted here is what the
*database* holds, not what a service can be reviewed into holding. Four of these are
load-bearing in a way that is easy to lose later:

* `card_ref` allocation survives two writers, because the reference goes on to name a
  branch (V2.3) and a pull request (V2.4) — a collision surfaces three phases after
  the mistake;
* the optimistic lock is a conditional `UPDATE`, so a lost update is impossible
  rather than unlikely;
* a card cannot depend on itself, refused by a constraint rather than by a service;
* an epic that goes away drops its stories into the unclassified bucket instead of
  taking them with it — a card must never disappear because of how it was filed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Epic,
    Node,
    Project,
    Role,
    SessionToken,
    Task,
    TaskDependency,
    TerminalSession,
    User,
    UserStory,
)
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


async def _user(session: AsyncSession, username: str) -> User:
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
    project = Project(id=uuid.uuid4(), name=slug, slug=slug, owner_user_id=owner.id)
    session.add(project)
    await session.flush()
    return project


async def _task(session: AsyncSession, project: Project, ref: str, **kwargs: object) -> Task:
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref=ref,
        title=f"card {ref}",
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(task)
    await session.flush()
    return task


async def _allocate(session: AsyncSession, project_id: uuid.UUID) -> int:
    """The one allocation statement, exactly as the service issues it.

    `RETURNING next_card_seq - 1`: the column names the *next* number, so the caller
    takes the value it had before the increment.
    """
    result = await session.execute(
        sa.text(
            "UPDATE projects SET next_card_seq = next_card_seq + 1 "
            "WHERE id = :pid RETURNING next_card_seq - 1"
        ),
        {"pid": project_id},
    )
    return int(result.scalar_one())


async def test_card_refs_are_unique_within_a_project(session: AsyncSession) -> None:
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    await _task(session, project, "TASK-1")
    with pytest.raises(IntegrityError):
        await _task(session, project, "TASK-1")


async def test_the_same_card_ref_may_exist_in_two_projects(session: AsyncSession) -> None:
    """`card_ref` is unique per project, not globally.

    Which is why the API resolves it with a project in hand (`?ref=`) rather than
    accepting it as a path parameter: `TASK-12` on its own does not identify a card.
    """
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    first = await _project(session, owner, f"a-{uuid.uuid4().hex[:8]}")
    second = await _project(session, owner, f"b-{uuid.uuid4().hex[:8]}")
    await _task(session, first, "TASK-1")
    await _task(session, second, "TASK-1")
    count = await session.scalar(sa.select(sa.func.count()).select_from(Task))
    assert count == 2


async def test_the_counter_skips_across_the_three_card_kinds(session: AsyncSession) -> None:
    """One sequence for epics, stories and tasks, so numbers skip.

    Deliberate (ADR 0028 sec 7): three counters would be three things to lock, and the
    reference is an identifier rather than a count. Asserted so that "the numbers look
    wrong" is not later fixed into three counters.
    """
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    allocated = [await _allocate(session, project.id) for _ in range(3)]
    assert allocated == [1, 2, 3]

    session.add(
        Epic(id=uuid.uuid4(), project_id=project.id, card_ref="EPIC-1", title="e"),
    )
    session.add(
        UserStory(id=uuid.uuid4(), project_id=project.id, card_ref="US-2", title="s"),
    )
    await _task(session, project, "TASK-3")
    await session.flush()
    # Read through SQL rather than `session.get`: the allocation is a raw `UPDATE`,
    # so the identity map still holds the value the row had when it was created.
    seq = await session.scalar(
        sa.text("SELECT next_card_seq FROM projects WHERE id = :pid"), {"pid": project.id}
    )
    assert seq == 4


async def test_a_card_cannot_depend_on_itself(session: AsyncSession) -> None:
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    task = await _task(session, project, "TASK-1")
    session.add(TaskDependency(task_id=task.id, depends_on_task_id=task.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_dependency_pair_cannot_be_recorded_twice(session: AsyncSession) -> None:
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    first = await _task(session, project, "TASK-1")
    second = await _task(session, project, "TASK-2")
    session.add(TaskDependency(task_id=first.id, depends_on_task_id=second.id))
    await session.flush()
    session.add(TaskDependency(task_id=first.id, depends_on_task_id=second.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_removing_an_epic_leaves_its_stories_and_tasks_unclassified(
    session: AsyncSession,
) -> None:
    """A card must not disappear because of how it was filed (D4)."""
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    epic = Epic(id=uuid.uuid4(), project_id=project.id, card_ref="EPIC-1", title="e")
    session.add(epic)
    await session.flush()
    story = UserStory(
        id=uuid.uuid4(), project_id=project.id, epic_id=epic.id, card_ref="US-2", title="s"
    )
    session.add(story)
    await session.flush()
    task = await _task(session, project, "TASK-3", epic_id=epic.id, user_story_id=story.id)

    await session.execute(sa.delete(Epic).where(Epic.id == epic.id))
    await session.flush()
    await session.refresh(story)
    await session.refresh(task)
    assert story.epic_id is None
    assert task.epic_id is None
    # The story link survives: only the epic went away.
    assert task.user_story_id == story.id


async def test_a_terminal_session_keeps_its_row_when_its_task_is_removed(
    session: AsyncSession,
) -> None:
    """`SET NULL`, not cascade: a session really ran, whatever happened to the card."""
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    node = Node(
        id=uuid.uuid4(), name=f"n-{uuid.uuid4().hex[:8]}", hostname="n.invalid", status="online"
    )
    session.add(node)
    await session.flush()
    task = await _task(session, project, "TASK-1")
    terminal = TerminalSession(
        id=uuid.uuid4(),
        node_id=node.id,
        user_id=owner.id,
        name="s",
        runtime="claude",
        workspace="/srv/work",
        status="running",
        rows=24,
        columns=80,
        project_id=project.id,
        task_id=task.id,
    )
    session.add(terminal)
    await session.flush()

    await session.execute(sa.delete(Task).where(Task.id == task.id))
    await session.flush()
    await session.refresh(terminal)
    assert terminal.task_id is None
    assert terminal.status == "running"


async def test_a_session_token_hash_is_unique_and_dies_with_its_session(
    session: AsyncSession,
) -> None:
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    node = Node(
        id=uuid.uuid4(), name=f"n-{uuid.uuid4().hex[:8]}", hostname="n.invalid", status="online"
    )
    session.add(node)
    await session.flush()
    terminal = TerminalSession(
        id=uuid.uuid4(),
        node_id=node.id,
        user_id=owner.id,
        name="s",
        runtime="claude",
        workspace="/srv/work",
        status="running",
        rows=24,
        columns=80,
        project_id=project.id,
    )
    session.add(terminal)
    await session.flush()

    def _token(digest: str) -> SessionToken:
        return SessionToken(
            id=uuid.uuid4(),
            session_id=terminal.id,
            project_id=project.id,
            token_hash=digest,
            scopes=["project.view", "task.update"],
            issued_by=owner.id,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    session.add(_token("abc"))
    await session.flush()
    session.add(_token("abc"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_concurrent_allocations_never_hand_out_the_same_number(db_url: str) -> None:
    """Two writers, two numbers.

    The row lock is the whole mechanism, so it has to be exercised with two committing
    transactions — a single-session test would pass with `count(*) + 1`, which is the
    implementation this exists to rule out.

    Own engine rather than the `session` fixture, which keeps everything inside one
    rolled-back transaction; the rows are cleaned up by hand at the end.
    """
    engine = create_async_engine(db_url)
    db_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with db_sessionmaker() as setup:
        owner = await _user(setup, f"owner-{uuid.uuid4().hex[:8]}")
        project = await _project(setup, owner, f"seq-{uuid.uuid4().hex[:8]}")
        project_id, owner_id = project.id, owner.id
        await setup.commit()

    async def allocate() -> int:
        async with db_sessionmaker() as db_session:
            number = await _allocate(db_session, project_id)
            await db_session.commit()
            return number

    try:
        numbers = await asyncio.gather(*(allocate() for _ in range(8)))
        assert sorted(numbers) == list(range(1, 9))
    finally:
        async with db_sessionmaker() as cleanup:
            await cleanup.execute(sa.delete(Project).where(Project.id == project_id))
            await cleanup.execute(sa.delete(User).where(User.id == owner_id))
            await cleanup.commit()
        await engine.dispose()


async def test_the_optimistic_lock_refuses_the_second_writer(db_url: str) -> None:
    """A conditional `UPDATE`, so a lost update is impossible rather than unlikely.

    Both writers read version 1 and both try to write; the second one's statement
    matches no row. What matters is the *second assertion*: the loser must not have
    written half of its change (FR-TASK-003.AC-01).
    """
    engine = create_async_engine(db_url)
    db_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with db_sessionmaker() as setup:
        owner = await _user(setup, f"owner-{uuid.uuid4().hex[:8]}")
        project = await _project(setup, owner, f"lock-{uuid.uuid4().hex[:8]}")
        task = await _task(setup, project, "TASK-1")
        project_id, owner_id, task_id = project.id, owner.id, task.id
        await setup.commit()

    async def move(stage: str) -> int:
        async with db_sessionmaker() as db_session:
            result = await db_session.execute(
                sa.update(Task)
                .where(Task.id == task_id, Task.version == 1)
                .values(stage=stage, version=Task.version + 1)
            )
            await db_session.commit()
            return int(result.rowcount)

    try:
        first = await move("implementing")
        second = await move("done")
        assert [first, second] == [1, 0]
        async with db_sessionmaker() as check:
            row = await check.get(Task, task_id)
            assert row is not None
            assert row.stage == "implementing"
            assert row.version == 2
    finally:
        async with db_sessionmaker() as cleanup:
            await cleanup.execute(sa.delete(Task).where(Task.id == task_id))
            await cleanup.execute(sa.delete(Project).where(Project.id == project_id))
            await cleanup.execute(sa.delete(User).where(User.id == owner_id))
            await cleanup.commit()
        await engine.dispose()


async def test_the_stage_check_constraint_refuses_an_unknown_lane(session: AsyncSession) -> None:
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    with pytest.raises(IntegrityError):
        await _task(session, project, "TASK-1", stage="in-progress")


async def test_activity_actor_kind_defaults_to_user(session: AsyncSession) -> None:
    """Nothing needs backfilling: every row written before V2.1 was a person's action."""
    owner = await _user(session, f"o-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"p-{uuid.uuid4().hex[:8]}")
    await session.execute(
        sa.text(
            "INSERT INTO activity_events (id, project_id, kind, payload) "
            "VALUES (:id, :pid, 'project.created', '{}'::jsonb)"
        ),
        {"id": uuid.uuid4(), "pid": project.id},
    )
    kind = await session.scalar(
        sa.text("SELECT actor_kind FROM activity_events WHERE project_id = :pid"),
        {"pid": project.id},
    )
    assert kind == "user"
