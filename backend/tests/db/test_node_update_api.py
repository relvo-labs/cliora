"""`POST /api/nodes/{id}/update` against the real app and schema (P4-10, ADR 0017).

Two behaviours carry most of the weight here, and both are about not lying about
state:

* **A relay timeout is not a failure.** The daemon restarts during the update, which
  drops the socket the reply was travelling on. Recording that as failed would report
  a rollback that never happened — most often for the updates that actually worked.
* **The refusal path still records.** An offline or busy node must not leave the row
  claiming an update is in progress, and the audit row for the refusal has to survive
  the raised error.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import metrics
from app.api.errors import ApiError
from app.api.http import nodes as nodes_module
from app.db.models import AuditLog, Node, Role, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password
from app.services import audit, releases
from app.services import node_update as node_update_module
from app.services.node_update import FAILED, IN_PROGRESS, ROLLED_BACK, SUCCEEDED
from app.settings import Settings, get_settings

pytestmark = pytest.mark.asyncio

TARGET = "1.4.0"


@pytest.fixture(autouse=True)
def _fresh_release_cache():
    releases.reset_cache()
    yield
    releases.reset_cache()


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    """An artifacts directory holding one published release, wired into settings."""
    content = b"tarball"
    lines = []
    for architecture in ("amd64", "arm64"):
        name = f"agentd_{TARGET}_linux_{architecture}.tar.gz"
        (tmp_path / name).write_bytes(content)
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}")
    (tmp_path / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir=str(tmp_path))
    yield tmp_path
    app.dependency_overrides.pop(get_settings, None)


def _msg(node_id: uuid.UUID, payload: dict, *, success: bool = True) -> ControlMessage:
    return ControlMessage(
        version=1,
        type="daemon.update_result",
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload=payload,
        success=success,
    )


class ReplyingRegistry:
    """A registry whose `request` answers with a canned `daemon.update_result`, or
    raises the ApiError a real one would."""

    def __init__(self, *, payload: dict | None = None, error: ApiError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[tuple[str, dict]] = []

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        self.requests.append((type_, payload))
        if self.error is not None:
            raise self.error
        return _msg(node_id, self.payload or {})

    async def evict(self, node_id: uuid.UUID):
        return None

    def seconds_since_heartbeat(self, node_id: uuid.UUID) -> float | None:
        return 1.0

    def resources_for(self, node_id: uuid.UUID):
        return None


@contextlib.contextmanager
def use_registry(registry: ReplyingRegistry) -> Iterator[None]:
    """Install the fake registry at both places the update path reaches one.

    Two, not one: the service sends the frame and the route builds the response from
    the node's live status. Patching only the first would make the response read from
    the real (empty) registry and report the node offline.
    """
    original_service = node_update_module.get_node_registry
    original_route = nodes_module.get_node_registry
    node_update_module.get_node_registry = lambda: registry  # type: ignore[assignment]
    nodes_module.get_node_registry = lambda: registry  # type: ignore[assignment]
    try:
        yield
    finally:
        node_update_module.get_node_registry = original_service  # type: ignore[assignment]
        nodes_module.get_node_registry = original_route  # type: ignore[assignment]


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
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


async def _node(maker: async_sessionmaker, *, daemon_version: str = "1.3.0") -> uuid.UUID:
    async with maker() as session:
        node = Node(
            name="vm",
            hostname="vm.local",
            status="online",
            is_enabled=True,
            daemon_version=daemon_version,
            architecture="amd64",
        )
        session.add(node)
        await session.commit()
        return node.id


async def _reload(maker: async_sessionmaker, node_id: uuid.UUID) -> Node:
    async with maker() as session:
        return (await session.execute(sa.select(Node).where(Node.id == node_id))).scalar_one()


async def _audit_rows(maker: async_sessionmaker, action: str) -> list[AuditLog]:
    async with maker() as session:
        result = await session.execute(
            sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(result.scalars())


# --------------------------------------------------------------------------- #
# Authorization and input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "allowed"), [("Admin", True), ("Developer", False), ("Viewer", False)]
)
async def test_only_node_manage_may_trigger_an_update(
    api: tuple, artifacts: Path, role: str, allowed: bool
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker, role)
    node_id = await _node(maker)
    registry = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )

    if allowed:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 403
        assert registry.requests == [], "a refused caller still reached the daemon"


async def test_the_request_body_cannot_name_an_artifact(api: tuple, artifacts: Path) -> None:
    """SEC-002 at the HTTP boundary: a client that could name a binary could name any
    binary, so the model has nowhere to put one."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})

    with use_registry(registry):
        await client.post(
            f"/api/nodes/{node_id}/update",
            json={
                "target_version": TARGET,
                "url": "http://evil/agentd",
                "binary_path": "/tmp/agentd",
                "sha256": "deadbeef",
            },
            headers=headers,
        )

    assert registry.requests, "no frame was sent"
    _, payload = registry.requests[0]
    assert set(payload) <= {"target_version", "allow_downgrade"}, payload


