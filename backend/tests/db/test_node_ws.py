"""Daemon WS Ed25519 challenge, registration, and heartbeat tests."""

from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import WebSocketDisconnect

from app.api.ws.nodes import node_gateway
from app.db.models import Node, Role, TerminalSession, User
from app.protocol import encode_binary
from app.repositories.nodes import NodeRepository
from app.security.node_keys import signing_message
from app.security.passwords import hash_password
from app.services.enrollment import EnrollmentService
from app.services.nodes import NodeRegistrationService, RegisterNodeInput, RuntimeInput
from app.services.registry import get_node_registry
from app.services.terminal_queue import BrowserChannel
from app.services.terminal_relay import TerminalRelay

RID = "01K0ABCDEFGHJKMNPQRSTVWXYZ"


def _frame(type_: str, node_id: uuid.UUID, payload: dict, request_id: str = RID) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": type_,
            "request_id": request_id,
            "node_id": str(node_id),
            "timestamp": "2026-07-24T01:00:00Z",
            "payload": payload,
        }
    )


class FakeWebSocket:
    def __init__(
        self, node_id: uuid.UUID, private: Ed25519PrivateKey | None, incoming: list[str]
    ) -> None:
        self.node_id, self.private, self._incoming = node_id, private, list(incoming)
        self.sent: list[str] = []
        self.accepted = False
        self.closed: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if (
            self.private is not None
            and self.sent
            and json.loads(self.sent[-1]).get("type") == "node.challenge"
        ):
            challenge = json.loads(self.sent[-1])
            self.private, key = None, self.private
            signature = base64.b64encode(
                key.sign(
                    signing_message(
                        self.node_id, challenge["request_id"], challenge["payload"]["nonce"]
                    )
                )
            ).decode()
            return _frame(
                "node.auth",
                self.node_id,
                {"challenge_id": challenge["request_id"], "signature": signature},
                challenge["request_id"],
            )
        if not self._incoming:
            raise WebSocketDisconnect(1000)
        return self._incoming.pop(0)

    async def receive(self) -> dict:
        # The control loop consumes scripted text frames via receive(); a binary
        # terminal path is covered by the relay tests, not here.
        if not self._incoming:
            return {"type": "websocket.disconnect", "code": 1000}
        return {"type": "websocket.receive", "text": self._incoming.pop(0)}

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    def sent_types(self) -> list[str]:
        return [json.loads(s).get("type") for s in self.sent]


def _register_payload() -> dict:
    return {
        "name": "vm-updated",
        "hostname": "vm-updated.local",
        "os": "linux",
        "os_version": "Ubuntu 24.04",
        "architecture": "amd64",
        "daemon_version": "1.0.0",
        "run_user": "neil",
        "runtimes": [{"runtime": "claude", "available": True, "version": "1.2.3"}],
        "workspace_roots": [{"path": "/home/neil", "is_enabled": True}],
    }


async def _seed_node(maker):
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        admin = User(
            username="admin", password_hash=hash_password("pw"), display_name="a", role_id=role.id
        )
        session.add(admin)
        await session.flush()
        created = await EnrollmentService(session).create(created_by=admin.id)
        registered = await NodeRegistrationService(session).register(
            created.plaintext,
            RegisterNodeInput(
                name="vm",
                hostname="vm",
                os="linux",
                os_version="Ubuntu 24.04",
                architecture="amd64",
                daemon_version="1.0.0",
                run_user="neil",
                public_key=public,
                runtimes=[RuntimeInput(runtime="claude", available=True)],
            ),
        )
        await session.commit()
        return registered.node.id, private


