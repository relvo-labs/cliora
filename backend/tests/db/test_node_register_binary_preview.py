"""node.register → the live binary_preview bit, the capability, and the rollback signals
(ADR 0029 §9, plan/31/04 §3, §7).

The daemon side is a scripted WebSocket whose incoming frames come from a queue, so
the test can hold a connection open, query the HTTP API against it, drop it and
reconnect. When Central sends it a preview request it answers like a daemon would.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.api.http.sessions import get_registry as sessions_registry
from app.api.ws.nodes import node_gateway
from app.db.models import Node, Role, TerminalSession, User
from app.main import app
from app.protocol import ControlMessage
from app.security.node_keys import signing_message
from app.security.passwords import hash_password
from app.services.enrollment import EnrollmentService
from app.services.nodes import NodeRegistrationService, RegisterNodeInput
from app.services.registry import get_node_registry
from app.settings import get_settings

pytestmark = pytest.mark.asyncio

PNG = b"\x89PNG\r\n\x1a\n" + bytes(200)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLIORA_BINARY_PREVIEW_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _frame(
    type_: str,
    node_id: uuid.UUID,
    payload: dict,
    request_id: str | None = None,
    success: bool | None = None,
) -> str:
    body: dict[str, Any] = {
        "version": 1,
        "type": type_,
        "request_id": request_id
        or "01K6"
        + uuid.uuid4()
        .hex[:22]
        .upper()
        .replace("I", "J")
        .replace("L", "M")
        .replace("O", "P")
        .replace("U", "V"),
        "node_id": str(node_id),
        "timestamp": "2026-09-27T01:00:00Z",
        "payload": payload,
    }
    if success is not None:
        body["success"] = success
    return json.dumps(body)


def _register(
    binary_preview: bool | None,
    name: str = "vm",
    version: str = "1.0.0",
    runtimes: list[dict] | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "hostname": "vm.local",
        "os": "linux",
        "os_version": "Ubuntu 24.04",
        "architecture": "amd64",
        "daemon_version": version,
        "run_user": "agentd",
        "runtimes": runtimes or [],
        "workspace_roots": [{"path": "/home/neil/projects", "is_enabled": True}],
    }
    if binary_preview is not None:
        payload["binary_preview"] = binary_preview
    return payload


class LiveDaemon:
    """A WebSocket driven from a queue that also plays the daemon for preview frames."""

    def __init__(
        self, node_id: uuid.UUID, private: Ed25519PrivateKey, files: dict[str, bytes] | None = None
    ):
        self.node_id, self.private = node_id, private
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.sent: list[dict] = []
        self.files = files or {}
        self.handles: dict[str, bytes] = {}
        self.closed: int | None = None

    async def accept(self) -> None:
        pass

    async def receive_text(self) -> str:
        challenge = self.sent[-1]
        signature = base64.b64encode(
            self.private.sign(
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

    async def receive(self) -> dict:
        return await self.incoming.get()

    def push(self, text: str) -> None:
        self.incoming.put_nowait({"type": "websocket.receive", "text": text})

    def disconnect(self) -> None:
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    async def send_text(self, data: str) -> None:
        frame = json.loads(data)
        self.sent.append(frame)
        typ, rid, p = frame.get("type"), frame.get("request_id"), frame.get("payload", {})
        if typ == "filesystem.preview_open":
            data_bytes = self.files[p["path"]]
            pid = "01K6PREV1EW" + f"{len(self.handles) + 1:015d}"
            self.handles[pid] = data_bytes
            self.push(
                _frame(
                    "filesystem.preview_opened",
                    self.node_id,
                    {
                        "success": True,
                        "preview_id": pid,
                        "path": p["path"],
                        "kind": "image",
                        "mime": "image/png",
                        "size": len(data_bytes),
                        "modified_at": "2026-09-27T00:00:00Z",
                        "chunk_size": 524288,
                        "chunk_count": max(1, math.ceil(len(data_bytes) / 524288)),
                        "width": 2,
                        "height": 2,
                    },
                    rid,
                    True,
                )
            )
        elif typ == "filesystem.preview_chunk":
            piece = self.handles[p["preview_id"]][p["index"] * 524288 : (p["index"] + 1) * 524288]
            self.push(
                _frame(
                    "filesystem.preview_data",
                    self.node_id,
                    {
                        "preview_id": p["preview_id"],
                        "index": p["index"],
                        "data": base64.b64encode(piece).decode(),
                    },
                    rid,
                    True,
                )
            )
        elif typ == "filesystem.preview_close":
            self.handles.pop(p["preview_id"], None)
            self.push(
                _frame(
                    "filesystem.preview_closed",
                    self.node_id,
                    {"preview_id": p["preview_id"]},
                    rid,
                    True,
                )
            )

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    def sent_types(self) -> list[str]:
        return [f.get("type") for f in self.sent]


async def _seed(maker) -> tuple[uuid.UUID, Ed25519PrivateKey, uuid.UUID, uuid.UUID]:
    """A registered node, a Viewer and a session of theirs on that node."""
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    async with maker() as session:
        admin_role = (
            await session.execute(sa.select(Role).where(Role.name == "Admin"))
        ).scalar_one()
        admin = User(
            username=f"a-{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("pw"),
            display_name="a",
            role_id=admin_role.id,
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
                os_version="x",
                architecture="amd64",
                daemon_version="1.0.0",
                run_user="agentd",
                public_key=public,
            ),
        )
        node_id = registered.node.id
        viewer_role = (
            await session.execute(sa.select(Role).where(Role.name == "Viewer"))
        ).scalar_one()
        viewer = User(
            username=f"v-{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("pw"),
            display_name="v",
            role_id=viewer_role.id,
        )
        session.add(viewer)
        await session.flush()
        ts = TerminalSession(
            node_id=node_id,
            user_id=viewer.id,
            name="s",
            runtime="claude",
            workspace="/home/neil/projects/app",
            status="running",
            rows=24,
            columns=80,
        )
        session.add(ts)
        await session.commit()
        return node_id, private, ts.id, viewer.id


async def _token(client, maker, user_id: uuid.UUID) -> dict:
    async with maker() as session:
        user = await session.get(User, user_id)
        username = user.username
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _connect(maker, daemon: LiveDaemon, register: dict) -> asyncio.Task:
    async def run() -> None:
        async with maker() as session:
            await node_gateway(daemon, daemon.node_id, session)

    task = asyncio.create_task(run())
    daemon.push(_frame("node.register", daemon.node_id, register))
    for _ in range(200):
        if "node.registered" in daemon.sent_types() or task.done():
            break
        await asyncio.sleep(0.01)
    return task


async def _close(daemon: LiveDaemon, task: asyncio.Task) -> None:
    daemon.disconnect()
    await asyncio.wait_for(task, 5)


async def _capability(client, headers, sid) -> bool:
    resp = await client.get(f"/api/sessions/{sid}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["capabilities"]["can_preview_binary"]


async def _preview_status(client, headers, sid) -> int:
    resp = await client.post(
        f"/api/sessions/{sid}/files/binary-preview", json={"path": "a.png"}, headers=headers
    )
    return resp.status_code


async def test_reconnect_flips_gate_and_capability(api: tuple) -> None:
    client, maker = api
    node_id, private, sid, uid = await _seed(maker)
    headers = await _token(client, maker, uid)

    first = LiveDaemon(node_id, private, {"a.png": PNG})
    task = await _connect(maker, first, _register(True))
    assert get_node_registry().binary_preview(node_id) is True
    assert await _capability(client, headers, sid) is True
    assert await _preview_status(client, headers, sid) == 200
    await _close(first, task)
    assert get_node_registry().binary_preview(node_id) is False

    # Reconnect downgraded (field omitted): both the capability and the endpoint turn
    # off at once, without waiting for any database write.
    second = LiveDaemon(node_id, private, {"a.png": PNG})
    task = await _connect(maker, second, _register(None))
    assert await _capability(client, headers, sid) is False
    assert await _preview_status(client, headers, sid) == 409
    assert not any(t.startswith("filesystem.preview") for t in second.sent_types()), (
        "a node whose live registration omits binary_preview must receive no preview frame"
    )
    await _close(second, task)

    third = LiveDaemon(node_id, private, {"a.png": PNG})
    task = await _connect(maker, third, _register(True))
    assert await _capability(client, headers, sid) is True
    assert await _preview_status(client, headers, sid) == 200
    await _close(third, task)
    assert await _capability(client, headers, sid) is False  # connection gone


async def test_capability_needs_the_flag_too(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    client, maker = api
    node_id, private, sid, uid = await _seed(maker)
    headers = await _token(client, maker, uid)
    daemon = LiveDaemon(node_id, private)
    task = await _connect(maker, daemon, _register(True))
    monkeypatch.setenv("CLIORA_BINARY_PREVIEW_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert await _capability(client, headers, sid) is False
    finally:
        await _close(daemon, task)


class _SessionsFake:
    """Answers the session lifecycle frames for the sessions router."""

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        sid = payload["session_id"]
        reply = "session.started" if type_ == "session.start" else "session.stopped"
        return ControlMessage(
            version=1,
            type=reply,
            request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
            node_id=node_id,
            timestamp="2026-09-27T00:00:00Z",
            payload={"session_id": sid, "pid": 7, "exit_code": 0},
            success=True,
        )


async def test_capability_on_every_session_response(api: tuple) -> None:
    """sessions.py's five return points all carry can_preview_binary, with one value."""
    client, maker = api
    node_id, private, sid, _ = await _seed(maker)
    async with maker() as session:
        dev_role = (
            await session.execute(sa.select(Role).where(Role.name == "Developer"))
        ).scalar_one()
        dev = User(
            username=f"d-{uuid.uuid4().hex[:6]}",
            password_hash=hash_password("pw"),
            display_name="d",
            role_id=dev_role.id,
        )
        session.add(dev)
        node = await session.get(Node, node_id)
        # The register below supplies the workspace roots and runtimes.
        node.status = "online"
        await session.commit()
        dev_id = dev.id
    headers = await _token(client, maker, dev_id)
    daemon = LiveDaemon(node_id, private)
    task = await _connect(
        maker,
        daemon,
        _register(
            True,
            runtimes=[
                {"runtime": "claude", "available": True},
                {"runtime": "shell", "available": True},
            ],
        ),
    )
    app.dependency_overrides[sessions_registry] = lambda: _SessionsFake()
    try:
        created = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "workspace": "/home/neil/projects/app",
                "name": "x",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        new_id = created.json()["id"]
        listed = await client.get("/api/sessions", headers=headers)
        detail = await client.get(f"/api/sessions/{new_id}", headers=headers)
        shell = await client.post(f"/api/sessions/{new_id}/shell", json={}, headers=headers)
        terminated = await client.post(f"/api/sessions/{new_id}/terminate", headers=headers)
    finally:
        app.dependency_overrides.pop(sessions_registry, None)
        await _close(daemon, task)
    values = [
        created.json()["capabilities"]["can_preview_binary"],
        next(s for s in listed.json() if s["id"] == new_id)["capabilities"]["can_preview_binary"],
        detail.json()["capabilities"]["can_preview_binary"],
        terminated.json()["capabilities"]["can_preview_binary"],
    ]
    assert values == [True, True, True, True], values
    # The shell response is the shell session itself: never a route to the files.
    assert shell.status_code in (200, 201), shell.text
    assert shell.json()["capabilities"]["can_preview_binary"] is False
    assert "can_preview_binary" in shell.json()["capabilities"]


