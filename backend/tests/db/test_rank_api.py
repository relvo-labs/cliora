"""Moving a card, and the three ways it can legitimately fail (PX-61, ADR 0042 §5).

The pure ordering algebra is tested without a database in `test_work_ranking.py`. What
needs a database is the part the algebra cannot promise:

* **one move is one `UPDATE tasks`** — asserted by counting statements, because a move
  that renumbers the lane is the design this column replaced;
* **neighbours, not an index** — and what happens when the pair no longer describes a
  gap, which on a shared board is a normal Tuesday rather than an error;
* **rebalancing does not reorder** — the inline valve rewrites every card in the
  project, and it must be invisible.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Project, Role, Task, User
from app.security.passwords import hash_password
from app.services.tasks import TaskService
from app.services.work.ranking import (
    INLINE_REBALANCE_THRESHOLD,
    rank_between,
    rebalanced_ranks,
    validate_rank,
)

pytestmark = pytest.mark.asyncio


async def _admin(client: AsyncClient, maker: async_sessionmaker) -> dict[str, str]:
    username = f"rank-{uuid.uuid4().hex[:8]}"
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
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def _board(
    client: AsyncClient, headers: dict[str, str], count: int
) -> tuple[str, list[dict]]:
    project_id = (
        await client.post(
            "/api/projects", json={"name": f"rank-{uuid.uuid4().hex[:6]}"}, headers=headers
        )
    ).json()["id"]
    cards = []
    for index in range(count):
        response = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": f"card {index}"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        cards.append(response.json()["task"])
    return project_id, cards


async def _order(maker: async_sessionmaker, project_id: str) -> list[str]:
    async with maker() as check:
        return list(
            (
                await check.execute(
                    sa.select(Task.card_ref)
                    .where(Task.project_id == uuid.UUID(project_id))
                    .order_by(Task.rank, Task.id)
                )
            ).scalars()
        )


async def test_a_move_lands_between_the_named_neighbours(api, projects_enabled) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project_id, cards = await _board(client, headers, 4)
    # Created newest-first, so the board reads card 3, 2, 1, 0.
    assert await _order(maker, project_id) == ["TASK-4", "TASK-3", "TASK-2", "TASK-1"]

    moved = cards[3]  # TASK-4, currently first
    response = await client.post(
        f"/api/tasks/{moved['id']}/rank",
        json={
            "version": moved["version"],
            "previous_task_id": cards[1]["id"],  # TASK-2
            "next_task_id": cards[0]["id"],  # TASK-1
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert await _order(maker, project_id) == ["TASK-3", "TASK-2", "TASK-4", "TASK-1"]
    # A move is a write, so the version advances — the browser's next move carries it.
    assert response.json()["version"] == moved["version"] + 1


async def test_a_null_neighbour_means_the_end_of_the_list(api, projects_enabled) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    project_id, cards = await _board(client, headers, 3)
    last = cards[0]  # TASK-1, currently last

    to_top = await client.post(
        f"/api/tasks/{last['id']}/rank",
        json={"version": last["version"], "previous_task_id": None, "next_task_id": cards[2]["id"]},
        headers=headers,
    )
    assert to_top.status_code == 200, to_top.text
    assert (await _order(maker, project_id))[0] == "TASK-1"

    to_bottom = await client.post(
        f"/api/tasks/{last['id']}/rank",
        json={
            "version": to_top.json()["version"],
            "previous_task_id": cards[1]["id"],
            "next_task_id": None,
        },
        headers=headers,
    )
    assert to_bottom.status_code == 200, to_bottom.text
    assert (await _order(maker, project_id))[-1] == "TASK-1"


async def test_one_move_writes_one_row(api, projects_enabled) -> None:
    """The property the column exists for.

    An integer `position` cannot do this — there is no integer between adjacent integers,
    so inserting renumbers the tail. Counted rather than reasoned about, because the
    renumbering version passes every functional test.
    """
    client, maker = api
    headers = await _admin(client, maker)
    project_id, cards = await _board(client, headers, 6)
    before = await _order(maker, project_id)

    async with maker() as check:
        ranks_before = dict(
            (
                await check.execute(
                    sa.select(Task.card_ref, Task.rank).where(
                        Task.project_id == uuid.UUID(project_id)
                    )
                )
            ).all()
        )

    moved = cards[5]
    response = await client.post(
        f"/api/tasks/{moved['id']}/rank",
        json={
            "version": moved["version"],
            "previous_task_id": cards[2]["id"],
            "next_task_id": cards[1]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    async with maker() as check:
        ranks_after = dict(
            (
                await check.execute(
                    sa.select(Task.card_ref, Task.rank).where(
                        Task.project_id == uuid.UUID(project_id)
                    )
                )
            ).all()
        )
    changed = [ref for ref in ranks_before if ranks_before[ref] != ranks_after[ref]]
    assert changed == [moved["card_ref"]], f"one move rewrote {len(changed)} cards"
    assert before != await _order(maker, project_id)


async def test_a_stale_pair_is_refused_and_the_card_does_not_move(api, projects_enabled) -> None:
    """Somebody else reordered. The refusal names the ranks so the board can re-render."""
    client, maker = api
    headers = await _admin(client, maker)
    project_id, cards = await _board(client, headers, 4)
    before = await _order(maker, project_id)

    response = await client.post(
        f"/api/tasks/{cards[3]['id']}/rank",
        # Reversed: `previous` is below `next`, so the pair does not describe a gap.
        json={
            "version": cards[3]["version"],
            "previous_task_id": cards[0]["id"],
            "next_task_id": cards[2]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RANK_NEIGHBOR_STALE"
    assert set(response.json()["error"]["details"]) == {"previous_rank", "next_rank"}
    assert await _order(maker, project_id) == before


async def test_a_neighbour_in_another_project_is_refused(api, projects_enabled) -> None:
    """The check is project membership, not existence.

    A card id from another project is a well-formed uuid that resolves, so "does this
    row exist" would let a cross-project move through — and the ranks of two projects
    have no relationship at all.
    """
    client, maker = api
    headers = await _admin(client, maker)
    _, mine = await _board(client, headers, 2)
    _, theirs = await _board(client, headers, 2)

    response = await client.post(
        f"/api/tasks/{mine[0]['id']}/rank",
        json={
            "version": mine[0]["version"],
            "previous_task_id": theirs[0]["id"],
            "next_task_id": None,
        },
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RANK_NEIGHBOR_STALE"


async def test_a_card_cannot_be_dropped_next_to_itself(api, projects_enabled) -> None:
    client, maker = api
    headers = await _admin(client, maker)
    _, cards = await _board(client, headers, 2)
    response = await client.post(
        f"/api/tasks/{cards[0]['id']}/rank",
        json={
            "version": cards[0]["version"],
            "previous_task_id": cards[0]["id"],
            "next_task_id": None,
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RANK_NEIGHBOR_STALE"


async def test_a_stale_version_is_a_version_conflict_not_a_stale_neighbour(
    api, projects_enabled
) -> None:
    """Two different answers, because they send the reader to two different places.

    "Somebody edited this card" and "somebody moved the cards around it" are not the
    same situation, and a single code would make the board's recovery generic.
    """
    client, maker = api
    headers = await _admin(client, maker)
    _, cards = await _board(client, headers, 3)
    response = await client.post(
        f"/api/tasks/{cards[0]['id']}/rank",
        json={
            "version": cards[0]["version"] + 7,
            "previous_task_id": cards[1]["id"],
            "next_task_id": None,
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_VERSION_CONFLICT"


# --- rebalancing ------------------------------------------------------------------ #


async def _project(session: AsyncSession) -> Project:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"reb-{uuid.uuid4().hex[:8]}"
    owner = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(owner)
    await session.flush()
    slug = f"reb-{uuid.uuid4().hex[:8]}"
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


async def test_rebalancing_keeps_the_order_and_is_idempotent(session: AsyncSession) -> None:
    project = await _project(session)
    ranks = ["a", "ai", "aj", "b", "c"]
    for index, rank in enumerate(ranks):
        session.add(
            Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"TK-{index}",
                title=f"card {index}",
                stage="backlog",
                source="none",
                delivery="none",
                rank=rank,
            )
        )
    await session.flush()
    service = TaskService(session)

    before = list(
        (
            await session.execute(
                sa.select(Task.card_ref)
                .where(Task.project_id == project.id)
                .order_by(Task.rank, Task.id)
            )
        ).scalars()
    )
    written = await service.rebalance(project_id=project.id)
    assert written == len(ranks)
    after = list(
        (
            await session.execute(
                sa.select(Task.card_ref)
                .where(Task.project_id == project.id)
                .order_by(Task.rank, Task.id)
            )
        ).scalars()
    )
    assert after == before
    for value in rebalanced_ranks(len(ranks)):
        validate_rank(value)
    # A second pass writes nothing, which is what makes a scheduled background job safe.
    assert await service.rebalance(project_id=project.id) == 0


async def test_a_project_with_a_long_rank_is_reported_for_rebalancing(
    session: AsyncSession,
) -> None:
    """The threshold is on rank *length*, not on card count.

    Length is what runs out of room: a thousand evenly spaced cards are in better shape
    than ten with forty inserts at the same spot.
    """
    project = await _project(session)
    dense = rank_between("a", "b")
    while len(dense) < 24:
        dense = rank_between("a", dense)
    session.add(
        Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref="TK-long",
            title="deeply nested",
            stage="backlog",
            source="none",
            delivery="none",
            rank=dense,
        )
    )
    await session.flush()
    assert project.id in await TaskService(session).projects_needing_rebalance()
    assert len(dense) < INLINE_REBALANCE_THRESHOLD
