"""What V2-P1 promised **not** to change (PX-28, plan/26/05 §8).

Five assertions, and each one guards a promise whose breach is invisible from inside the
phase that broke it:

* the run credential reaches **none** of the new endpoints — a read model is a person's
  surface, and an agent holding `project.view` must not gain a cross-project query;
* the three new agent-forbidden fields are actually refused, per field, through the write
  path an agent can reach;
* the RBAC action count is still 27 (D53);
* the wave-0 side-car is **gone**, now that the board it propped up is — the schedule was
  written into a test rather than into a wave number, and this is where it comes due;
* `/board` is **gone too**, one release later than the side-car and for the opposite
  reason: it had callers, so it waited for their count to reach zero (`beta.2`, ADR 0044).

Two assertions left with it: `/board`'s shape and `BoardCardDTO`'s 16 fields. What they
guarded — a card that renders a board stays a summary — is pinned on the replacement, in
`test_work_items_size.py`.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AgentRunner, Node, Project, Role, Task, TaskRun, User
from app.security.passwords import hash_password
from app.services import rbac
from app.services.agent_auth import AGENT_FORBIDDEN_FIELDS, RUN_TOKEN_SCOPES
from app.services.runs import RunTokenService, RunTokenSubject

pytestmark = pytest.mark.asyncio

# Every route the read model added. Listed rather than discovered, because the point is
# that adding a route is a decision about this list too.
NEW_ENDPOINTS = [
    ("GET", "/api/projects/{project_id}/work-items"),
    ("GET", "/api/projects/{project_id}/work-counts"),
    ("GET", "/api/projects/{project_id}/views"),
    ("POST", "/api/projects/{project_id}/views"),
    ("GET", "/api/me/work-items"),
    ("GET", "/api/me/attention-counts"),
    ("POST", "/api/tasks/bulk-update"),
]


async def _admin(client: AsyncClient, maker: async_sessionmaker) -> dict[str, str]:
    username = f"compat-{uuid.uuid4().hex[:8]}"
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
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def _run_token(maker: async_sessionmaker) -> tuple[str, uuid.UUID, uuid.UUID]:
    """A real run credential, with its project and its card."""
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        username = f"rt-{uuid.uuid4().hex[:8]}"
        owner = User(
            id=uuid.uuid4(),
            username=username,
            display_name=username,
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(owner)
        await session.flush()
        slug = f"rt-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            status="active",
            owner_user_id=owner.id,
            next_card_seq=1,
        )
        session.add(project)
        node = Node(id=uuid.uuid4(), name=slug, hostname=f"{slug}.invalid", status="online")
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(), node_id=node.id, name=slug, runtimes=["claude"], labels=[]
        )
        session.add(runner)
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref="TASK-1",
            title="a card",
            stage="ready",
            source="none",
            delivery="none",
        )
        session.add(task)
        await session.flush()
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=project.id,
            seq=1,
            status="running",
            attempt=1,
            runner_id=runner.id,
            source_kind="none",
        )
        session.add(run)
        await session.flush()
        issued = await RunTokenService(session).issue(
            run=RunTokenSubject(
                run_id=run.id,
                project_id=project.id,
                task_id=task.id,
                timeout_seconds=600,
            )
        )
        await session.commit()
        return issued.value, project.id, task.id


async def test_a_run_credential_reaches_none_of_the_new_endpoints(api, projects_enabled) -> None:
    """A read model is a person's surface.

    An agent holds `project.view` for the card it is executing; a cross-project query is a
    different thing entirely, and the run credential is deliberately not a user session
    — `get_agent_principal` never resolves into a `User`, so these routes cannot accept it
    at all.
    """
    client, maker = api
    token, project_id, _ = await _run_token(maker)
    headers = {"Authorization": f"Bearer {token}"}
    for method, template in NEW_ENDPOINTS:
        path = template.format(project_id=project_id)
        response = await client.request(method, path, headers=headers, json={})
        assert response.status_code in (401, 403), (
            f"{method} {path} answered {response.status_code}"
        )


@pytest.mark.parametrize("field", ["is_blocked", "blocking_reason", "rank"])
async def test_an_agent_cannot_write_the_three_new_fields(
    api, projects_enabled, field: str
) -> None:
    """The three V2-P1 additions to `AGENT_FORBIDDEN_FIELDS`, one test each.

    Parameterised rather than combined: an agent that can unblock its own card has cleared
    the dependency gate, and one that can reorder itself has made first-in-first-out
    advisory. Those are two different holes and a combined test would go green if only one
    were closed.
    """
    client, maker = api
    token, _, task_id = await _run_token(maker)
    assert field in AGENT_FORBIDDEN_FIELDS
    response = await client.patch(
        f"/api/agent/runs/tasks/{task_id}",
        json={field: True if field == "is_blocked" else "unknown"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 while the route is elsewhere, 403/422 when it is reached — what must never
    # happen is 200. Asserted as "not success" so the test survives the route moving.
    assert response.status_code >= 400, response.text


async def test_blocking_message_is_deliberately_not_forbidden() -> None:
    """An agent explaining why it is stuck is useful and grants nothing.

    Stated as a test because the natural instinct when adding three fields to a deny list
    is to add the fourth beside them.
    """
    assert "blocking_message" not in AGENT_FORBIDDEN_FIELDS
    assert {"is_blocked", "blocking_reason", "rank"} <= AGENT_FORBIDDEN_FIELDS


async def test_the_run_token_scope_did_not_grow() -> None:
    """Asserted as a set. "It also holds X" is how a scope grows."""
    assert RUN_TOKEN_SCOPES == frozenset({"project.view", "task.update"})


async def test_the_action_count_is_still_twenty_seven() -> None:
    """D53. Six new endpoints and no new action.

    Every one of them answers a question about cards the caller can already read, so a new
    action would only create a role that can see a board but not why anything on it is
    stuck.
    """
    assert len(rbac.ALL_ACTIONS) == 27


async def test_the_side_car_is_gone_now_that_the_v1_board_is(api, projects_enabled) -> None:
    """The scheduled deletion, asserted rather than remembered.

    `plan/26/05` §9 gave `GET /projects/{id}/board-attention` a named owner and a
    condition: it goes when the board it was propping up goes. The plan said wave 2; doing
    it then would have taken the attention badges off the only board that existed, because
    `PX-64` had not replaced `ProjectDetailView.vue` yet. So the condition was written into
    a test instead of a wave number — **and this is that test, flipped**.

    A "temporary" endpoint with nobody assigned to remove it is a permanent one.
    """
    client, maker = api
    headers = await _admin(client, maker)
    created = await client.post("/api/projects", json={"name": "sidecar"}, headers=headers)
    project_id = created.json()["id"]
    response = await client.get(f"/api/projects/{project_id}/board-attention", headers=headers)
    assert response.status_code == 404, response.text

    # And it is out of the schema, not merely unrouted.
    from app.main import app

    assert "/api/projects/{project_id}/board-attention" not in app.openapi()["paths"]


async def test_the_board_endpoint_is_gone(api, projects_enabled) -> None:
    """D118's schedule, come due — the side-car test's twin, flipped the same way.

    `/board` was deprecated in V2-P1 and kept for one version, because after D117 removed
    the version flag it was one of the two degradation paths left if the new board turned
    out to be wrong. It did not, and `beta.2` deletes it (ADR 0044, D126).

    `getBoard()` had **zero call sites** when this was written. That is what made the
    deletion a deletion rather than a migration, and it is the difference between this
    test and the one above it: the side-car was never called from outside the repository,
    while `/board` was — so this one waited for a release and for the count to reach zero.
    """
    from app.main import app

    assert "/api/projects/{project_id}/board" not in app.openapi()["paths"]

    client, maker = api
    headers = await _admin(client, maker)
    created = await client.post("/api/projects", json={"name": "gone"}, headers=headers)
    response = await client.get(f"/api/projects/{created.json()['id']}/board", headers=headers)
    assert response.status_code == 404, response.text


async def test_the_deleted_board_types_are_not_importable() -> None:
    """The DTOs went with the route, not just the route.

    A deleted endpoint whose response model is still importable is a deletion that the
    next person undoes in one line, because the expensive half — agreeing on the shape —
    still looks done. ADR 0044 §2 carries the measurement those types documented.
    """
    import app.api.http.schemas as schemas

    for name in ("BoardCardDTO", "BoardLaneDTO", "BoardDTO"):
        assert not hasattr(schemas, name), f"{name} survived the sunset"

    from app.repositories.tasks import TaskRepository

    assert not hasattr(TaskRepository, "board_cards")