async def test_register_persists_the_column_and_audits_a_change(api: tuple) -> None:
    client, maker = api
    node_id, private, _, _ = await _seed(maker)
    for value in (True, True, None):
        daemon = LiveDaemon(node_id, private)
        task = await _connect(maker, daemon, _register(value))
        await _close(daemon, task)
    async with maker() as session:
        node = await session.get(Node, node_id)
        assert node.binary_preview is False
        rows = (
            (
                await session.execute(
                    sa.text(
                        "select metadata from audit_logs "
                        "where action = 'node.posture_changed' and node_id = :n "
                        "order by created_at"
                    ),
                    {"n": node_id},
                )
            )
            .scalars()
            .all()
        )
    changes = [(r["binary_preview"], r["previous_binary_preview"]) for r in rows]
    # Only changes are audited: on, (no change), off.
    assert changes == [(True, False), (False, True)], changes


async def test_last_registration_at_is_registration_specific(api: tuple) -> None:
    client, maker = api
    node_id, private, _, _ = await _seed(maker)

    async def last_registration() -> datetime | None:
        async with maker() as session:
            return (await session.get(Node, node_id)).last_registration_at

    daemon = LiveDaemon(node_id, private)
    task = await _connect(maker, daemon, _register(True))
    first = await last_registration()
    assert first is not None and first.tzinfo is not None
    # Heartbeats move last_seen_at but not last_registration_at.
    daemon.push(
        _frame("node.heartbeat", node_id, {"daemon_version": "1.0.0", "active_sessions": 0})
    )
    await asyncio.sleep(0.2)
    assert await last_registration() == first
    # An invalid register (binary_preview:false is not a legal value) is skipped:
    # nothing persisted, nothing acknowledged, and this signal does not move.
    before = daemon.sent_types().count("node.registered")
    daemon.push(_frame("node.register", node_id, _register(False, name="must-not-land")))
    await asyncio.sleep(0.2)
    assert await last_registration() == first
    assert daemon.sent_types().count("node.registered") == before
    await _close(daemon, task)
    # The same version re-registering moves it: that, not daemon_version, is the proof.
    await asyncio.sleep(0.01)
    again = LiveDaemon(node_id, private)
    task = await _connect(maker, again, _register(True, version="1.0.0"))
    await _close(again, task)
    second = await last_registration()
    assert second is not None and second > first
    async with maker() as session:
        assert (await session.get(Node, node_id)).name == "vm"


