"""The authorization matrix against the real app and schema (P4-03 gate, ADR 0016).

The pure rules and the matrix-consistency checks live in `tests/test_authz.py`
(no database needed). What needs PostgreSQL, and is therefore here:

* the declared matrix matches what the seed migrations actually produced;
* every guarded route, for every role, over real HTTP;
* a refused mutation leaves **nothing** behind — no row changed and no frame
  relayed to the daemon;
* the defect this gate exists to close: a Developer terminating a colleague's
  session;
* the capability flags the UI renders agree with what the server enforces.
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import metrics
from app.api.http.sessions import get_registry
from app.db.models import Node, NodeRuntime, NodeWorkspaceRoot, Role, TerminalSession, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password
from app.services import rbac
from tests.test_authz import ROUTE_ACTIONS

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload=payload,
        success=success,
    )


class RecordingRegistry:
    """Records every daemon call, so a refusal can be *proven* to have relayed
    nothing — the same technique P3 used to prove boundary rejection."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        self.calls.append((type_, payload))
        sid = payload.get("session_id")
        if type_ == "session.start":
            return _msg("session.started", node_id, {"session_id": sid, "pid": 7}, success=True)
        if type_ == "filesystem.list":
            return _msg("filesystem.entries", node_id, {"path": ".", "entries": []}, success=True)
        if type_ == "filesystem.search":
            return _msg(
                "filesystem.search_result",
                node_id,
                {"results": [], "partial": False},
                success=True,
            )
        if type_ == "filesystem.read":
            return _msg(
                "filesystem.content",
                node_id,
                {"success": True, "rel_path": "a.py", "content": "x", "size": 1},
                success=True,
            )
        return _msg("session.stopped", node_id, {"session_id": sid, "exit_code": 0}, success=True)


