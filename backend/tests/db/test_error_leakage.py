"""A daemon's internal error string never reaches an API response (P4-07, ADR 0014/0017).

P3 established this for the filesystem relay. This extends it to the other two paths
that carry a daemon error outward — session start and daemon update — because the
guarantee is only worth having if it holds everywhere a node's words could travel.

What a daemon puts in an error message is not adversarial, just unguarded: absolute
paths, command lines, systemctl output, tmux internals. Any of it in an HTTP body tells
every user of the console how the node is laid out. So Central maps the code and
answers with the catalog's own wording.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.errors import ApiError
from app.api.http.sessions import get_registry
from app.db.models import Node, NodeRuntime, NodeWorkspaceRoot, Role, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio

# The kind of thing a daemon error message really contains. Every fragment here must be
# absent from the HTTP response.
LEAKY_MESSAGE = (
    "exec /usr/local/lib/node_modules/.bin/claude failed in "
    "/home/deploy/secret-project: tmux server on /tmp/tmux-1000/default "
    "refused (pane_dead_status=127), see /var/log/agentd/agentd.log"
)
LEAK_FRAGMENTS = (
    "/usr/local/lib/node_modules",
    "/home/deploy/secret-project",
    "/tmp/tmux-1000",
    "/var/log/agentd",
    "pane_dead_status",
    "node_modules",
)


def _error_message(node_id: uuid.UUID, code: str) -> ControlMessage:
    return ControlMessage(
        version=1,
        type="error",
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload={},
        success=False,
        error={"code": code, "message": LEAKY_MESSAGE},
    )


class LeakyRegistry:
    """A node that answers every request with a verbose internal failure."""

    def __init__(self, code: str) -> None:
        self.code = code

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        return _error_message(node_id, self.code)

    async def evict(self, node_id: uuid.UUID):
        return None

    def seconds_since_heartbeat(self, node_id: uuid.UUID) -> float | None:
        return 1.0

    def resources_for(self, node_id: uuid.UUID):
        return None


async def _admin(
    client: AsyncClient, maker: async_sessionmaker
) -> tuple[uuid.UUID, dict[str, str]]:
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
        node = Node(
            name="vm",
            hostname="vm.local",
            status="online",
            is_enabled=True,
            architecture="amd64",
            daemon_version="1.3.0",
        )
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


def _assert_no_leak(text: str) -> None:
    for fragment in LEAK_FRAGMENTS:
        assert fragment not in text, f"response leaked {fragment!r}: {text}"
    assert LEAKY_MESSAGE not in text


@pytest.mark.parametrize("code", ["SESSION_START_FAILED", "RUNTIME_NOT_FOUND", "INTERNAL_ERROR"])
async def test_a_failed_session_start_does_not_echo_the_daemon(api: tuple, code: str) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)
    app.dependency_overrides[get_registry] = lambda: LeakyRegistry(code)
    try:
        response = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_registry, None)

    assert response.status_code >= 400
    _assert_no_leak(response.text)
    # And what it *does* say is the catalog's wording for the mapped code.
    from app.api.error_catalog import CATALOG

    body = response.json()
    assert body["error"]["message"] == CATALOG[body["error"]["code"]].message
    # The request id is present so the real detail can be found in the log.
    assert body["request_id"]


async def test_a_failed_update_does_not_echo_the_daemon(api: tuple, tmp_path) -> None:
    """The update path relays a daemon result rather than an error frame, so the
    leak-shaped field is `stage`/`error_code` — neither of which may carry prose."""
    import hashlib

    from app.services import node_update as node_update_module
    from app.services import releases
    from app.settings import Settings, get_settings

    releases.reset_cache()
    content = b"tarball"
    for architecture in ("amd64", "arm64"):
        (tmp_path / f"agentd_1.4.0_linux_{architecture}.tar.gz").write_bytes(content)
    (tmp_path / "checksums.txt").write_text(
        "\n".join(
            f"{hashlib.sha256(content).hexdigest()}  agentd_1.4.0_linux_{a}.tar.gz"
            for a in ("amd64", "arm64")
        )
        + "\n",
        encoding="utf-8",
    )

    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)

    class ResultRegistry(LeakyRegistry):
        async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
            return ControlMessage(
                version=1,
                type="daemon.update_result",
                request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
                node_id=node_id,
                timestamp="2026-07-25T00:00:00Z",
                # A daemon that put its prose in a vocabulary field: the value is not in
                # the closed set, so it must land as `unknown` rather than being echoed.
                payload={"status": LEAKY_MESSAGE, "stage": LEAKY_MESSAGE},
                success=False,
            )

    registry = ResultRegistry("INTERNAL_ERROR")
    original = node_update_module.get_node_registry
    node_update_module.get_node_registry = lambda: registry  # type: ignore[assignment]
    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir=str(tmp_path))
    try:
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": "1.4.0"}, headers=headers
        )
    finally:
        node_update_module.get_node_registry = original  # type: ignore[assignment]
        app.dependency_overrides.pop(get_settings, None)
        releases.reset_cache()

    assert response.status_code == 200, response.text
    _assert_no_leak(response.text)
    assert response.json()["update_status"]["status"] == "unknown"


async def test_an_unexpected_daemon_response_is_a_safe_gateway_error(api: tuple) -> None:
    """Not an error frame and not the expected type: the fallback must still be a
    catalog code with a catalog message, not whatever arrived."""
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)

    class WrongTypeRegistry(LeakyRegistry):
        async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
            return ControlMessage(
                version=1,
                type="session.list_result",
                request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
                node_id=node_id,
                timestamp="2026-07-25T00:00:00Z",
                payload={"detail": LEAKY_MESSAGE},
                success=True,
            )

    app.dependency_overrides[get_registry] = lambda: WrongTypeRegistry("INTERNAL_ERROR")
    try:
        response = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_registry, None)

    assert response.status_code >= 400
    _assert_no_leak(response.text)


async def test_an_offline_node_message_names_no_internal_detail(api: tuple) -> None:
    client, maker = api
    _, headers = await _admin(client, maker)
    node_id = await _node(maker)

    class OfflineRegistry(LeakyRegistry):
        def is_connected(self, node_id: uuid.UUID) -> bool:
            return False

        async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
            raise ApiError("NODE_OFFLINE", "Node is not connected", 409)

    app.dependency_overrides[get_registry] = lambda: OfflineRegistry("NODE_OFFLINE")
    try:
        response = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_registry, None)

    _assert_no_leak(response.text)