async def test_ws_auth_register_heartbeat_persists(api: tuple) -> None:
    _, maker = api
    node_id, private = await _seed_node(maker)
    ws = FakeWebSocket(
        node_id,
        private,
        [
            _frame("node.register", node_id, _register_payload()),
            _frame("node.heartbeat", node_id, {"daemon_version": "1.0.0", "active_sessions": 0}),
        ],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    assert (
        ws.accepted
        and "node.challenge" in ws.sent_types()
        and "node.authenticated" in ws.sent_types()
        and "node.registered" in ws.sent_types()
    )
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert (
            node is not None
            and node.hostname == "vm-updated.local"
            and node.last_seen_at is not None
        )


async def test_ws_rejects_bad_signature(api: tuple) -> None:
    _, maker = api
    node_id, _ = await _seed_node(maker)
    bad = _frame(
        "node.auth",
        node_id,
        {"challenge_id": RID, "signature": base64.b64encode(b"x" * 64).decode()},
    )
    ws = FakeWebSocket(node_id, None, [bad])
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    assert ws.closed == 1008 and "node.authenticated" not in ws.sent_types()


async def test_ws_rejects_replayed_challenge_id(api: tuple) -> None:
    _, maker = api
    node_id, _ = await _seed_node(maker)
    replay = _frame(
        "node.auth",
        node_id,
        {"challenge_id": RID, "signature": base64.b64encode(b"x" * 64).decode()},
    )
    ws = FakeWebSocket(node_id, None, [replay])
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    assert ws.closed == 1008


async def test_ws_requires_auth_first(api: tuple) -> None:
    _, maker = api
    node_id, _ = await _seed_node(maker)
    ws = FakeWebSocket(
        node_id,
        None,
        [_frame("node.heartbeat", node_id, {"daemon_version": "1.0.0", "active_sessions": 0})],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    assert ws.closed == 1008


async def test_ws_system_info_and_runtime_status_persist(api: tuple) -> None:
    _, maker = api
    node_id, private = await _seed_node(maker)
    ws = FakeWebSocket(
        node_id,
        private,
        [
            _frame(
                "node.system_info",
                node_id,
                {
                    "os": "linux",
                    "os_version": "Debian 12",
                    "architecture": "arm64",
                    "run_user": "deploy",
                    "kernel": "6.1.0-debian",
                },
            ),
            _frame(
                "node.runtime_status",
                node_id,
                {"runtimes": [{"runtime": "codex", "available": True, "version": "9.9"}]},
            ),
        ],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert node is not None
        # node.system_info refreshed the OS/arch/run_user + kernel metadata.
        assert node.os_version == "Debian 12"
        assert node.architecture == "arm64"
        assert node.run_user == "deploy"
        assert node.node_metadata.get("kernel") == "6.1.0-debian"
        # node.runtime_status replaced the detected runtimes.
        assert [(r.runtime, r.available) for r in node.runtimes] == [("codex", True)]


class _ResourceCapturingWebSocket(FakeWebSocket):
    """Snapshots the live registry resources at the moment the loop drains its
    last frame (post-heartbeat) and is about to disconnect."""

    def __init__(self, node_id: uuid.UUID, private, incoming: list[str]) -> None:
        super().__init__(node_id, private, incoming)
        self.captured: dict | None = None

    async def receive(self) -> dict:
        # The control loop drains via receive(); snapshot the live registry
        # resources just before the loop sees the disconnect (post-heartbeat).
        if self.private is None and not self._incoming and self.captured is None:
            from app.services.registry import get_node_registry

            self.captured = get_node_registry().resources_for(self.node_id)
        return await super().receive()


async def test_ws_heartbeat_resources_reach_registry(api: tuple) -> None:
    _, maker = api
    node_id, private = await _seed_node(maker)
    ws = _ResourceCapturingWebSocket(
        node_id,
        private,
        [
            _frame(
                "node.heartbeat",
                node_id,
                {
                    "daemon_version": "1.0.0",
                    "active_sessions": 0,
                    "resources": {"cpu_usage": 5.0, "daemon_uptime": 120.0},
                },
            )
        ],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    assert ws.captured == {"cpu_usage": 5.0, "daemon_uptime": 120.0}


# --- Privileged node posture (ADR 0023, PV-07) ---------------------------------


def _privileged_register_payload() -> dict:
    payload = _register_payload()
    payload["privileged_terminal"] = True
    payload["runtimes"] = [
        {"runtime": "codex", "available": True, "version": "codex 1.2.3", "sandbox_bypass": True},
        {"runtime": "claude", "available": True},
    ]
    return payload


async def _register_via_ws(maker, node_id, private, payload) -> None:
    ws = FakeWebSocket(node_id, private, [_frame("node.register", node_id, payload)])
    async with maker() as session:
        await node_gateway(ws, node_id, session)


async def _posture_audit_rows(maker) -> list:
    from app.db.models import AuditLog

    async with maker() as session:
        rows = (
            await session.execute(
                sa.select(AuditLog).where(AuditLog.action == "node.posture_changed")
            )
        ).scalars()
        return list(rows)


async def test_a_daemon_that_says_nothing_is_not_privileged(api: tuple) -> None:
    """Absent must read as unprivileged. An older daemon sends neither field, and a
    console that inferred "privileged" from silence would describe a posture nobody
    claimed."""
    _, maker = api
    node_id, private = await _seed_node(maker)
    await _register_via_ws(maker, node_id, private, _register_payload())
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert node is not None and node.privileged_terminal is False
        assert all(r.sandbox_bypass is False for r in node.runtimes)
    assert await _posture_audit_rows(maker) == []


async def test_the_reported_posture_is_persisted_and_audited(api: tuple) -> None:
    _, maker = api
    node_id, private = await _seed_node(maker)
    await _register_via_ws(maker, node_id, private, _privileged_register_payload())
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert node is not None and node.privileged_terminal is True
        codex = next(r for r in node.runtimes if r.runtime == "codex")
        claude = next(r for r in node.runtimes if r.runtime == "claude")
        assert codex.sandbox_bypass is True
        # Only the runtime that reported it: a bypass is not a node-wide property.
        assert claude.sandbox_bypass is False
    rows = await _posture_audit_rows(maker)
    assert len(rows) == 1
    assert rows[0].audit_metadata["privileged_terminal"] is True
    assert rows[0].audit_metadata["previous"] is False


async def test_reconnecting_in_the_same_posture_writes_no_audit_row(api: tuple) -> None:
    """A reconnect is not a change. One row per reconnect would bury the announce that
    matters — which is the only reason this action is worth having."""
    _, maker = api
    node_id, private = await _seed_node(maker)
    await _register_via_ws(maker, node_id, private, _privileged_register_payload())
    await _register_via_ws(maker, node_id, private, _privileged_register_payload())
    assert len(await _posture_audit_rows(maker)) == 1


async def test_revoking_the_posture_is_audited_too(api: tuple) -> None:
    _, maker = api
    node_id, private = await _seed_node(maker)
    await _register_via_ws(maker, node_id, private, _privileged_register_payload())
    await _register_via_ws(maker, node_id, private, _register_payload())
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert node is not None and node.privileged_terminal is False
    rows = sorted(await _posture_audit_rows(maker), key=lambda r: r.created_at)
    assert len(rows) == 2
    assert rows[1].audit_metadata["privileged_terminal"] is False
    assert rows[1].audit_metadata["previous"] is True


async def test_runtime_status_refresh_updates_the_sandbox_posture(api: tuple) -> None:
    """A codex upgrade that drops the flag has to be visible without a re-register:
    the daemon re-detects and pushes node.runtime_status."""
    _, maker = api
    node_id, private = await _seed_node(maker)
    await _register_via_ws(maker, node_id, private, _privileged_register_payload())
    ws = FakeWebSocket(
        node_id,
        private,
        [
            _frame(
                "node.runtime_status",
                node_id,
                {
                    "runtimes": [
                        {"runtime": "codex", "available": True, "sandbox_bypass": False},
                    ]
                },
            )
        ],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    async with maker() as session:
        node = await NodeRepository(session).get(node_id)
        assert node is not None
        codex = next(r for r in node.runtimes if r.runtime == "codex")
        assert codex.sandbox_bypass is False
        # The terminal posture is not touched by a runtime refresh: it changes only
        # when the machine's unit and sudoers change, which requires a restart.
        assert node.privileged_terminal is True


class SessionFrameWebSocket(FakeWebSocket):
    async def receive(self) -> dict:
        if self._incoming and isinstance(self._incoming[0], bytes):
            return {"type": "websocket.receive", "bytes": self._incoming.pop(0)}
        return await super().receive()


async def _seed_session_target(maker, owner_id, *, initial="running", child=False):
    async with maker() as session:
        user = (await session.execute(sa.select(User))).scalars().one()
        parent = TerminalSession(
            node_id=owner_id,
            user_id=user.id,
            name="target",
            runtime="claude",
            workspace="/home/neil",
            status=initial,
            rows=24,
            columns=80,
        )
        session.add(parent)
        await session.flush()
        child_id = None
        if child:
            shell = TerminalSession(
                node_id=owner_id,
                user_id=user.id,
                name="child",
                runtime="shell",
                workspace="/home/neil",
                status="running",
                rows=24,
                columns=80,
                parent_session_id=parent.id,
            )
            session.add(shell)
            await session.flush()
            child_id = shell.id
        await session.commit()
        return parent.id, child_id


async def _other_node(maker):
    async with maker() as session:
        node = Node(name="other", hostname="other", status="online", is_enabled=True)
        session.add(node)
        await session.commit()
        return node.id


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        ("starting", "running"),
        ("starting", "failed"),
        ("starting", "exited"),
        ("running", "disconnected"),
        ("running", "exited"),
        ("running", "terminating"),
        ("running", "failed"),
        ("disconnected", "running"),
        ("disconnected", "exited"),
        ("disconnected", "terminating"),
        ("disconnected", "failed"),
        ("terminating", "terminated"),
        ("terminating", "failed"),
        ("terminating", "exited"),
    ],
)
async def test_ws_cross_node_status_cannot_mutate_or_stop_children(
    api, monkeypatch, initial, target
):
    _, maker = api
    node_a, private = await _seed_node(maker)
    node_b = await _other_node(maker)
    sid, child_id = await _seed_session_target(maker, node_b, initial=initial, child=True)
    cleanup = AsyncMock()
    monkeypatch.setattr(get_node_registry(), "request", cleanup)
    ws = SessionFrameWebSocket(
        node_a,
        private,
        [
            _frame(
                "session.status_changed",
                node_a,
                {"session_id": str(sid), "status": target, "exit_code": 73},
            ),
        ],
    )
    async with maker() as session:
        commit = AsyncMock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit)
        await node_gateway(ws, node_a, session)
        commit.assert_not_awaited()
    async with maker() as session:
        row = await session.get(TerminalSession, sid)
        shell = await session.get(TerminalSession, child_id)
        assert row.status == initial and row.exit_code is None and row.ended_at is None
        assert shell.status == "running" and shell.ended_at is None
    cleanup.assert_not_awaited()
    assert ws.closed is None


@pytest.mark.parametrize("kind", ["binary", "terminal.gap", "terminal.exited", "terminal.error"])
async def test_ws_terminal_frames_require_owner_and_keep_connection_alive(api, monkeypatch, kind):
    _, maker = api
    node_a, private = await _seed_node(maker)
    node_b = await _other_node(maker)
    foreign, _ = await _seed_session_target(maker, node_b)
    own, _ = await _seed_session_target(maker, node_a)
    unknown = uuid.uuid4()
    relay = TerminalRelay()
    monkeypatch.setattr("app.services.terminal_relay._relay", relay)
    channels = {}
    for sid in (foreign, own, unknown):
        channel = BrowserChannel(max_bytes=4096, max_frames=16)
        channels[sid] = channel
        await relay.subscribe(sid, "viewer", uuid.uuid4(), channel, can_write=False)

    def frame(sid):
        if kind == "binary":
            return encode_binary(2, sid, b"private-terminal-content")
        payload = {"session_id": str(sid)}
        if kind == "terminal.gap":
            payload.update(dropped_bytes=12, reason="slow_consumer")
        elif kind == "terminal.exited":
            payload["exit_code"] = 0
        else:
            payload.update(code="SESSION_NOT_FOUND", message="private-terminal-content")
        # Spoofing the envelope identity cannot override the authenticated socket.
        return _frame(kind, node_b, payload)

    ws = SessionFrameWebSocket(node_a, private, [frame(foreign), frame(unknown), frame(own)])
    async with maker() as session:
        await node_gateway(ws, node_a, session)
    assert channels[foreign].stats.frames == channels[foreign].stats.control == 0
    assert channels[unknown].stats.frames == channels[unknown].stats.control == 0
    assert channels[own].stats.frames + channels[own].stats.control == 1
    expected = (
        ("output", b"private-terminal-content") if kind == "binary" else ("control", frame(own))
    )
    assert await channels[own].get() == expected
    assert ws.closed is None


async def test_ws_same_node_status_and_unknown_status(api, monkeypatch):
    _, maker = api
    node_id, private = await _seed_node(maker)
    sid, child_id = await _seed_session_target(maker, node_id, child=True)
    cleanup = AsyncMock()
    monkeypatch.setattr(get_node_registry(), "request", cleanup)
    ws = SessionFrameWebSocket(
        node_id,
        private,
        [
            _frame(
                "session.status_changed",
                node_id,
                {"session_id": str(uuid.uuid4()), "status": "exited", "exit_code": 99},
            ),
            _frame(
                "session.status_changed",
                node_id,
                {"session_id": str(sid), "status": "exited", "exit_code": 7},
            ),
        ],
    )
    async with maker() as session:
        await node_gateway(ws, node_id, session)
    async with maker() as session:
        row = await session.get(TerminalSession, sid)
        shell = await session.get(TerminalSession, child_id)
        assert row.status == "exited" and row.exit_code == 7 and row.ended_at is not None
        assert shell.status == "terminated" and shell.ended_at is not None
    cleanup.assert_awaited_once()


async def test_ws_reconnect_reuses_ownership_and_end_delete_invalidate_it(api, monkeypatch):
    from app.repositories.sessions import SessionRepository
    from app.services.sessions import SessionService

    _, maker = api
    node_id, private = await _seed_node(maker)
    sid, _ = await _seed_session_target(maker, node_id)
    relay = TerminalRelay()
    monkeypatch.setattr("app.services.terminal_relay._relay", relay)
    channel = BrowserChannel(max_bytes=4096, max_frames=16)
    await relay.subscribe(sid, "viewer", uuid.uuid4(), channel, can_write=False)
    lookups = []
    original = SessionRepository.owner

    async def owner(repo, session_id):
        lookups.append(session_id)
        return await original(repo, session_id)

    monkeypatch.setattr(SessionRepository, "owner", owner)

    async def connect(frames):
        ws = SessionFrameWebSocket(node_id, private, frames)
        async with maker() as session:
            await node_gateway(ws, node_id, session)
        assert ws.closed is None and "node.authenticated" in ws.sent_types()

    output = encode_binary(2, sid, b"own")
    await connect([output, output])
    await connect([output])
    assert lookups == [sid] and channel.stats.frames == 3

    await connect(
        [
            _frame(
                "session.status_changed",
                node_id,
                {"session_id": str(sid), "status": "exited", "exit_code": 0},
            )
        ]
    )
    assert sid not in relay._owners
    await connect([_frame("terminal.exited", node_id, {"session_id": str(sid), "exit_code": 0})])
    assert lookups == [sid, sid] and channel.stats.control == 1
    assert sid not in relay._owners
    async with maker() as session:
        await SessionService(session).delete(session_id=sid)
        await session.commit()
    await connect([output])
    assert lookups == [sid, sid, sid] and channel.stats.frames == 3


async def test_ws_unknown_status_drops_without_commit(api, monkeypatch):
    _, maker = api
    node_id, private = await _seed_node(maker)
    ws = SessionFrameWebSocket(
        node_id,
        private,
        [
            _frame(
                "session.status_changed",
                node_id,
                {"session_id": str(uuid.uuid4()), "status": "exited", "exit_code": 42},
            ),
        ],
    )
    async with maker() as session:
        commit = AsyncMock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit)
        await node_gateway(ws, node_id, session)
        commit.assert_not_awaited()
    assert ws.closed is None