@contextmanager
def use_registry(fake: RecordingRegistry):
    from app.api.http import files as files_api

    app.dependency_overrides[get_registry] = lambda: fake
    app.dependency_overrides[files_api.get_registry] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)
        app.dependency_overrides.pop(files_api.get_registry, None)


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
    token = resp.json()["tokens"]["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def _node(maker: async_sessionmaker) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


async def _session_row(
    maker: async_sessionmaker, node_id: uuid.UUID, owner_id: uuid.UUID
) -> uuid.UUID:
    async with maker() as db:
        row = TerminalSession(
            node_id=node_id,
            user_id=owner_id,
            name="s",
            runtime="claude",
            workspace="/home/neil/projects/app",
            status="running",
        )
        db.add(row)
        await db.commit()
        return row.id


# --------------------------------------------------------------------------- #
# The declared matrix vs. the database the system actually authorizes against
# --------------------------------------------------------------------------- #


async def test_role_actions_match_the_seeded_database(session) -> None:
    """`ROLE_ACTIONS` is the source of truth; the seeded rows are what the running
    system checks. If they disagree, the declared matrix is fiction."""
    rows = (
        await session.execute(
            sa.select(Role.name, Role.permissions).where(Role.name.in_(rbac.ROLE_ACTIONS))
        )
    ).all()
    seeded = {name: set((perms or {}).get("actions", [])) for name, perms in rows}
    declared = {role: set(actions) for role, actions in rbac.ROLE_ACTIONS.items()}
    assert seeded == declared


async def test_seeded_roles_are_exactly_the_three_documented_roles(session) -> None:
    names = set((await session.execute(sa.select(Role.name))).scalars())
    assert names == set(rbac.ROLE_ACTIONS)


# --------------------------------------------------------------------------- #
# Role x route, exhaustively, over real HTTP
# --------------------------------------------------------------------------- #

_SUB = {
    "/api/sessions": {
        "node_id": None,  # filled per test
        "runtime": "claude",
        "name": "s",
        "workspace": "/home/neil/projects/app",
    },
    "/api/enrollment-tokens": {"name": "vm-1"},
    "/api/nodes/{node_id}/enabled": {"enabled": False},
}
_QUERY = {
    "/api/sessions/{session_id}/files/tree": {"path": "."},
    "/api/sessions/{session_id}/files/search": {"keyword": "x"},
    "/api/sessions/{session_id}/files/content": {"path": "a.py"},
}


@pytest.mark.parametrize("role", sorted(rbac.ROLE_ACTIONS))
async def test_role_matrix_over_every_guarded_route(api: tuple, role: str) -> None:
    """The **action layer**, for every guarded route: a role holding the action must
    not be refused, and a role lacking it must get exactly 403 with the uniform
    code.

    The session is owned by the role under test so the owner layer cannot mask an
    action-layer result — ownership has its own tests below, and conflating the two
    here would let a missing action check hide behind a passing owner check.
    """
    client, maker = api
    owner_id, headers = await _actor(client, maker, role)
    node_id = await _node(maker)
    session_id = await _session_row(maker, node_id, owner_id)
    held = rbac.ROLE_ACTIONS[role]

    substitutions = {
        "{node_id}": str(node_id),
        "{session_id}": str(session_id),
        "{token_id}": str(uuid.uuid4()),
    }
    registry = RecordingRegistry()

    for (method, path), action in sorted(ROUTE_ACTIONS.items()):
        if action is None:
            continue
        url = path
        for token, value in substitutions.items():
            url = url.replace(token, value)
        body = _SUB.get(path)
        if body is not None and "node_id" in body:
            body = {**body, "node_id": str(node_id)}
        with use_registry(registry):
            resp = await client.request(
                method, url, json=body, params=_QUERY.get(path), headers=headers
            )
        if action in held:
            assert resp.status_code != 403, f"{role} holds {action} but {method} {path} → 403"
        else:
            assert resp.status_code == 403, (
                f"{role} lacks {action} but {method} {path} → {resp.status_code}: {resp.text}"
            )
            assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_viewer_forged_mutations_change_nothing(api: tuple) -> None:
    """A Viewer's forged mutation must fail *and* leave no trace: no row created or
    changed, and no frame relayed to the daemon."""
    client, maker = api
    _, viewer = await _actor(client, maker, "Viewer")
    node_id = await _node(maker)
    owner_id, _ = await _actor(client, maker, "Developer")
    session_id = await _session_row(maker, node_id, owner_id)

    registry = RecordingRegistry()
    attempts: list[tuple[str, str, dict | None]] = [
        (
            "POST",
            "/api/sessions",
            {
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "x",
                "workspace": "/home/neil/projects/app",
            },
        ),
        ("POST", f"/api/sessions/{session_id}/terminate", None),
        ("DELETE", f"/api/sessions/{session_id}", None),
        ("POST", f"/api/nodes/{node_id}/enabled", {"enabled": False}),
        ("POST", f"/api/nodes/{node_id}/credential/revoke", None),
        ("POST", f"/api/nodes/{node_id}/credential/rotate", None),
        ("DELETE", f"/api/nodes/{node_id}", None),
        ("POST", "/api/enrollment-tokens", {"name": "vm"}),
        ("GET", "/api/enrollment-tokens", None),
    ]
    with use_registry(registry):
        for method, url, body in attempts:
            resp = await client.request(method, url, json=body, headers=viewer)
            assert resp.status_code == 403, f"{method} {url} → {resp.status_code}"

    assert registry.calls == [], f"a refused request still reached the daemon: {registry.calls}"
    async with maker() as db:
        total = (await db.execute(sa.select(sa.func.count()).select_from(TerminalSession))).scalar()
        assert total == 1
        row = await db.get(TerminalSession, session_id)
        assert row is not None and row.status == "running"
        node = await db.get(Node, node_id)
        assert node is not None and node.is_enabled and node.deleted_at is None


async def test_developer_cannot_terminate_another_users_session(api: tuple) -> None:
    """The defect this gate closes: through P1-P3, `session.terminate` was checked
    without ownership, so any Developer could end any colleague's session."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, _ = await _actor(client, maker, "Developer")
    _, intruder = await _actor(client, maker, "Developer")
    session_id = await _session_row(maker, node_id, owner_id)

    registry = RecordingRegistry()
    with use_registry(registry):
        for method, url in (
            ("POST", f"/api/sessions/{session_id}/terminate"),
            ("DELETE", f"/api/sessions/{session_id}"),
        ):
            resp = await client.request(method, url, headers=intruder)
            assert resp.status_code == 403, f"{method} {url} → {resp.status_code}"
            assert resp.json()["error"]["code"] == "FORBIDDEN"

    assert registry.calls == []
    async with maker() as db:
        row = await db.get(TerminalSession, session_id)
        assert row is not None and row.status == "running"


async def test_owner_and_admin_may_terminate(api: tuple) -> None:
    """The allow side of the same rule — a scope check that only ever denies would
    be indistinguishable from a broken endpoint."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, owner = await _actor(client, maker, "Developer")
    _, admin = await _actor(client, maker, "Admin")

    own = await _session_row(maker, node_id, owner_id)
    with use_registry(RecordingRegistry()):
        resp = await client.post(f"/api/sessions/{own}/terminate", headers=owner)
    assert resp.status_code == 200, resp.text

    # An Admin holds node.manage, so ownership is not required of them.
    other = await _session_row(maker, node_id, owner_id)
    with use_registry(RecordingRegistry()):
        resp = await client.post(f"/api/sessions/{other}/terminate", headers=admin)
    assert resp.status_code == 200, resp.text


async def test_capability_flags_agree_with_enforcement(api: tuple) -> None:
    """The flags the UI renders must match the server's own decision: a mismatch is
    either a hidden control that would have worked, or a visible one that 403s."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, owner = await _actor(client, maker, "Developer")
    _, other = await _actor(client, maker, "Developer")
    _, viewer = await _actor(client, maker, "Viewer")

    for headers, expected in (
        (viewer, {"can_view": True, "can_write": False, "can_terminate": False}),
        (other, {"can_view": True, "can_write": True, "can_terminate": False}),
        (owner, {"can_view": True, "can_write": True, "can_terminate": True}),
    ):
        session_id = await _session_row(maker, node_id, owner_id)
        got = await client.get(f"/api/sessions/{session_id}", headers=headers)
        assert got.status_code == 200, got.text
        caps = got.json()["capabilities"]
        for key, value in expected.items():
            assert caps[key] is value, f"{key}: {caps[key]} != {value}"

        with use_registry(RecordingRegistry()):
            resp = await client.post(f"/api/sessions/{session_id}/terminate", headers=headers)
        assert (resp.status_code != 403) is expected["can_terminate"]


async def test_list_carries_per_row_capabilities(api: tuple) -> None:
    """A Developer may see a colleague's session in the list but not act on it, so
    the row must say so."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, owner = await _actor(client, maker, "Developer")
    _, other = await _actor(client, maker, "Developer")
    await _session_row(maker, node_id, owner_id)

    for headers, can_terminate in ((owner, True), (other, False)):
        listed = await client.get("/api/sessions", headers=headers)
        assert listed.status_code == 200
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["capabilities"]["can_terminate"] is can_terminate
        assert rows[0]["capabilities"]["can_view"] is True


async def test_created_session_reports_its_creators_capabilities(api: tuple) -> None:
    """Regression: the create response was built without the viewer, so a session
    reported that the person who had just created it could do nothing with it. The
    `viewer` argument is required now, but the response shape is asserted here
    because a wrong-but-well-typed default would pass a type check."""
    client, maker = api
    _, owner = await _actor(client, maker, "Developer")
    node_id = await _node(maker)
    with use_registry(RecordingRegistry()):
        created = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=owner,
        )
    assert created.status_code == 201, created.text
    caps = created.json()["capabilities"]
    assert caps == {
        "can_view": True,
        "can_write": True,
        "can_takeover": True,
        "can_terminate": True,
        "can_browse_files": True,
        # A Developer holds `file.upload`, so image drop is offered (ADR 0024 §6).
        "can_upload_files": True,
        # A Developer holds `terminal.shell` and owns this session, so the tab is
        # offered here (ADR 0021 / D7).
        "can_open_shell": True,
    }


