"""Project API behaviour over real HTTP (PJ-04, FR-PROJECT-001/002/004/005).

Grouped by the property being defended rather than by endpoint, because several of
these exist to stop a specific regression rather than to describe a feature:

* the flag answers 404 **before** the action guard, so a deployment that never
  enabled the layer does not advertise it;
* a binding is re-authorized on every read, so a root withdrawn after binding shows
  up as unusable rather than as a working shortcut;
* the timeline hides actor identity from anyone without `audit.view`, which is the
  one disclosure this phase could plausibly introduce;
* unbinding does not touch a running session.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    ActivityEvent,
    Node,
    NodeRuntime,
    NodeWorkspaceRoot,
    Role,
    TerminalSession,
    User,
)
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio

ROOT = "/home/neil/projects"
WORKSPACE = f"{ROOT}/app"


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str
) -> tuple[uuid.UUID, dict[str, str]]:
    username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
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
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _node(maker: async_sessionmaker, *, name: str = "vm", root: str = ROOT) -> uuid.UUID:
    async with maker() as session:
        node = Node(name=name, hostname=f"{name}.invalid", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path=root, is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


async def _project(client: AsyncClient, headers: dict[str, str], *, name: str) -> dict:
    resp = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- the feature flag ------------------------------------------------------ #


async def test_every_project_route_is_404_while_the_flag_is_off(
    api: tuple, projects_disabled: None
) -> None:
    """No `projects_enabled` fixture here: this is the default deployment.

    404 rather than 403, and with **no error code** in the body — a code naming the
    project layer would leak exactly what the bare 404 withholds, which is that the
    capability exists and is merely switched off.
    """
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    pid, bid = uuid.uuid4(), uuid.uuid4()

    for method, path in [
        ("GET", "/api/projects"),
        ("POST", "/api/projects"),
        ("GET", f"/api/projects/{pid}"),
        ("PATCH", f"/api/projects/{pid}"),
        ("GET", f"/api/projects/{pid}/activity"),
        ("POST", f"/api/projects/{pid}/workspaces"),
        ("DELETE", f"/api/projects/{pid}/workspaces/{bid}"),
    ]:
        resp = await client.request(method, path, json={}, headers=headers)
        assert resp.status_code == 404, f"{method} {path} → {resp.status_code}"
        assert "PROJECT" not in resp.text.upper(), f"{method} {path} named the feature"


async def test_the_flag_does_not_change_the_mounted_route_set() -> None:
    """The guard is in the handler, never in `include_router`.

    `test_every_mounted_route_is_in_the_matrix` reads the import-time `app.routes`;
    if mounting depended on the flag, that assertion would pass or fail according to
    the environment the suite ran in (ADR 0027 sec 3).
    """
    from tests.test_authz import mounted_routes

    routes = mounted_routes()
    assert ("GET", "/api/projects") in routes
    assert ("DELETE", "/api/projects/{project_id}/workspaces/{binding_id}") in routes


# --- lifecycle ------------------------------------------------------------- #


async def test_slug_is_derived_then_fixed_and_collisions_are_refused(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")

    created = await _project(client, headers, name="Traqora API")
    assert created["slug"] == "traqora-api"

    clash = await client.post(
        "/api/projects", json={"name": "Other", "slug": "traqora-api"}, headers=headers
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "PROJECT_SLUG_TAKEN"

    # `slug` is not an updatable field, so sending one changes nothing rather than
    # silently renaming the thing V2.1 card references will be built on.
    patched = await client.patch(
        f"/api/projects/{created['id']}",
        json={"name": "Renamed", "slug": "something-else"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json() == {**patched.json(), "slug": "traqora-api", "name": "Renamed"}


async def test_owner_is_the_caller_and_never_the_request_body(
    api: tuple, projects_enabled: None
) -> None:
    """The same rule `session.create` follows for `user_id`."""
    client, maker = api
    admin_id, headers = await _actor(client, maker, "Admin")
    someone_else = uuid.uuid4()

    resp = await client.post(
        "/api/projects",
        json={"name": "Owned", "owner_user_id": str(someone_else)},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["owner_user_id"] == str(admin_id)


async def test_archived_projects_refuse_new_bindings_and_keep_everything_else(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, headers, name="Archived")

    archived = await client.patch(
        f"/api/projects/{project['id']}", json={"status": "archived"}, headers=headers
    )
    assert archived.status_code == 200

    bind = await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"node_id": str(node_id), "path": WORKSPACE},
        headers=headers,
    )
    assert bind.status_code == 409
    assert bind.json()["error"]["code"] == "PROJECT_ARCHIVED"

    # Reading and renaming still work: archiving is not deletion.
    assert (await client.get(f"/api/projects/{project['id']}", headers=headers)).status_code == 200
    assert (
        await client.patch(
            f"/api/projects/{project['id']}", json={"name": "Still editable"}, headers=headers
        )
    ).status_code == 200


# --- bindings -------------------------------------------------------------- #


async def test_binding_is_idempotent_and_refuses_paths_outside_the_allowed_roots(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, headers, name="Bindings")
    url = f"/api/projects/{project['id']}/workspaces"

    first = await client.post(
        url, json={"node_id": str(node_id), "path": WORKSPACE}, headers=headers
    )
    assert first.status_code == 200
    second = await client.post(
        url, json={"node_id": str(node_id), "path": WORKSPACE}, headers=headers
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"], "a repeat bind created a second row"

    outside = await client.post(
        url, json={"node_id": str(node_id), "path": "/etc"}, headers=headers
    )
    assert outside.status_code == 400
    # Reuses the existing code rather than inventing a synonym, so "why is this path
    # not allowed" has one answer wherever it is asked.
    assert outside.json()["error"]["code"] == "WORKSPACE_OUTSIDE_ALLOWED_ROOT"


async def test_a_binding_is_re_authorized_on_every_read(api: tuple, projects_enabled: None) -> None:
    """Bind legally, withdraw the root, read again.

    This is the whole of "a binding is a shortcut, never an authorization": the row
    is unchanged, but the verdict is recomputed from the node as it is *now*.
    """
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, headers, name="Revalidated")

    bound = await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"node_id": str(node_id), "path": WORKSPACE},
        headers=headers,
    )
    assert bound.status_code == 200
    assert bound.json()["usability"] in {"usable", "node_offline"}

    async with maker() as session:
        await session.execute(
            sa.update(NodeWorkspaceRoot)
            .where(NodeWorkspaceRoot.node_id == node_id)
            .values(is_enabled=False)
        )
        await session.commit()

    detail = await client.get(f"/api/projects/{project['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["workspaces"][0]["usability"] == "outside_allowed_root"


async def test_soft_deleted_nodes_drop_out_of_the_listing_but_keep_their_row(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, headers, name="Softdelete")
    await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"node_id": str(node_id), "path": WORKSPACE},
        headers=headers,
    )

    async with maker() as session:
        await session.execute(
            sa.update(Node).where(Node.id == node_id).values(deleted_at=sa.func.now())
        )
        await session.commit()

    detail = await client.get(f"/api/projects/{project['id']}", headers=headers)
    assert detail.json()["workspaces"] == []
    assert detail.json()["status"] == "active", "the project must survive its node"

    async with maker() as session:
        # Exit condition 4: the binding disappeared from the response because the
        # service filters, not because the row went away.
        surviving = (
            await session.execute(
                sa.text("SELECT count(*) FROM project_workspaces WHERE project_id = :p"),
                {"p": str(project["id"])},
            )
        ).scalar_one()
    assert surviving == 1

    # A restore/re-enrollment workflow may reactivate the same node identity by
    # clearing its soft-delete marker. The binding is a filtered row, not deleted
    # data, so it must immediately reappear without being recreated.
    async with maker() as session:
        await session.execute(sa.update(Node).where(Node.id == node_id).values(deleted_at=None))
        await session.commit()

    restored = await client.get(f"/api/projects/{project['id']}", headers=headers)
    assert restored.status_code == 200
    assert [row["path"] for row in restored.json()["workspaces"]] == [WORKSPACE]


async def test_unbinding_leaves_a_running_session_untouched(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 3. Unbinding says "stop offering this path here", not "stop
    the work"."""
    client, maker = api
    actor_id, headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, headers, name="Unbind")
    bound = await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"node_id": str(node_id), "path": WORKSPACE},
        headers=headers,
    )
    binding_id = bound.json()["id"]

    async with maker() as session:
        row = TerminalSession(
            node_id=node_id,
            user_id=actor_id,
            name="live",
            runtime="claude",
            workspace=WORKSPACE,
            status="running",
            project_id=uuid.UUID(project["id"]),
        )
        session.add(row)
        await session.commit()
        session_id = row.id

    deleted = await client.delete(
        f"/api/projects/{project['id']}/workspaces/{binding_id}", headers=headers
    )
    assert deleted.status_code == 204

    async with maker() as session:
        after = await session.get(TerminalSession, session_id)
        assert after is not None
        assert after.status == "running"
        assert after.project_id == uuid.UUID(project["id"])


