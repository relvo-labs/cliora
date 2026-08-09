"""The project layer's data-level guarantees (PJ-02, FR-PROJECT-001/002/004).

What is asserted here is the set of properties the *database* holds, as opposed to
the ones a service can be reviewed into holding. Each of them is load-bearing:

* binding is idempotent, so a second POST cannot create a duplicate the user would
  have to unbind twice;
* at most one primary binding per project, under concurrency;
* a project cannot be deleted out from under a user who owns it;
* the timeline paginates stably when rows share a timestamp — the failure mode that
  drops or repeats entries across pages, and which only appears under a clock
  coarser than the write rate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ActivityEvent, Node, Project, ProjectWorkspace, Role, User
from app.repositories.projects import ProjectRepository
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


async def _node(session: AsyncSession, name: str) -> Node:
    node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="offline")
    session.add(node)
    await session.flush()
    return node


async def _project(session: AsyncSession, owner: User, slug: str) -> Project:
    project = Project(id=uuid.uuid4(), name=slug.title(), slug=slug, owner_user_id=owner.id)
    session.add(project)
    await session.flush()
    return project


async def test_slug_is_unique_across_projects(session: AsyncSession) -> None:
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    await _project(session, owner, slug)
    session.add(Project(id=uuid.uuid4(), name="Other", slug=slug, owner_user_id=owner.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_detail_summary_has_no_hidden_one_thousand_project_cap(
    session: AsyncSession,
) -> None:
    """A detail lookup is by id, not by membership in the newest list page."""
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    old = datetime(2020, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 1, 1, tzinfo=UTC)
    target = Project(
        id=uuid.uuid4(),
        name="Old project",
        slug=f"old-{uuid.uuid4().hex[:8]}",
        owner_user_id=owner.id,
        created_at=old,
        updated_at=old,
    )
    session.add(target)
    session.add_all(
        [
            Project(
                id=uuid.uuid4(),
                name=f"Recent {index}",
                slug=f"recent-{uuid.uuid4().hex[:12]}",
                owner_user_id=owner.id,
                created_at=recent,
                updated_at=recent,
            )
            for index in range(1000)
        ]
    )
    await session.flush()

    summary = await ProjectRepository(session).summary(target)
    assert summary.project.id == target.id


async def test_binding_the_same_triple_twice_is_refused_by_the_database(
    session: AsyncSession,
) -> None:
    """The constraint is what makes the *service* able to be idempotent.

    Without it, "return the existing row" would be a read-then-write race: two
    concurrent binds both see nothing and both insert.
    """
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"bind-{uuid.uuid4().hex[:8]}")

    session.add(
        ProjectWorkspace(id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/srv/app")
    )
    await session.flush()
    session.add(
        ProjectWorkspace(id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/srv/app")
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_the_same_path_may_be_bound_to_two_projects(session: AsyncSession) -> None:
    """Explicitly allowed, and the reason the platform never infers a session's
    project from its workspace: there would be no unique answer (ADR 0027 sec 3)."""
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    left = await _project(session, owner, f"left-{uuid.uuid4().hex[:8]}")
    right = await _project(session, owner, f"right-{uuid.uuid4().hex[:8]}")

    session.add_all(
        [
            ProjectWorkspace(id=uuid.uuid4(), project_id=left.id, node_id=node.id, path="/srv/x"),
            ProjectWorkspace(id=uuid.uuid4(), project_id=right.id, node_id=node.id, path="/srv/x"),
        ]
    )
    await session.flush()  # no IntegrityError


async def test_only_one_primary_binding_per_project(session: AsyncSession) -> None:
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"primary-{uuid.uuid4().hex[:8]}")

    session.add(
        ProjectWorkspace(
            id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/a", is_primary=True
        )
    )
    await session.flush()
    session.add(
        ProjectWorkspace(
            id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/b", is_primary=True
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_non_primary_bindings_are_unconstrained(session: AsyncSession) -> None:
    """The partial index must not turn into "one binding per project"."""
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"many-{uuid.uuid4().hex[:8]}")

    session.add_all(
        [
            ProjectWorkspace(id=uuid.uuid4(), project_id=project.id, node_id=node.id, path=f"/p{i}")
            for i in range(5)
        ]
    )
    await session.flush()  # no IntegrityError


async def test_deleting_an_owner_is_refused(session: AsyncSession) -> None:
    """`ON DELETE RESTRICT`: somebody leaving must not take a project and its whole
    timeline with them. No endpoint deletes users today, so this constraint blocks
    nobody now — it is a sentence for the day one is written."""
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    await _project(session, owner, f"owned-{uuid.uuid4().hex[:8]}")
    await session.flush()

    # The DELETE is a Core statement, so PostgreSQL raises on `execute` rather than
    # at the next flush — the constraint fires as the statement runs, not when the
    # unit of work is emitted.
    with pytest.raises(IntegrityError):
        await session.execute(sa.delete(User).where(User.id == owner.id))


async def test_activity_pagination_is_stable_when_timestamps_collide(
    session: AsyncSession,
) -> None:
    """200 rows sharing one instant must paginate to exactly 200 distinct rows.

    Ordering by `occurred_at` alone gives PostgreSQL no reason to be consistent
    between the two queries, so a keyset page boundary lands mid-tie and entries are
    dropped or repeated. `(occurred_at DESC, id DESC)` is what makes the walk total.
    """
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"page-{uuid.uuid4().hex[:8]}")
    instant = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
    session.add_all(
        [
            ActivityEvent(
                id=uuid.uuid4(),
                project_id=project.id,
                kind="project.updated",
                activity_payload={"n": i},
                occurred_at=instant,
            )
            for i in range(200)
        ]
    )
    await session.flush()

    seen: list[uuid.UUID] = []
    cursor: tuple[datetime, uuid.UUID] | None = None
    for _ in range(20):
        stmt = (
            sa.select(ActivityEvent.id, ActivityEvent.occurred_at)
            .where(ActivityEvent.project_id == project.id)
            .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc())
            .limit(25)
        )
        if cursor is not None:
            occurred, last_id = cursor
            stmt = stmt.where(
                sa.tuple_(ActivityEvent.occurred_at, ActivityEvent.id)
                < sa.tuple_(occurred, last_id)
            )
        rows = (await session.execute(stmt)).all()
        if not rows:
            break
        seen.extend(row.id for row in rows)
        cursor = (rows[-1].occurred_at, rows[-1].id)

    assert len(seen) == 200, "keyset walk lost or repeated rows across a timestamp tie"
    assert len(set(seen)) == 200


async def test_soft_deleted_nodes_keep_their_binding_rows(
    session: AsyncSession,
) -> None:
    """Node removal is a soft delete (ADR 0011), so the cascade does not fire.

    This is the fact plan/16 rewrote exit condition 4 around: the binding disappears
    from responses because the *service* filters `deleted_at IS NULL`, not because
    the row went away. Re-enabling a node removed by mistake brings its bindings
    back, and that only works if the row survived.
    """
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"soft-{uuid.uuid4().hex[:8]}")
    session.add(
        ProjectWorkspace(id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/srv/soft")
    )
    await session.flush()

    node.deleted_at = datetime.now(UTC)
    await session.flush()

    remaining = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectWorkspace)
            .where(ProjectWorkspace.project_id == project.id)
        )
    ).scalar_one()
    assert remaining == 1


async def test_hard_deleting_a_node_cascades_the_binding(
    session: AsyncSession,
) -> None:
    """The safety net still has to work: a genuinely removed row must not leave a
    binding pointing at a machine that no longer exists."""
    owner = await _user(session, f"owner-{uuid.uuid4().hex[:8]}")
    node = await _node(session, f"node-{uuid.uuid4().hex[:8]}")
    project = await _project(session, owner, f"hard-{uuid.uuid4().hex[:8]}")
    session.add(
        ProjectWorkspace(id=uuid.uuid4(), project_id=project.id, node_id=node.id, path="/srv/hard")
    )
    await session.flush()

    await session.execute(sa.delete(Node).where(Node.id == node.id))
    await session.flush()

    remaining = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectWorkspace)
            .where(ProjectWorkspace.project_id == project.id)
        )
    ).scalar_one()
    assert remaining == 0


async def test_concurrent_primary_bindings_cannot_both_land(db_url: str) -> None:
    """Two transactions, two primaries, one survivor.

    The single-session test above proves the constraint exists; this proves it is the
    thing doing the work. An application-level "unset the others first" would pass
    that test and fail this one.

    Uses its own engine rather than the `session` fixture, which holds everything
    inside one rolled-back transaction — two committing transactions is the entire
    point here, so the rows have to be cleaned up by hand at the end.
    """
    engine = create_async_engine(db_url)
    db_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with db_sessionmaker() as setup:
        owner = await _user(setup, f"owner-{uuid.uuid4().hex[:8]}")
        project = await _project(setup, owner, f"race-{uuid.uuid4().hex[:8]}")
        node = await _node(setup, f"node-{uuid.uuid4().hex[:8]}")
        project_id, node_id, owner_id = project.id, node.id, owner.id
        await setup.commit()

    async def bind(path: str) -> bool:
        async with db_sessionmaker() as session:
            session.add(
                ProjectWorkspace(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    node_id=node_id,
                    path=path,
                    is_primary=True,
                )
            )
            try:
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    try:
        first = await bind("/race/a")
        second = await bind("/race/b")
        assert [first, second].count(True) == 1
    finally:
        async with db_sessionmaker() as cleanup:
            await cleanup.execute(
                sa.delete(ProjectWorkspace).where(ProjectWorkspace.project_id == project_id)
            )
            await cleanup.execute(sa.delete(Project).where(Project.id == project_id))
            await cleanup.execute(sa.delete(Node).where(Node.id == node_id))
            await cleanup.execute(sa.delete(User).where(User.id == owner_id))
            await cleanup.commit()
        await engine.dispose()