async def test_demoted_owner_loses_write_and_terminate(api: tuple) -> None:
    """Permission contraction must actually contract: a Developer demoted to Viewer
    still *owns* their earlier sessions, so an ownership-only rule would keep
    letting them type into a live CLI."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, headers = await _actor(client, maker, "Developer")
    session_id = await _session_row(maker, node_id, owner_id)

    async with maker() as db:
        viewer_role = (await db.execute(sa.select(Role).where(Role.name == "Viewer"))).scalar_one()
        user = await db.get(User, owner_id)
        assert user is not None
        user.role_id = viewer_role.id
        await db.commit()

    got = await client.get(f"/api/sessions/{session_id}", headers=headers)
    assert got.status_code == 200
    caps = got.json()["capabilities"]
    assert caps == {
        "can_view": True,
        "can_write": False,
        "can_takeover": False,
        "can_terminate": False,
        "can_browse_files": True,
        # Contraction reaches the write path too: a demoted owner may still read
        # the workspace but may no longer put a file into it (ADR 0024 §6).
        "can_upload_files": False,
        # Contraction reaches the system terminal too: a demoted owner still owns
        # the session but no longer holds `terminal.shell`.
        "can_open_shell": False,
    }

    registry = RecordingRegistry()
    with use_registry(registry):
        resp = await client.post(f"/api/sessions/{session_id}/terminate", headers=headers)
    assert resp.status_code == 403
    assert registry.calls == []


async def test_deactivated_user_is_refused_on_the_next_request(api: tuple) -> None:
    client, maker = api
    user_id, headers = await _actor(client, maker, "Admin")
    async with maker() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.is_active = False
        await db.commit()
    resp = await client.get("/api/nodes", headers=headers)
    assert resp.status_code == 401


async def test_file_relay_refuses_before_reaching_the_daemon(api: tuple) -> None:
    """`file.browse` plus view access are both required, and a refusal must not
    relay: Central authorizes before it becomes a relay (ADR 0014/0016)."""
    client, maker = api
    node_id = await _node(maker)
    owner_id, _ = await _actor(client, maker, "Developer")
    session_id = await _session_row(maker, node_id, owner_id)

    # No seeded role lacks file.browse, so this needs a purpose-built one. The
    # cleanup is in `finally` because `roles` is deliberately not in the fixture's
    # cleanup list (the seeded roles must survive), so a leak here would break
    # `test_seeded_roles_are_exactly_the_three_documented_roles` for every later run.
    stripped_id = uuid.uuid4()
    username = f"nb-{uuid.uuid4().hex[:8]}"
    try:
        async with maker() as db:
            db.add(
                Role(
                    id=stripped_id,
                    name=f"NoBrowse-{uuid.uuid4().hex[:6]}",
                    permissions={"actions": [rbac.NODE_VIEW]},
                )
            )
            await db.commit()
        async with maker() as db:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password("pw"),
                    display_name=username,
                    role_id=stripped_id,
                )
            )
            await db.commit()
        login = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
        headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

        registry = RecordingRegistry()
        with use_registry(registry):
            for url, params in (
                (f"/api/sessions/{session_id}/files/tree", {"path": "."}),
                (f"/api/sessions/{session_id}/files/search", {"keyword": "x"}),
                (f"/api/sessions/{session_id}/files/content", {"path": "a.py"}),
            ):
                resp = await client.get(url, params=params, headers=headers)
                assert resp.status_code == 403, f"{url} → {resp.status_code}"
        assert registry.calls == []
    finally:
        async with maker() as db:
            await db.execute(sa.delete(User).where(User.username == username))
            await db.execute(sa.delete(Role).where(Role.id == stripped_id))
            await db.commit()


async def test_refusals_are_counted_without_identifying_labels(api: tuple) -> None:
    """`authz_denied_total` makes a probing client or a broken role visible, but it
    must never carry an id or a path: metrics are the one sink with no redaction
    (ADR 0018)."""
    client, maker = api
    metrics.reset()
    node_id = await _node(maker)
    owner_id, _ = await _actor(client, maker, "Developer")
    _, intruder = await _actor(client, maker, "Developer")
    session_id = await _session_row(maker, node_id, owner_id)

    with use_registry(RecordingRegistry()):
        resp = await client.post(f"/api/sessions/{session_id}/terminate", headers=intruder)
    assert resp.status_code == 403

    assert (
        metrics.counter_value(
            metrics.AUTHZ_DENIED_TOTAL,
            action=rbac.SESSION_TERMINATE,
            role="Developer",
            reason="scope",
        )
        == 1
    )
    snapshot = json.dumps(metrics.snapshot())
    forbidden_labels = {"user_id", "session_id", "node_id", "path", "username", "resource"}
    assert not (forbidden_labels & set(re.findall(r"'([a-z_]+)':", snapshot)))
    assert str(session_id) not in snapshot
    assert str(owner_id) not in snapshot
    metrics.reset()