# --- the activity timeline ------------------------------------------------- #


async def test_the_timeline_hides_actor_identity_without_audit_view(
    api: tuple, projects_enabled: None
) -> None:
    """`project.view` is held by all three roles, so this is the one place V2.0 could
    hand a Viewer an actor feed. Admin sees the name; Viewer sees the event."""
    client, maker = api
    _, admin_headers = await _actor(client, maker, "Admin")
    node_id = await _node(maker)
    project = await _project(client, admin_headers, name="Timeline")
    await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"node_id": str(node_id), "path": WORKSPACE},
        headers=admin_headers,
    )

    as_admin = await client.get(f"/api/projects/{project['id']}/activity", headers=admin_headers)
    assert as_admin.status_code == 200
    assert as_admin.json()["actors_hidden"] is False
    assert any(item["actor_name"] for item in as_admin.json()["items"])

    _, viewer_headers = await _actor(client, maker, "Viewer")
    as_viewer = await client.get(f"/api/projects/{project['id']}/activity", headers=viewer_headers)
    assert as_viewer.status_code == 200
    body = as_viewer.json()
    assert body["actors_hidden"] is True
    assert [i["kind"] for i in body["items"]] == [i["kind"] for i in as_admin.json()["items"]]
    assert all(i["actor_id"] is None and i["actor_name"] is None for i in body["items"])