async def test_a_version_that_is_not_published_is_refused_without_contacting_the_node(
    api: tuple, artifacts: Path
) -> None:
    """Refusing here turns a five-minute failed update into an immediate, explainable
    error. The daemon re-derives and re-verifies everything regardless — this is
    ergonomics, not the security boundary."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry()

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": "9.9.9"}, headers=headers
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "UPDATE_NOT_ALLOWED"
    assert registry.requests == []
    assert (await _reload(maker, node_id)).update_status is None


async def test_updating_with_nothing_published_is_refused(api: tuple, tmp_path: Path) -> None:
    client, maker = api
    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir=str(tmp_path))
    try:
        _, headers = await _actor(client, maker)
        node_id = await _node(maker)
        with use_registry(ReplyingRegistry()):
            response = await client.post(
                f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "UPDATE_NOT_ALLOWED"


async def test_an_unknown_node_is_404(api: tuple, artifacts: Path) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    with use_registry(ReplyingRegistry()):
        response = await client.post(
            f"/api/nodes/{uuid.uuid4()}/update", json={"target_version": TARGET}, headers=headers
        )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #


async def test_a_successful_update_records_the_new_version_and_two_audit_rows(
    api: tuple, artifacts: Path
) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    node_id = await _node(maker, daemon_version="1.3.0")
    metrics.reset()
    registry = ReplyingRegistry(
        payload={
            "status": SUCCEEDED,
            "stage": "healthcheck",
            "from_version": "1.3.0",
            "to_version": TARGET,
        }
    )

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert response.status_code == 200, response.text

    node = await _reload(maker, node_id)
    assert node.update_status == SUCCEEDED
    assert node.update_target_version == TARGET
    assert node.daemon_version == TARGET
    assert node.update_updated_at is not None and node.update_updated_at.tzinfo is not None

    started = await _audit_rows(maker, audit.DAEMON_UPDATE_STARTED)
    finished = await _audit_rows(maker, audit.DAEMON_UPDATE_RESULT)
    assert len(started) == 1 and len(finished) == 1
    assert started[0].user_id == actor_id
    assert started[0].audit_metadata["target_version"] == TARGET
    assert finished[0].audit_metadata["status"] == SUCCEEDED
    assert metrics.counter_value(metrics.NODE_UPDATE_TOTAL, status=SUCCEEDED) == 1


async def test_the_response_reports_current_latest_and_status(api: tuple, artifacts: Path) -> None:
    """What the node detail page renders: where it is, where it could be, and what
    happened last."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry(
        payload={"status": SUCCEEDED, "stage": "healthcheck", "to_version": TARGET}
    )

    with use_registry(registry):
        body = (
            await client.post(
                f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
            )
        ).json()

    status = body["update_status"]
    assert status["current_version"] == TARGET
    assert status["latest_version"] == TARGET
    assert status["status"] == SUCCEEDED
    assert status["auto_update_enabled"] is False


async def test_a_rolled_back_update_is_recorded_with_its_stage_and_code(
    api: tuple, artifacts: Path
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker, daemon_version="1.3.0")
    registry = ReplyingRegistry(
        payload={
            "status": ROLLED_BACK,
            "stage": "healthcheck",
            "error_code": "UPDATE_HEALTHCHECK_FAILED",
            "from_version": "1.3.0",
            "to_version": TARGET,
        }
    )

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert response.status_code == 200

    node = await _reload(maker, node_id)
    assert node.update_status == ROLLED_BACK
    assert node.update_last_result == "UPDATE_HEALTHCHECK_FAILED"
    # The rollback restored the previous binary, so the recorded version must not move.
    assert node.daemon_version == "1.3.0"
    result = (await _audit_rows(maker, audit.DAEMON_UPDATE_RESULT))[0]
    assert result.audit_metadata["stage"] == "healthcheck"
    assert result.audit_metadata["error_code"] == "UPDATE_HEALTHCHECK_FAILED"


