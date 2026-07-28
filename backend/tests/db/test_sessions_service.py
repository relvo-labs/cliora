"""DB-backed tests for the session domain service (P2-05).

Uses the rolled-back `session` fixture and a fake connection registry so the
state machine, guards, and daemon round-trip are exercised against the real
schema without a live daemon.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.api.errors import ApiError
from app.db.models import (
    AuditLog,
    Node,
    NodeRuntime,
    NodeWorkspaceRoot,
    Role,
    TerminalSession,
    User,
)
from app.protocol import ControlMessage
from app.security.passwords import hash_password
from app.services import audit
from app.services.nodes import NodeManagementService
from app.services.sessions import FAILED, RUNNING, TERMINATED, SessionService
from app.settings import Settings

pytestmark = pytest.mark.asyncio


def _msg(
    type_: str, node_id: uuid.UUID, *, success: bool, payload: dict, error=None
) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-24T00:00:00Z",
        payload=payload,
        success=success,
        error=error,
    )


class FakeRegistry:
    """Stands in for NodeConnectionRegistry: presence + correlated request."""

    def __init__(
        self, *, connected: bool = True, start_error=None, start_fail: bool = False
    ) -> None:
        self.connected = connected
        self.start_error = start_error
        self.start_fail = start_fail
        self.sent: list[tuple[str, dict]] = []

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return self.connected

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        self.sent.append((type_, payload))
        if type_ == "session.start":
            if self.start_error is not None:
                raise self.start_error
            if self.start_fail:
                return _msg(
                    "session.start_failed",
                    node_id,
                    success=False,
                    payload={"session_id": payload["session_id"]},
                    error={"code": "SESSION_START_FAILED", "message": "boom"},
                )
            return _msg(
                "session.started",
                node_id,
                success=True,
                payload={"session_id": payload["session_id"], "pid": 4242},
            )
        if type_ == "session.stop":
            return _msg(
                "session.stopped",
                node_id,
                success=True,
                payload={"session_id": payload["session_id"], "exit_code": 0, "forced": False},
            )
        return _msg("error", node_id, success=False, payload={})


async def _seed(session, *, runtime="claude", root="/home/neil/projects", enabled_node=True):
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    user = User(
        username=f"dev-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("pw"),
        display_name="dev",
        role_id=role.id,
    )
    session.add(user)
    node = Node(name="vm-1", hostname="vm-1", status="online", is_enabled=enabled_node)
    node.runtimes = [NodeRuntime(runtime=runtime, available=True)]
    node.workspace_roots = [NodeWorkspaceRoot(path=root, display_name="proj", is_enabled=True)]
    session.add(node)
    await session.flush()
    return user.id, node.id


async def test_create_success_transitions_to_running(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(session, registry=FakeRegistry())
    result = await svc.create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name="s1",
        workspace="/home/neil/projects/app",
        rows=40,
        columns=120,
    )
    assert result.status == RUNNING
    assert result.pid == 4242
    assert result.started_at is not None


async def test_create_on_offline_node_rejected(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(session, registry=FakeRegistry(connected=False))
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s1",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "NODE_OFFLINE"
    # No STARTING row should linger for an offline node.
    rows = (await session.execute(sa.select(TerminalSession))).scalars().all()
    assert rows == []


async def test_create_disabled_node_rejected(session) -> None:
    user_id, node_id = await _seed(session, enabled_node=False)
    svc = SessionService(session, registry=FakeRegistry())
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s1",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "NODE_DISABLED"


async def test_create_missing_runtime_rejected(session) -> None:
    user_id, node_id = await _seed(session, runtime="claude")
    svc = SessionService(session, registry=FakeRegistry())
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="codex",
            name="s1",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "RUNTIME_NOT_FOUND"


async def test_workspace_prefix_collision_rejected(session) -> None:
    user_id, node_id = await _seed(session, root="/home/neil/projects")
    svc = SessionService(session, registry=FakeRegistry())
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s1",
            workspace="/home/neil/projects-other/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "WORKSPACE_OUTSIDE_ALLOWED_ROOT"


async def test_start_timeout_marks_failed_and_raises(session) -> None:
    user_id, node_id = await _seed(session)
    timeout = ApiError("REQUEST_TIMEOUT", "no answer", 504)
    svc = SessionService(session, registry=FakeRegistry(start_error=timeout))
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s1",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "REQUEST_TIMEOUT"
    row = (await session.execute(sa.select(TerminalSession))).scalars().one()
    assert row.status == FAILED
    assert row.error_message == "REQUEST_TIMEOUT"


async def test_start_failure_marks_failed(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(session, registry=FakeRegistry(start_fail=True))
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s1",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "SESSION_START_FAILED"
    row = (await session.execute(sa.select(TerminalSession))).scalars().one()
    assert row.status == FAILED


async def test_session_limit_reached(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(
        session, registry=FakeRegistry(), settings=Settings(sessions_per_node_max=1)
    )
    await svc.create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name="s1",
        workspace="/home/neil/projects/app",
        rows=24,
        columns=80,
    )
    with pytest.raises(ApiError) as exc:
        await svc.create(
            actor_id=user_id,
            node_id=node_id,
            runtime="claude",
            name="s2",
            workspace="/home/neil/projects/app",
            rows=24,
            columns=80,
        )
    assert exc.value.code == "SESSION_LIMIT_REACHED"


async def test_terminate_transitions_to_terminated(session) -> None:
    user_id, node_id = await _seed(session)
    registry = FakeRegistry()
    svc = SessionService(session, registry=registry)
    created = await svc.create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name="s1",
        workspace="/home/neil/projects/app",
        rows=24,
        columns=80,
    )
    assert created.status == RUNNING
    terminated = await svc.terminate(actor_id=user_id, session_id=created.id)
    assert terminated.status == TERMINATED
    assert terminated.ended_at is not None
    assert ("session.stop", {"session_id": str(created.id)}) in registry.sent


async def test_apply_status_changed_running_to_exited(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(session, registry=FakeRegistry())
    created = await svc.create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name="s1",
        workspace="/home/neil/projects/app",
        rows=24,
        columns=80,
    )
    updated = await svc.apply_status_changed(created.id, "exited", exit_code=0)
    assert updated is not None
    assert updated.status == "exited"
    assert updated.exit_code == 0
    assert updated.ended_at is not None
    # Illegal transition (already terminal) is ignored, not raised.
    assert await svc.apply_status_changed(created.id, "running") is None


async def test_terminate_already_ended_rejected(session) -> None:
    user_id, node_id = await _seed(session)
    svc = SessionService(session, registry=FakeRegistry())
    created = await svc.create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name="s1",
        workspace="/home/neil/projects/app",
        rows=24,
        columns=80,
    )
    await svc.terminate(actor_id=user_id, session_id=created.id)
    with pytest.raises(ApiError) as exc:
        await svc.terminate(actor_id=user_id, session_id=created.id)
    assert exc.value.code == "SESSION_INVALID_STATE"


async def _running_session(session, user_id, node_id, name: str) -> TerminalSession:
    return await SessionService(session, registry=FakeRegistry()).create(
        actor_id=user_id,
        node_id=node_id,
        runtime="claude",
        name=name,
        workspace="/home/neil/projects/app",
        rows=24,
        columns=80,
    )


async def test_disabling_a_node_leaves_running_sessions_alone_by_default(session) -> None:
    """FR-NODE-005: disabling stops new work. Whether the work already running is
    torn down is the administrator's decision, and the default is to let it finish."""
    user_id, node_id = await _seed(session)
    first = await _running_session(session, user_id, node_id, "s1")
    second = await _running_session(session, user_id, node_id, "s2")

    service = NodeManagementService(session, registry=FakeRegistry())
    await service.set_enabled(node_id, enabled=False, actor_id=user_id)
    await session.flush()

    assert first.status == RUNNING
    assert second.status == RUNNING
    row = await _latest_audit(session, audit.NODE_DISABLE)
    assert row.audit_metadata["terminate_sessions"] is False
    assert row.audit_metadata["sessions_terminated"] == 0