async def test_invalid_register_is_silently_skipped(api: tuple) -> None:
    """Pins today's failure mode, which is what an older Central does with a 1.11
    register (ADR 0029 §9): no persistence, no reply, and the connection stays up."""
    client, maker = api
    node_id, private, _, _ = await _seed(maker)
    daemon = LiveDaemon(node_id, private)

    async def run() -> None:
        async with maker() as session:
            await node_gateway(daemon, node_id, session)

    task = asyncio.create_task(run())
    bad = _register(True, name="marker-should-not-land")
    bad["unknown_field"] = True
    daemon.push(_frame("node.register", node_id, bad))
    await asyncio.sleep(0.3)
    assert not task.done(), "the connection must stay up"
    assert "node.registered" not in daemon.sent_types()
    assert get_node_registry().is_connected(node_id)
    assert get_node_registry().binary_preview(node_id) is False
    async with maker() as session:
        node = await session.get(Node, node_id)
        assert node.name != "marker-should-not-land"
        assert node.last_registration_at is None
    await _close(daemon, task)


async def test_node_detail_exposes_last_registration_at(api: tuple) -> None:
    client, maker = api
    node_id, private, _, _ = await _seed(maker)
    async with maker() as session:
        admin = (
            (await session.execute(sa.select(User).where(User.username.like("a-%"))))
            .scalars()
            .first()
        )
        admin_id = admin.id
    headers = await _token(client, maker, admin_id)
    before = await client.get(f"/api/nodes/{node_id}", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["last_registration_at"] is None
    assert before.json()["binary_preview"] is False
    daemon = LiveDaemon(node_id, private)
    task = await _connect(maker, daemon, _register(True))
    await _close(daemon, task)
    after = await client.get(f"/api/nodes/{node_id}", headers=headers)
    stamp = datetime.fromisoformat(after.json()["last_registration_at"].replace("Z", "+00:00"))
    assert stamp <= datetime.now(UTC)
    assert after.json()["binary_preview"] is True