async def test_an_unrecognized_status_lands_as_unknown_not_success(
    api: tuple, artifacts: Path
) -> None:
    """Coercing an unreadable report into `succeeded` would record an update that may
    never have happened."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker, daemon_version="1.3.0")
    registry = ReplyingRegistry(payload={"status": "banana", "stage": "swap"})

    with use_registry(registry):
        await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )

    node = await _reload(maker, node_id)
    assert node.update_status == "unknown"
    assert node.daemon_version == "1.3.0"


# --------------------------------------------------------------------------- #
# The timeout, and refusals
# --------------------------------------------------------------------------- #


async def test_a_relay_timeout_leaves_the_node_in_progress_not_failed(
    api: tuple, artifacts: Path
) -> None:
    """The restart drops the socket the reply was coming back on, so a timeout means
    "no answer yet". Marking it failed would report a rollback that never happened —
    and would do so most often for the updates that succeeded."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry(
        error=ApiError("REQUEST_TIMEOUT", "Node did not respond in time", 504)
    )

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert response.status_code == 200, response.text

    node = await _reload(maker, node_id)
    assert node.update_status == IN_PROGRESS
    assert node.update_target_version == TARGET
    # Only the request was audited; there is no outcome to record yet.
    assert len(await _audit_rows(maker, audit.DAEMON_UPDATE_STARTED)) == 1
    assert await _audit_rows(maker, audit.DAEMON_UPDATE_RESULT) == []


async def test_a_late_result_settles_a_node_stuck_in_progress(api: tuple, artifacts: Path) -> None:
    """The other half of the timeout contract: the daemon reports after its restart,
    and that is what un-sticks the row."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker, daemon_version="1.3.0")

    with use_registry(ReplyingRegistry(error=ApiError("REQUEST_TIMEOUT", "timeout", 504))):
        await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert (await _reload(maker, node_id)).update_status == IN_PROGRESS

    # What `api/ws/nodes.py` does with an unsolicited daemon.update_result.
    from app.services.node_update import NodeUpdateService, outcome_from_payload

    async with maker() as session:
        await NodeUpdateService(session).apply_result(
            node_id,
            outcome_from_payload(
                {"status": SUCCEEDED, "stage": "healthcheck", "to_version": TARGET}
            ),
        )
        await session.commit()

    node = await _reload(maker, node_id)
    assert node.update_status == SUCCEEDED
    assert node.daemon_version == TARGET


async def test_an_offline_node_is_refused_and_the_refusal_is_audited(
    api: tuple, artifacts: Path
) -> None:
    """Nothing was started, so the row must not claim otherwise — and the audit row
    has to survive the raised error, exactly as a failed login's does (P4-04)."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry(error=ApiError("NODE_OFFLINE", "Node is not connected", 409))

    with use_registry(registry):
        response = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NODE_OFFLINE"

    node = await _reload(maker, node_id)
    assert node.update_status == FAILED
    assert node.update_last_result == "NODE_OFFLINE"
    assert len(await _audit_rows(maker, audit.DAEMON_UPDATE_STARTED)) == 1
    result = (await _audit_rows(maker, audit.DAEMON_UPDATE_RESULT))[0]
    assert result.audit_metadata["error_code"] == "NODE_OFFLINE"


async def test_a_second_update_while_one_is_in_progress_is_refused(
    api: tuple, artifacts: Path
) -> None:
    """Two concurrent swaps of the same file would leave the second one's backup
    holding the first one's binary."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)

    with use_registry(ReplyingRegistry(error=ApiError("REQUEST_TIMEOUT", "timeout", 504))):
        await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    registry = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})
    with use_registry(registry):
        second = await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "UPDATE_IN_PROGRESS"
    assert registry.requests == [], "the refused request still reached the daemon"


async def test_allow_downgrade_is_passed_through_only_when_asked_for(
    api: tuple, artifacts: Path
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)

    plain = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})
    with use_registry(plain):
        await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )
    assert "allow_downgrade" not in plain.requests[0][1]

    forced = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})
    with use_registry(forced):
        await client.post(
            f"/api/nodes/{node_id}/update",
            json={"target_version": TARGET, "allow_downgrade": True},
            headers=headers,
        )
    assert forced.requests[0][1]["allow_downgrade"] is True


async def test_the_frame_sent_to_the_daemon_is_a_daemon_update(api: tuple, artifacts: Path) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    registry = ReplyingRegistry(payload={"status": SUCCEEDED, "stage": "healthcheck"})

    with use_registry(registry):
        await client.post(
            f"/api/nodes/{node_id}/update", json={"target_version": TARGET}, headers=headers
        )

    assert registry.requests[0][0] == "daemon.update"
    assert registry.requests[0][1]["target_version"] == TARGET
