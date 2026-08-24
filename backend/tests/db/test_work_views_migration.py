"""What `0043` promises about data that already existed (PX-22, ADR 0042).

The migration itself is exercised by `alembic upgrade` in CI; what needs its own tests is
the part a successful upgrade can still get wrong:

* **the board does not reshuffle.** The rank backfill orders by `updated_at DESC, id DESC`
  — word for word `board_cards()` — and `rebalanced_ranks` preserves the order it is
  given. A person upgrading must find their board where they left it, and nothing about a
  green migration says so.
* **every project has views, including one created afterwards.** Two callers, one
  function; the failure mode is a split nobody notices until a customer has projects on
  both sides of the upgrade.
* **the constraints refuse the states they exist to refuse.** A CHECK that is never
  tested is a CHECK somebody removes when it becomes inconvenient.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Role, Task, User, WorkView
from app.security.passwords import hash_password
from app.services.work.ranking import INITIAL_RANK, rebalanced_ranks, validate_rank
from app.services.work.views import DEFAULT_VIEWS, seed_statements

pytestmark = pytest.mark.asyncio


async def _owner(session: AsyncSession) -> User:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"views-{uuid.uuid4().hex[:8]}"
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


async def _project(session: AsyncSession, owner: User) -> Project:
    slug = f"views-{uuid.uuid4().hex[:8]}"
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


# --- the columns ----------------------------------------------------------------- #


async def test_the_model_default_is_the_ranking_modules_initial_rank(
    session: AsyncSession,
) -> None:
    """`db/models.py` writes `'a'` as a literal rather than importing it.

    That is deliberate — models are the bottom of the dependency graph and importing a
    service from there would invert it — so this is what keeps the two equal.
    """
    owner = await _owner(session)
    project = await _project(session, owner)
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref="TK-1",
        title="direct insert",
        stage="backlog",
        source="none",
        delivery="none",
    )
    session.add(task)
    await session.flush()
    assert task.rank == INITIAL_RANK


# --- the rank backfill's promise -------------------------------------------------- #


async def test_the_backfill_ordering_is_the_boards_ordering() -> None:
    """A pure restatement of the property, so it fails in the fast suite too.

    `rebalanced_ranks` preserves input order, and the backfill feeds it
    `ORDER BY updated_at DESC, id DESC`. Therefore ordering by rank afterwards equals
    ordering by `updated_at DESC, id DESC` before — which is what "the board does not
    reshuffle on upgrade" means.
    """
    ranks = rebalanced_ranks(25)
    assert ranks == sorted(ranks)
    for rank in ranks:
        validate_rank(rank)


async def test_ordering_by_rank_matches_the_v1_board_order(session: AsyncSession) -> None:
    owner = await _owner(session)
    project = await _project(session, owner)
    for index in range(12):
        session.add(
            Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"TK-{index}",
                title=f"card {index}",
                stage="backlog",
                source="none",
                delivery="none",
            )
        )
    await session.flush()

    v1_order = list(
        (
            await session.execute(
                sa.select(Task.id)
                .where(Task.project_id == project.id)
                .order_by(Task.updated_at.desc(), Task.id.desc())
            )
        ).scalars()
    )
    ranks = rebalanced_ranks(len(v1_order))
    for task_id, rank in zip(v1_order, ranks, strict=True):
        await session.execute(sa.update(Task).where(Task.id == task_id).values(rank=rank))
    await session.flush()

    by_rank = list(
        (
            await session.execute(
                sa.select(Task.id).where(Task.project_id == project.id).order_by(Task.rank, Task.id)
            )
        ).scalars()
    )
    assert by_rank == v1_order


# --- the constraints -------------------------------------------------------------- #


async def test_a_personal_view_without_an_owner_is_refused(session: AsyncSession) -> None:
    """`ck_work_views_scope`. Without it the permission check is an `if`, not a join."""
    owner = await _owner(session)
    project = await _project(session, owner)
    session.add(
        WorkView(
            id=uuid.uuid4(),
            project_id=project.id,
            owner_user_id=None,
            name="bad",
            layout="list",
            scope="personal",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_project_view_with_an_owner_is_refused(session: AsyncSession) -> None:
    owner = await _owner(session)
    project = await _project(session, owner)
    session.add(
        WorkView(
            id=uuid.uuid4(),
            project_id=project.id,
            owner_user_id=owner.id,
            name="bad",
            layout="list",
            scope="project",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_an_unimplemented_layout_is_still_a_legal_value(session: AsyncSession) -> None:
    """`roadmap` is admitted from the first migration although nothing writes it.

    Same reason `BoardDTO.has_more` exists: a value added later forces every existing
    client to handle its absence.
    """
    owner = await _owner(session)
    project = await _project(session, owner)
    session.add(
        WorkView(
            id=uuid.uuid4(),
            project_id=project.id,
            owner_user_id=None,
            name="future",
            layout="roadmap",
            scope="project",
        )
    )
    await session.flush()


async def test_a_second_default_view_is_refused(session: AsyncSession) -> None:
    """`uq_work_views_default`. This is what makes "change the default" two updates in
    one transaction — the pair the audit entry records — instead of a state the UI has
    to choose between."""
    owner = await _owner(session)
    project = await _project(session, owner)
    for name in ("one", "two"):
        session.add(
            WorkView(
                id=uuid.uuid4(),
                project_id=project.id,
                owner_user_id=None,
                name=name,
                layout="list",
                scope="project",
                is_default=True,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_deleted_views_name_becomes_reusable(session: AsyncSession) -> None:
    """`uq_work_views_name` is partial on `deleted_at IS NULL` — kintra's shape, kept."""
    from app.clock import now_utc

    owner = await _owner(session)
    project = await _project(session, owner)
    session.add(
        WorkView(
            id=uuid.uuid4(),
            project_id=project.id,
            owner_user_id=None,
            name="Sprint",
            layout="list",
            scope="project",
            deleted_at=now_utc(),
        )
    )
    await session.flush()
    session.add(
        WorkView(
            id=uuid.uuid4(),
            project_id=project.id,
            owner_user_id=None,
            name="Sprint",
            layout="list",
            scope="project",
        )
    )
    await session.flush()


