"""HTTP filesystem relay API against the real schema (P3-06, ADR 0014/0015).

The daemon round-trip is faked by overriding the files router's get_registry;
the offline path uses a disconnected fake so NODE_OFFLINE is exercised. These
tests assert the relay/authorize contract: RBAC (file.browse on all roles),
boundary rejection of absolute/`..` paths (never relayed), safe collapse of
existence-probing errors, sensitive-read audit with no path/content, and that no
server absolute path is ever returned to the browser.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import metrics
from app.api.errors import ApiError
from app.api.http.files import get_registry
from app.db.models import Node, NodeWorkspaceRoot, Role, TerminalSession, User
from app.logging import JsonFormatter
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool = True) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload=payload,
        success=success,
    )


def _err_msg(node_id: uuid.UUID, code: str) -> ControlMessage:
    return ControlMessage(
        version=1,
        type="error",
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload={},
        success=False,
        error={"code": code, "message": "denied"},
    )


class FakeRegistry:
    """Fakes the daemon: records the last relayed (type, payload) and returns a
    canned response. `responder` may be set to customise the reply."""

    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.calls: list[tuple[str, dict]] = []
        self.responder = None

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return self.connected

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        self.calls.append((type_, payload))
        if self.responder is not None:
            return self.responder(node_id, type_, payload)
        if type_ == "filesystem.list":
            return _msg(
                "filesystem.entries",
                node_id,
                {
                    "path": payload["path"],
                    "root_display_name": "Projects",
                    "truncated": False,
                    "entries": [
                        {
                            "name": "main.py",
                            "rel_path": "main.py",
                            "type": "file",
                            "size": 12,
                            "modified_at": "2026-07-25T00:00:00Z",
                            "hidden": False,
                            "symlink": False,
                            "excluded": False,
                            "expandable": False,
                        }
                    ],
                },
            )
        if type_ == "filesystem.search":
            return _msg(
                "filesystem.search_result",
                node_id,
                {
                    "results": [
                        {
                            "name": "main.py",
                            "rel_path": "main.py",
                            "type": "file",
                            "modified_at": "2026-07-25T00:00:00Z",
                        }
                    ],
                    "partial": False,
                    "scanned_count": 1,
                },
            )
        return _msg(
            "filesystem.content",
            node_id,
            {
                "success": True,
                "rel_path": payload["path"],
                "size": 12,
                "modified_at": "2026-07-25T00:00:00Z",
                "encoding": "utf-8",
                "language_hint": "python",
                "content": "print('hi')\n",
            },
        )


@contextmanager
def use_registry(fake: FakeRegistry):
    app.dependency_overrides[get_registry] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def _login(
    client: AsyncClient, maker: async_sessionmaker, *, role_name: str
) -> tuple[dict, uuid.UUID]:
    username = f"u-{uuid.uuid4().hex[:8]}"
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
        uid = user.id
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}, uid


async def _make_session(
    maker: async_sessionmaker, owner_id: uuid.UUID, *, online: bool = True
) -> uuid.UUID:
    async with maker() as session:
        node = Node(
            name="vm", hostname="vm", status="online" if online else "offline", is_enabled=True
        )
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.flush()
        ts = TerminalSession(
            node_id=node.id,
            user_id=owner_id,
            name="s1",
            runtime="claude",
            workspace="/home/neil/projects/app",
            status="running",
            rows=40,
            columns=120,
        )
        session.add(ts)
        await session.commit()
        return ts.id


async def test_tree_search_content_relay(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    with use_registry(fake):
        tree = await client.get(
            f"/api/sessions/{sid}/files/tree", params={"path": "."}, headers=headers
        )
        assert tree.status_code == 200, tree.text
        assert tree.json()["entries"][0]["rel_path"] == "main.py"

        search = await client.get(
            f"/api/sessions/{sid}/files/search", params={"keyword": "main"}, headers=headers
        )
        assert search.status_code == 200, search.text
        assert search.json()["results"][0]["name"] == "main.py"

        content = await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "main.py"}, headers=headers
        )
        assert content.status_code == 200, content.text
        assert content.json()["content"] == "print('hi')\n"
    # No server absolute path leaked in any relayed response.
    for resp_text in (tree.text, search.text, content.text):
        assert "/home/neil" not in resp_text


async def test_viewer_can_browse(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Viewer")
    sid = await _make_session(maker, uid)
    with use_registry(FakeRegistry()):
        resp = await client.get(
            f"/api/sessions/{sid}/files/tree", params={"path": "."}, headers=headers
        )
    assert resp.status_code == 200, resp.text


async def test_absolute_and_parent_paths_rejected_at_boundary(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    with use_registry(fake):
        for bad in ("/etc/passwd", "a/../../etc", "~/secrets"):
            resp = await client.get(
                f"/api/sessions/{sid}/files/content", params={"path": bad}, headers=headers
            )
            assert resp.status_code == 400, (bad, resp.text)
    # None of the rejected paths were ever relayed to the daemon.
    assert fake.calls == []


async def test_offline_node_conflict(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid, online=False)
    with use_registry(FakeRegistry(connected=False)):
        resp = await client.get(
            f"/api/sessions/{sid}/files/tree", params={"path": "."}, headers=headers
        )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "NODE_OFFLINE"


async def test_existence_probe_collapses_to_cannot_access(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _err_msg(
        node_id, "WORKSPACE_OUTSIDE_ALLOWED_ROOT"
    )
    with use_registry(fake):
        resp = await client.get(
            f"/api/sessions/{sid}/files/tree", params={"path": "secret"}, headers=headers
        )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "FILE_NOT_FOUND"


async def test_sensitive_denial_is_audited_without_path(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.content",
        node_id,
        {
            "success": False,
            "rel_path": payload["path"],
            "error": {"code": "FILE_DENIED", "reason": "dotenv"},
        },
    )
    with use_registry(fake):
        resp = await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "config/.env"}, headers=headers
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["error"]["code"] == "FILE_DENIED"
    # Audit recorded classification + extension only — no rel_path/content.
    async with maker() as session:
        rows = (
            await session.execute(
                sa.text(
                    "select action, metadata::text from audit_logs "
                    "where action = 'file.sensitive_read_denied'"
                )
            )
        ).all()
    assert len(rows) == 1
    meta = rows[0][1]
    assert "dotenv" in meta
    assert ".env" not in meta and "config" not in meta and "rel_path" not in meta


# --- P3-09 observability: metrics + correlation log (never content/path/keyword) ---


async def test_each_operation_is_counted_and_timed(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(FakeRegistry()):
        await client.get(f"/api/sessions/{sid}/files/tree", params={"path": "."}, headers=headers)
        await client.get(
            f"/api/sessions/{sid}/files/search", params={"keyword": "main"}, headers=headers
        )
        await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "main.py"}, headers=headers
        )

    for op in ("list", "search", "read"):
        assert metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op=op, code="OK") == 1
        entry = metrics.histogram_value(metrics.FILESYSTEM_REQUEST_DURATION, op=op)
        assert entry is not None and entry["count"] == 1


async def test_relay_timeout_and_disconnect_are_counted(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)

    timeout = FakeRegistry()

    def _raise_timeout(node_id, type_, payload):
        raise ApiError(
            "REQUEST_TIMEOUT", "Node did not respond in time", status.HTTP_504_GATEWAY_TIMEOUT
        )

    timeout.responder = _raise_timeout
    with use_registry(timeout):
        resp = await client.get(
            f"/api/sessions/{sid}/files/tree", params={"path": "."}, headers=headers
        )
    assert resp.status_code == 504, resp.text
    assert metrics.counter_value(metrics.FILESYSTEM_RELAY_TIMEOUT_TOTAL, op="list") == 1
    assert (
        metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op="list", code="REQUEST_TIMEOUT")
        == 1
    )

    with use_registry(FakeRegistry(connected=False)):
        resp = await client.get(
            f"/api/sessions/{sid}/files/search", params={"keyword": "x"}, headers=headers
        )
    assert resp.status_code == 409, resp.text
    assert metrics.counter_value(metrics.FILESYSTEM_NODE_DISCONNECT_TOTAL, op="search") == 1


async def test_denials_are_counted_by_reason(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.content",
        node_id,
        {
            "success": False,
            "rel_path": payload["path"],
            "error": {"code": "FILE_BINARY"},
            "size": 4096,
            "mime": "application/octet-stream",
        },
    )
    with use_registry(fake):
        resp = await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "logo.png"}, headers=headers
        )
    assert resp.status_code == 200, resp.text
    assert (
        metrics.counter_value(
            metrics.FILESYSTEM_DENIED_TOTAL, code="FILE_BINARY", reason="unspecified"
        )
        == 1
    )
    # The denial, not "OK", is the recorded outcome for the read.
    assert (
        metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op="read", code="FILE_BINARY") == 1
    )


async def test_correlation_log_has_ids_and_volumes_but_no_path_or_content(
    api: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with caplog.at_level(logging.INFO, logger="cliora.files"), use_registry(FakeRegistry()):
        await client.get(
            f"/api/sessions/{sid}/files/content",
            params={"path": "src/main.py"},
            headers=headers,
        )

    records = [r for r in caplog.records if getattr(r, "event", "") == "filesystem.read"]
    assert len(records) == 1
    record = records[0]
    assert record.op == "read"
    assert record.code == "OK"
    assert record.session_id == str(sid)
    assert record.user_id == str(uid)
    assert isinstance(record.duration_ms, float)
    # Volume only: the byte count, never the bytes.
    assert record.bytes == len("print('hi')\n")
    # Assert on what is actually written: the JSON line the formatter emits.
    emitted = JsonFormatter().format(record)
    assert "src/main.py" not in emitted
    assert "print(" not in emitted
    assert "/home/neil" not in emitted


async def test_search_keyword_is_hashed_in_the_correlation_log(
    api: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with caplog.at_level(logging.INFO, logger="cliora.files"), use_registry(FakeRegistry()):
        await client.get(
            f"/api/sessions/{sid}/files/search",
            params={"keyword": "acme-merger-plan"},
            headers=headers,
        )

    record = next(r for r in caplog.records if getattr(r, "event", "") == "filesystem.search")
    assert record.keyword_length == len("acme-merger-plan")
    assert len(record.keyword_digest) == 12
    assert "acme-merger-plan" not in JsonFormatter().format(record)
    assert record.results == 1
    assert record.scanned == 1


async def test_audit_write_failure_does_not_fail_the_request(api: tuple, monkeypatch) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)

    async def _boom(*args, **kwargs):
        raise RuntimeError("audit sink down")

    monkeypatch.setattr("app.services.audit.AuditService.record", _boom)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.content",
        node_id,
        {
            "success": False,
            "rel_path": payload["path"],
            "error": {"code": "FILE_DENIED", "reason": "private_key"},
        },
    )
    with use_registry(fake):
        resp = await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "keys/id_rsa"}, headers=headers
        )

    # The user still gets the denial; the audit gap is counted, not swallowed.
    assert resp.status_code == 200, resp.text
    assert resp.json()["error"]["code"] == "FILE_DENIED"
    assert metrics.counter_value(metrics.FILESYSTEM_AUDIT_ERROR_TOTAL, action="sensitive_read") == 1
