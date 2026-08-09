"""Node read/manage HTTP API: list, detail, disable, soft-delete (P1-14)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Node, Role, TerminalSession, User
from app.security.passwords import hash_password
from app.security.tokens import issue_access_token
from app.services.enrollment import EnrollmentService
from app.services.nodes import NodeRegistrationService, RegisterNodeInput, RuntimeInput
from app.services.registry import get_node_registry


class _FakeWebSocket:
    async def send_text(self, data: str) -> None:  # pragma: no cover - unused here
        pass

    async def close(self, code: int = 1000) -> None:
        pass


async def _seed_admin(maker: async_sessionmaker, role_name: str = "Admin") -> None:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        session.add(
            User(
                username="u",
                password_hash=hash_password("pw"),
                display_name="u",
                role_id=role.id,
            )
        )
        await session.commit()


async def _seed_node(maker: async_sessionmaker, name: str, *, claude: bool = True) -> uuid.UUID:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        admin = User(
            username=f"a-{name}",
            password_hash=hash_password("pw"),
            display_name="a",
            role_id=role.id,
        )
        session.add(admin)
        await session.flush()
        created = await EnrollmentService(session).create(created_by=admin.id)
        registered = await NodeRegistrationService(session).register(
            created.plaintext,
            RegisterNodeInput(
                name=name,
                hostname=name,
                os="linux",
                os_version="Ubuntu 24.04",
                architecture="amd64",
                daemon_version="1.0.0",
                run_user="neil",
                runtimes=[RuntimeInput(runtime="claude", available=claude)],
            ),
        )
        node_id = registered.node.id
        await session.commit()
        return node_id


async def _login(client, username: str = "u") -> dict[str, str]:
    tokens = (
        await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_list_and_detail_report_offline_status(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker)
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    listed = await client.get("/api/nodes", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "offline"  # no live daemon connection
    assert rows[0]["claude_available"] is True
    assert rows[0]["codex_available"] is False

    detail = await client.get(f"/api/nodes/{node_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["daemon_version"] == "1.0.0"
    assert len(detail.json()["runtimes"]) == 1


async def test_disable_sets_status_disabled(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker)
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    response = await client.post(
        f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert response.json()["is_enabled"] is False


async def test_remove_soft_deletes_and_hides(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker)
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    # Reproduces the user-visible bug: this row used to remain `running` in the
    # Sessions table after its node disappeared.
    async with maker() as session:
        user = (await session.execute(sa.select(User).where(User.username == "u"))).scalar_one()
        running = TerminalSession(
            node_id=node_id,
            user_id=user.id,
            name="must-leave-the-fleet-list",
            runtime="claude",
            workspace="/home/neil/work",
            status="running",
            rows=24,
            columns=80,
        )
        session.add(running)
        await session.commit()
        running_id = running.id

    assert (await client.delete(f"/api/nodes/{node_id}", headers=headers)).status_code == 204
    # Hidden from list and detail...
    assert (await client.get("/api/nodes", headers=headers)).json() == []
    assert (await client.get(f"/api/nodes/{node_id}", headers=headers)).status_code == 404
    assert (await client.get("/api/sessions", headers=headers)).json() == []
    # ...but the row and its audit are retained.
    async with maker() as session:
        node = await session.get(Node, node_id)
        assert node is not None and node.deleted_at is not None
        historical = await session.get(TerminalSession, running_id)
        assert historical is not None
        assert historical.status == "failed"
        assert historical.error_message == "NODE_REMOVED"
        assert historical.ended_at is not None


async def test_viewer_cannot_manage(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker, role_name="Viewer")
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    assert (await client.get("/api/nodes", headers=headers)).status_code == 200  # view allowed
    disable = await client.post(
        f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=headers
    )
    assert disable.status_code == 403
    assert (await client.delete(f"/api/nodes/{node_id}", headers=headers)).status_code == 403
    # Credential endpoints are Admin-only too.
    assert (
        await client.post(f"/api/nodes/{node_id}/credential/revoke", headers=headers)
    ).status_code == 403


async def test_detail_exposes_live_resources_and_update_status(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker)
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    registry = get_node_registry()
    await registry.register(node_id, _FakeWebSocket())
    registry.set_resources(
        node_id, {"cpu_usage": 12.5, "memory_usage": 40.0, "daemon_uptime": 3600}
    )
    try:
        detail = (await client.get(f"/api/nodes/{node_id}", headers=headers)).json()
    finally:
        await registry.evict(node_id)

    assert detail["resources"]["cpu_usage"] == 12.5
    assert detail["resources"]["daemon_uptime"] == 3600
    assert detail["resources"]["disk_usage"] is None
    # P4-10 widened this block. `status` is None because this node has never been
    # asked to update — a different fact from `succeeded` — and `latest_version` is
    # None because no artifacts directory is configured in this test.
    assert detail["update_status"] == {
        "current_version": "1.0.0",
        "latest_version": None,
        "status": None,
        "target_version": None,
        "last_result": None,
        "updated_at": None,
        "auto_update_enabled": False,
    }
    assert detail["recent_errors"] == []


async def test_detail_resources_null_when_offline(api: tuple) -> None:
    client, maker = api
    await _seed_admin(maker)
    node_id = await _seed_node(maker, "vm1")
    headers = await _login(client)

    detail = (await client.get(f"/api/nodes/{node_id}", headers=headers)).json()
    assert detail["resources"] is None


async def test_expired_access_token_returns_token_expired(api: tuple) -> None:
    client, _ = api
    expired = issue_access_token(uuid.uuid4(), "Admin", settings=_expired_settings())
    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def _expired_settings():
    from app.settings import Settings

    return Settings(access_token_ttl_seconds=-1)