async def test_disabling_a_node_with_the_flag_actually_terminates_its_sessions(
    session,
) -> None:
    """The flag used to be accepted and audited while nothing acted on it, so a
    disable that an administrator believed had cleared the node left every session
    running."""
    user_id, node_id = await _seed(session)
    first = await _running_session(session, user_id, node_id, "s1")
    second = await _running_session(session, user_id, node_id, "s2")

    registry = FakeRegistry()
    service = NodeManagementService(session, registry=registry)
    await service.set_enabled(node_id, enabled=False, actor_id=user_id, terminate_sessions=True)
    await session.flush()

    assert first.status == TERMINATED
    assert second.status == TERMINATED
    # Each one was really asked to stop, not just marked in the database.
    stopped = [payload["session_id"] for type_, payload in registry.sent if type_ == "session.stop"]
    assert sorted(stopped) == sorted([str(first.id), str(second.id)])

    row = await _latest_audit(session, audit.NODE_DISABLE)
    assert row.audit_metadata["terminate_sessions"] is True
    assert row.audit_metadata["sessions_terminated"] == 2


async def test_only_sessions_on_that_node_are_terminated(session) -> None:
    user_id, node_id = await _seed(session)
    mine = await _running_session(session, user_id, node_id, "s1")

    other = Node(name="vm-2", hostname="vm-2", status="online", is_enabled=True)
    other.runtimes = [NodeRuntime(runtime="claude", available=True)]
    other.workspace_roots = [
        NodeWorkspaceRoot(path="/home/neil/projects", display_name="proj", is_enabled=True)
    ]
    session.add(other)
    await session.flush()
    theirs = await _running_session(session, user_id, other.id, "s2")

    await NodeManagementService(session, registry=FakeRegistry()).set_enabled(
        node_id, enabled=False, actor_id=user_id, terminate_sessions=True
    )
    await session.flush()

    assert mine.status == TERMINATED
    assert theirs.status == RUNNING


