"""Session ↔ project association and the feature flag (PJ-05, FR-PROJECT-003/005).

The property under test throughout is that **the ad-hoc path is untouched**. A
session that names no project must behave exactly as it did before the project layer
existed — same fields, same filters, and no timeline row anywhere.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.http.sessions import get_registry
from app.db.models import ActivityEvent, Node, NodeRuntime, NodeWorkspaceRoot, Role, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio

ROOT = "/home/neil/projects"
BOUND = f"{ROOT}/app"


class _Registry:
    """A connected node whose daemon always starts and stops cleanly.

    Needed because `SessionService.create` checks connectivity *before* it resolves
    the project — V1's existing order, deliberately left alone. Without this every
    assertion below would read 409 NODE_OFFLINE and pass or fail for the wrong
    reason.
    """

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        sid = payload["session_id"]
        started = type_ == "session.start"
        return ControlMessage(
            version=1,
            type="session.started" if started else "session.stopped",
            request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
            node_id=node_id,
            timestamp="2026-08-08T00:00:00Z",
            payload={"session_id": sid, **({"pid": 7} if started else {"exit_code": 0})},
            success=True,
        )


@contextmanager
def _connected():
    app.dependency_overrides[get_registry] = _Registry
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def _admin(client: AsyncClient, maker: async_sessionmaker) -> tuple[uuid.UUID, dict]:
    username = f"admin-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password("pw"),
            display_name=username,
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return user_id, {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _node(maker: async_sessionmaker) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm.invalid", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path=ROOT, is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


async def _project_with_binding(client: AsyncClient, headers: dict, node_id: uuid.UUID) -> str:
    created = await client.post("/api/projects", json={"name": "Linked"}, headers=headers)
    project_id = created.json()["id"]
    bound = await client.post(
        f"/api/projects/{project_id}/workspaces",
        json={"node_id": str(node_id), "path": BOUND},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text
    return project_id


async def _activity_kinds(maker: async_sessionmaker, project_id: str) -> list[str]:
    async with maker() as session:
        rows = (
            await session.execute(
                sa.select(ActivityEvent.kind)
                .where(ActivityEvent.project_id == uuid.UUID(project_id))
                .order_by(ActivityEvent.occurred_at)
            )
        ).scalars()
        return list(rows)


async def _ended_actor(maker: async_sessionmaker, project_id: str) -> uuid.UUID | None:
    async with maker() as session:
        return (
            await session.execute(
                sa.select(ActivityEvent.actor_user_id).where(
                    ActivityEvent.project_id == uuid.UUID(project_id),
                    ActivityEvent.kind == "session.ended",
                )
            )
        ).scalar_one()


# --- validation ------------------------------------------------------------ #


async def test_a_workspace_outside_the_projects_bindings_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    """400, and **nothing is created**. A silently dropped `project_id` would only be
    noticed later, as an absence from a timeline."""
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, headers, node_id)

    with _connected():
        resp = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "mismatch",
                "workspace": f"{ROOT}/elsewhere",
                "project_id": project_id,
            },
            headers=headers,
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SESSION_PROJECT_MISMATCH"

    async with maker() as session:
        count = (
            await session.execute(sa.text("SELECT count(*) FROM terminal_sessions"))
        ).scalar_one()
    assert count == 0, "a refused session left a row behind"


async def test_a_subdirectory_of_a_bound_path_is_not_itself_bound(
    api: tuple, projects_enabled: None
) -> None:
    """The comparison is exact equality, not a prefix.

    A prefix match would have several answers under nested bindings, and the timeline
    row has to name one. It would also be a *second* prefix comparison on a path that
    `authorize_workspace` has already prefix-checked — the `/a/projects` versus
    `/a/projects-other` trap, entangled with a different meaning.
    """
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, headers, node_id)

    with _connected():
        resp = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "nested",
                "workspace": f"{BOUND}/backend",
                "project_id": project_id,
            },
            headers=headers,
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SESSION_PROJECT_MISMATCH"


async def test_an_archived_project_refuses_new_sessions(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, headers, node_id)
    await client.patch(f"/api/projects/{project_id}", json={"status": "archived"}, headers=headers)

    with _connected():
        resp = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "archived",
                "workspace": BOUND,
                "project_id": project_id,
            },
            headers=headers,
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROJECT_ARCHIVED"


async def test_an_unknown_project_is_404(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)

    with _connected():
        resp = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "ghost",
                "workspace": BOUND,
                "project_id": str(uuid.uuid4()),
            },
            headers=headers,
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# --- the flag -------------------------------------------------------------- #


async def test_naming_a_project_is_refused_while_the_flag_is_off(
    api: tuple, projects_disabled: None
) -> None:
    """422, not 404: what is rejected is a body field that means nothing in this
    deployment, not a missing route. The field is in the schema either way, because
    the OpenAPI document is static."""
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)

    with _connected():
        resp = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "flagged",
                "workspace": BOUND,
                "project_id": str(uuid.uuid4()),
            },
            headers=headers,
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_features_reports_the_deployment_not_the_person(
    api: tuple, projects_disabled: None
) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)

    off = await client.get("/api/auth/me", headers=headers)
    assert off.json()["features"] == []
    # An Admin still holds `project.manage` with the layer switched off, because seed
    # migrations run unconditionally. That is exactly why the flag cannot live in
    # `permissions`.
    assert "project.manage" in off.json()["permissions"]


async def test_features_lists_projects_when_enabled(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)
    assert (await client.get("/api/auth/me", headers=headers)).json()["features"] == ["projects"]


# --- the ad-hoc path is untouched ------------------------------------------ #


async def test_the_session_list_filters_three_ways(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    actor_id, headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, headers, node_id)

    async with maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO terminal_sessions "
                "(id, node_id, user_id, name, runtime, workspace, status, rows, columns,"
                " project_id)"
                " VALUES (:i1, :n, :u, 'linked', 'claude', :w, 'running', 24, 80, :p),"
                "        (:i2, :n, :u, 'adhoc', 'claude', :w, 'running', 24, 80, NULL)"
            ),
            {
                "i1": str(uuid.uuid4()),
                "i2": str(uuid.uuid4()),
                "n": str(node_id),
                "u": str(actor_id),
                "w": BOUND,
                "p": project_id,
            },
        )
        await session.commit()

    everything = await client.get("/api/sessions", headers=headers)
    assert {s["name"] for s in everything.json()} == {"linked", "adhoc"}

    scoped = await client.get("/api/sessions", params={"project_id": project_id}, headers=headers)
    assert [s["name"] for s in scoped.json()] == ["linked"]

    ad_hoc = await client.get("/api/sessions", params={"project_id": "none"}, headers=headers)
    assert [s["name"] for s in ad_hoc.json()] == ["adhoc"]
    assert ad_hoc.json()[0]["project_id"] is None

    bad = await client.get("/api/sessions", params={"project_id": "banana"}, headers=headers)
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_QUERY"


async def test_an_ad_hoc_session_writes_no_timeline_row_anywhere(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 2's second half. A project existing nearby must not attract
    sessions that never named it."""
    client, maker = api
    actor_id, headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, headers, node_id)

    before = await _activity_kinds(maker, project_id)

    async with maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO terminal_sessions "
                "(id, node_id, user_id, name, runtime, workspace, status, rows, columns)"
                " VALUES (:i, :n, :u, 'adhoc', 'claude', :w, 'running', 24, 80)"
            ),
            {"i": str(uuid.uuid4()), "n": str(node_id), "u": str(actor_id), "w": BOUND},
        )
        await session.commit()

    assert await _activity_kinds(maker, project_id) == before


async def test_session_ended_records_the_person_who_terminated_it(
    api: tuple, projects_enabled: None
) -> None:
    """An Admin ending another user's session must not be rewritten as its owner."""
    client, maker = api
    _, owner_headers = await _admin(client, maker)
    terminator_id, terminator_headers = await _admin(client, maker)
    node_id = await _node(maker)
    project_id = await _project_with_binding(client, owner_headers, node_id)

    with _connected():
        created = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "owned-by-someone-else",
                "workspace": BOUND,
                "project_id": project_id,
            },
            headers=owner_headers,
        )
        ended = await client.post(
            f"/api/sessions/{created.json()['id']}/terminate", headers=terminator_headers
        )

    assert ended.status_code == 200, ended.text
    assert await _ended_actor(maker, project_id) == terminator_id
