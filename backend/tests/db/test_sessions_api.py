"""HTTP session API against the real schema (P2-06, PRD §11.6).

The daemon round-trip is faked by overriding the `get_registry` dependency; the
offline path uses the real (empty) registry so NODE_OFFLINE is exercised too.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.http.sessions import get_registry
from app.db.models import Node, NodeRuntime, NodeWorkspaceRoot, Role, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-24T00:00:00Z",
        payload=payload,
        success=success,
    )


class FakeRegistry:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return self.connected

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        sid = payload["session_id"]
        if type_ == "session.start":
            return _msg("session.started", node_id, {"session_id": sid, "pid": 7}, success=True)
        return _msg("session.stopped", node_id, {"session_id": sid, "exit_code": 0}, success=True)


@contextmanager
def use_registry(fake: FakeRegistry):
    app.dependency_overrides[get_registry] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)


def _body(node_id: uuid.UUID, **over: object) -> dict:
    body = {
        "node_id": str(node_id),
        "runtime": "claude",
        "name": "s1",
        "workspace": "/home/neil/projects/app",
        "rows": 40,
        "columns": 120,
    }
    body.update(over)
    return body


async def _login(
    client: AsyncClient, maker: async_sessionmaker, *, role_name: str
) -> dict[str, str]:
    username = f"u-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        session.add(
            User(
                username=username,
                password_hash=hash_password("pw"),
                display_name=username,
                role_id=role.id,
            )
        )
        await session.commit()
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _make_node(maker: async_sessionmaker) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


async def test_create_get_and_list(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    node_id = await _make_node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/sessions", json=_body(node_id), headers=headers)
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["status"] == "running"
    assert data["pid"] == 7

    got = await client.get(f"/api/sessions/{data['id']}", headers=headers)
    assert got.status_code == 200
    listed = await client.get("/api/sessions", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1


async def test_create_offline_node_conflict(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    node_id = await _make_node(maker)
    # No registry override → real empty registry → node not connected.
    resp = await client.post("/api/sessions", json=_body(node_id), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NODE_OFFLINE"


async def test_viewer_cannot_create(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Viewer")
    node_id = await _make_node(maker)
    with use_registry(FakeRegistry()):
        resp = await client.post("/api/sessions", json=_body(node_id), headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_viewer_can_view_and_attach(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    viewer = await _login(client, maker, role_name="Viewer")
    node_id = await _make_node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/sessions", json=_body(node_id), headers=admin)
    sid = created.json()["id"]
    assert (await client.get(f"/api/sessions/{sid}", headers=viewer)).status_code == 200
    attach = await client.post(f"/api/sessions/{sid}/attach", headers=viewer)
    assert attach.status_code == 200
    assert attach.json()["ticket"] and attach.json()["session_id"] == sid


async def test_terminate_flow(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    node_id = await _make_node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/sessions", json=_body(node_id), headers=headers)
        sid = created.json()["id"]
        term = await client.post(f"/api/sessions/{sid}/terminate", headers=headers)
    assert term.status_code == 200
    assert term.json()["status"] == "terminated"


async def test_get_unknown_session_404(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    resp = await client.get(f"/api/sessions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_bad_runtime_rejected_422(api: tuple) -> None:
    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    node_id = await _make_node(maker)
    resp = await client.post("/api/sessions", json=_body(node_id, runtime="bash"), headers=headers)
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Per-user session cap (P4-14, tech §23 #14)
# --------------------------------------------------------------------------- #


async def test_a_user_is_capped_across_the_whole_fleet(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap the tech §23 sign-off was designed to find.

    Until P4-14 only `sessions_per_node_max` existed. One account could therefore hold
    `nodes x (per_node - 1)` sessions without ever tripping a limit — a bound that grows
    with the fleet is not a bound. The cap is asserted **across two nodes** precisely
    because a per-node check passes this scenario.
    """
    from app.services import sessions as sessions_service

    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    first_node = await _make_node(maker)
    second_node = await _make_node(maker)

    settings = sessions_service.get_settings()
    monkeypatch.setattr(settings, "sessions_per_user_max", 2, raising=False)

    with use_registry(FakeRegistry()):
        one = await client.post("/api/sessions", json=_body(first_node, name="a"), headers=headers)
        two = await client.post("/api/sessions", json=_body(second_node, name="b"), headers=headers)
        # Third one, on a node with plenty of room — refused by the *user* cap.
        three = await client.post(
            "/api/sessions", json=_body(first_node, name="c"), headers=headers
        )

    assert one.status_code == 201, one.text
    assert two.status_code == 201, two.text
    assert three.status_code == 409, three.text
    assert three.json()["error"]["code"] == "SESSION_LIMIT_REACHED"


async def test_the_cap_is_per_user_not_global(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """One user at their limit must not block anyone else. A global counter here would
    turn a busy colleague into an outage."""
    from app.services import sessions as sessions_service

    client, maker = api
    mine = await _login(client, maker, role_name="Admin")
    theirs = await _login(client, maker, role_name="Developer")
    node_id = await _make_node(maker)

    settings = sessions_service.get_settings()
    monkeypatch.setattr(settings, "sessions_per_user_max", 1, raising=False)

    with use_registry(FakeRegistry()):
        assert (
            await client.post("/api/sessions", json=_body(node_id, name="a"), headers=mine)
        ).status_code == 201
        blocked = await client.post("/api/sessions", json=_body(node_id, name="b"), headers=mine)
        other = await client.post("/api/sessions", json=_body(node_id, name="c"), headers=theirs)

    assert blocked.status_code == 409
    assert other.status_code == 201, other.text


async def test_a_terminated_session_frees_the_users_allowance(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap counts *active* sessions. If ended ones counted, a user would be locked
    out permanently after their twentieth session ever, which is a very different
    product rule from the one intended."""
    from app.services import sessions as sessions_service

    client, maker = api
    headers = await _login(client, maker, role_name="Admin")
    node_id = await _make_node(maker)

    settings = sessions_service.get_settings()
    monkeypatch.setattr(settings, "sessions_per_user_max", 1, raising=False)

    with use_registry(FakeRegistry()):
        created = await client.post("/api/sessions", json=_body(node_id, name="a"), headers=headers)
        assert created.status_code == 201
        assert (
            await client.post("/api/sessions", json=_body(node_id, name="b"), headers=headers)
        ).status_code == 409

        terminated = await client.post(
            f"/api/sessions/{created.json()['id']}/terminate", headers=headers
        )
        assert terminated.status_code == 200, terminated.text

        again = await client.post("/api/sessions", json=_body(node_id, name="c"), headers=headers)
    assert again.status_code == 201, again.text