async def test_one_session_that_will_not_stop_does_not_strand_the_others(session) -> None:
    """A node is disabled because something is wrong with it, so the least likely
    moment for every daemon reply to arrive is exactly this one. One failure must
    not leave the remaining sessions running."""
    user_id, node_id = await _seed(session)
    first = await _running_session(session, user_id, node_id, "s1")
    second = await _running_session(session, user_id, node_id, "s2")

    class StubbornRegistry(FakeRegistry):
        async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
            if type_ == "session.stop" and payload["session_id"] == str(first.id):
                raise ApiError("NODE_TIMEOUT", "no answer", 504)
            return await super().request(
                node_id, type_, payload, timeout_seconds=timeout_seconds, request_id=request_id
            )

    await NodeManagementService(session, registry=StubbornRegistry()).set_enabled(
        node_id, enabled=False, actor_id=user_id, terminate_sessions=True
    )
    await session.flush()

    assert second.status == TERMINATED
    row = await _latest_audit(session, audit.NODE_DISABLE)
    assert row.audit_metadata["sessions_terminated"] == 1


async def test_re_enabling_a_node_never_terminates_anything(session) -> None:
    user_id, node_id = await _seed(session)
    running = await _running_session(session, user_id, node_id, "s1")

    registry = FakeRegistry()
    await NodeManagementService(session, registry=registry).set_enabled(
        node_id, enabled=True, actor_id=user_id, terminate_sessions=True
    )
    await session.flush()

    assert running.status == RUNNING
    assert not [type_ for type_, _ in registry.sent if type_ == "session.stop"]


async def _latest_audit(session, action: str):
    result = await session.execute(
        sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc())
    )
    row = result.scalars().first()
    assert row is not None, f"no {action} audit row"
    return row