# --- the seed --------------------------------------------------------------------- #


async def test_seeding_is_idempotent(session: AsyncSession) -> None:
    """Both callers can reach the same project. The second attempt must be a no-op."""
    owner = await _owner(session)
    project = await _project(session, owner)
    for _ in range(2):
        for statement, params in seed_statements(project_id=project.id):
            await session.execute(statement, params)
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(WorkView)
            .where(WorkView.project_id == project.id)
        )
    ).scalar_one()
    assert count == len(DEFAULT_VIEWS)


async def test_a_project_created_after_the_upgrade_also_has_views(api, projects_enabled) -> None:
    """The half of D101 a migration cannot cover."""
    client, maker = api
    username = f"admin-{uuid.uuid4().hex[:8]}"
    async with maker() as setup:
        role = (await setup.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        setup.add(
            User(
                username=username,
                password_hash=hash_password("pw"),
                display_name=username,
                role_id=role.id,
            )
        )
        await setup.commit()
    login = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    created = await client.post("/api/projects", json={"name": "fresh"}, headers=headers)
    assert created.status_code == 201, created.text
    project_id = uuid.UUID(created.json()["id"])

    async with maker() as check:
        rows = list(
            (
                await check.execute(sa.select(WorkView).where(WorkView.project_id == project_id))
            ).scalars()
        )
    assert {row.name for row in rows} == {view.name for view in DEFAULT_VIEWS}
    assert [row.name for row in rows if row.is_default] == ["Active Work"]
    # Seeded by the platform, so no actor is named. An audit trail that named the
    # creating user would be claiming a person chose these.
    assert all(row.created_by is None and row.owner_user_id is None for row in rows)


async def test_a_new_card_goes_to_the_top_of_its_project(api, projects_enabled) -> None:
    """New cards land where they used to: the V1 board is `updated_at DESC`, and the
    backfill gave the newest card the smallest rank, so "top" is the continuous
    behaviour and "bottom" would put a new card behind a 200-card backlog."""
    client, maker = api
    username = f"admin-{uuid.uuid4().hex[:8]}"
    async with maker() as setup:
        role = (await setup.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        setup.add(
            User(
                username=username,
                password_hash=hash_password("pw"),
                display_name=username,
                role_id=role.id,
            )
        )
        await setup.commit()
    login = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    project_id = (
        await client.post("/api/projects", json={"name": "ranked"}, headers=headers)
    ).json()["id"]

    refs = []
    for index in range(4):
        response = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": f"card {index}"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        refs.append(response.json()["task"]["card_ref"])

    async with maker() as check:
        ordered = list(
            (
                await check.execute(
                    sa.select(Task.card_ref)
                    .where(Task.project_id == uuid.UUID(project_id))
                    .order_by(Task.rank)
                )
            ).scalars()
        )
    assert ordered == list(reversed(refs))