async def test_activity_payloads_cannot_carry_forbidden_keys(
    api: tuple, projects_enabled: None
) -> None:
    """The audit module's ban list guards this table too.

    The timeline's audience is *wider* than the audit trail's, so its content rules
    can only be tighter. Enforced rather than reviewed, because V2.2 will have agents
    writing here.
    """
    from app.services.activity import ActivityService

    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    project = await _project(client, headers, name="Payload")

    async with maker() as session:
        service = ActivityService(session)
        with pytest.raises(ValueError, match="forbidden keys"):
            await service.record(
                "project.updated",
                project_id=uuid.UUID(project["id"]),
                payload={"password": "hunter2"},
            )
        with pytest.raises(ValueError, match="unknown activity kind"):
            await service.record("project.exploded", project_id=uuid.UUID(project["id"]))


async def test_activity_paginates_without_losing_rows(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    project = await _project(client, headers, name="Paged")

    async with maker() as session:
        session.add_all(
            [
                ActivityEvent(
                    project_id=uuid.UUID(project["id"]),
                    kind="project.updated",
                    activity_payload={"n": i},
                )
                for i in range(30)
            ]
        )
        await session.commit()

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"limit": 10}
        if cursor:
            params["before"] = cursor
        page = await client.get(
            f"/api/projects/{project['id']}/activity", params=params, headers=headers
        )
        assert page.status_code == 200
        body = page.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_before"]
        if cursor is None:
            break

    # 30 seeded + 1 from creating the project.
    assert len(seen) == 31
    assert len(set(seen)) == 31


async def test_a_malformed_cursor_is_the_callers_fault(api: tuple, projects_enabled: None) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    project = await _project(client, headers, name="Cursor")

    resp = await client.get(
        f"/api/projects/{project['id']}/activity", params={"before": "not-base64"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_QUERY"


async def test_one_project_spans_two_nodes(api: tuple, projects_enabled: None) -> None:
    """Exit condition 1: the point of a project is that it is not one machine.

    Two nodes with *different* allowed roots, so the binding pair cannot pass by
    accident on a shared path — which is also why `run-stack.sh`'s second node
    (`E2E_SECOND_NODE`) gets its own workspace root rather than a second mount of
    the first.
    """
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    first = await _node(maker, name="vm-a", root="/srv/a")
    second = await _node(maker, name="vm-b", root="/opt/b")
    project = await _project(client, headers, name="Spanning")
    url = f"/api/projects/{project['id']}/workspaces"

    a = await client.post(
        url, json={"node_id": str(first), "path": "/srv/a/app", "is_primary": True}, headers=headers
    )
    b = await client.post(url, json={"node_id": str(second), "path": "/opt/b/ci"}, headers=headers)
    assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)

    detail = (await client.get(f"/api/projects/{project['id']}", headers=headers)).json()
    assert detail["node_count"] == 2
    assert detail["workspace_count"] == 2
    assert {w["node_name"] for w in detail["workspaces"]} == {"vm-a", "vm-b"}
    # Primary first, then creation order — so the list has a stable, meaningful head.
    assert detail["workspaces"][0]["is_primary"] is True
    assert detail["workspaces"][0]["node_name"] == "vm-a"

    # Each binding is judged against *its own* node: a path legal on one machine
    # says nothing about the other.
    assert all(w["usability"] in {"usable", "node_offline"} for w in detail["workspaces"])

    listed = (await client.get("/api/projects", headers=headers)).json()
    row = next(item for item in listed if item["id"] == project["id"])
    assert (row["node_count"], row["workspace_count"]) == (2, 2)


async def test_a_binding_is_judged_against_its_own_node(api: tuple, projects_enabled: None) -> None:
    """Withdraw one node's root; the other node's binding is unaffected.

    The failure this guards against is a single node lookup reused for every row,
    which would make one machine's state speak for the whole project.
    """
    client, maker = api
    _, headers = await _actor(client, maker, "Admin")
    first = await _node(maker, name="vm-c", root="/srv/c")
    second = await _node(maker, name="vm-d", root="/opt/d")
    project = await _project(client, headers, name="Independent")
    url = f"/api/projects/{project['id']}/workspaces"
    await client.post(url, json={"node_id": str(first), "path": "/srv/c/app"}, headers=headers)
    await client.post(url, json={"node_id": str(second), "path": "/opt/d/app"}, headers=headers)

    async with maker() as session:
        await session.execute(
            sa.update(NodeWorkspaceRoot)
            .where(NodeWorkspaceRoot.node_id == first)
            .values(is_enabled=False)
        )
        await session.commit()

    detail = (await client.get(f"/api/projects/{project['id']}", headers=headers)).json()
    verdicts = {w["node_name"]: w["usability"] for w in detail["workspaces"]}
    assert verdicts["vm-c"] == "outside_allowed_root"
    assert verdicts["vm-d"] in {"usable", "node_offline"}
