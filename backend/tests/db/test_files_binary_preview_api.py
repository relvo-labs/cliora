"""POST /api/sessions/{id}/files/binary-preview against the real schema (ADR 0029, plan/31/04).

The daemon is faked by overriding the files router's `get_registry`. The fake
implements the preview protocol strictly — four handles, no TTL, chunks cut from the
snapshot — so a Central that forgot to close a stream would run out of handles here
exactly as it would on a node. Two tests (backpressure and disconnect) call the ASGI
app directly, because httpx's ASGI transport buffers the whole body and so cannot
behave like a slow or vanishing client; they run through the full middleware stack
(`BP-OM-11`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import pytest
import sqlalchemy as sa
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import metrics
from app.api.errors import ApiError
from app.api.http.files import get_registry
from app.db.models import Node, NodeWorkspaceRoot, Role, TerminalSession, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password
from app.settings import get_settings

pytestmark = pytest.mark.asyncio

CHUNK = 524288
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
PID_PREFIX = "01K6PREV1EW"


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The Central flag defaults to off (OD-5); these tests exercise it on."""
    metrics.reset()
    monkeypatch.setenv("CLIORA_BINARY_PREVIEW_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool = True) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-09-27T00:00:00Z",
        payload=payload,
        success=success,
    )


def _err(node_id: uuid.UUID, code: str) -> ControlMessage:
    return ControlMessage(
        version=1,
        type="error",
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-09-27T00:00:00Z",
        payload={},
        success=False,
        error={"code": code, "message": "x"},
    )


class FakePreviewDaemon:
    """The daemon half of filesystem.preview_*, with a strict 4-handle cap and no TTL."""

    def __init__(
        self,
        *,
        live: bool = True,
        connected: bool = True,
        max_handles: int = 4,
        download_enabled: bool = True,
    ) -> None:
        self.live = live
        self.connected = connected
        self.max_handles = max_handles
        self.download_enabled = download_enabled
        self.calls: list[tuple[str, dict]] = []
        self.handles: dict[str, bytes] = {}
        self.files: dict[str, tuple[bytes, str, str, int | None, int | None]] = {}
        self.denials: dict[str, dict] = {}
        self.mime_override: str | None = None
        self.on_chunk: Callable[[int], Any] | None = None
        self._seq = 0

    def add(
        self, path: str, data: bytes, mime: str = "image/png", w: int | None = 3, h: int | None = 2
    ):
        kind = "pdf" if mime == "application/pdf" else "image"
        self.files[path] = (
            data,
            mime,
            kind,
            w if kind == "image" else None,
            h if kind == "image" else None,
        )

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return self.connected

    def binary_preview(self, node_id: uuid.UUID) -> bool:
        return self.live

    def types(self) -> list[str]:
        return [t for t, _ in self.calls]

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        self.calls.append((type_, payload))
        if type_ == "filesystem.download":
            if not self.download_enabled:
                return _err(node_id, "FILE_DOWNLOAD_DISABLED")
            data = self.files[payload["path"]][0]
            return _msg(
                "filesystem.downloaded",
                node_id,
                {
                    "path": payload["path"],
                    "size": len(data),
                    "modified_at": "2026-09-27T08:00:00Z",
                    "data": base64.b64encode(data).decode("ascii"),
                },
            )
        if type_ == "filesystem.preview_open":
            path = payload["path"]
            if path in self.denials:
                return _msg(
                    "filesystem.preview_opened",
                    node_id,
                    {"success": False, "path": path, "error": self.denials[path]},
                    success=False,
                )
            if path not in self.files:
                return _msg(
                    "filesystem.preview_opened",
                    node_id,
                    {
                        "success": False,
                        "path": path,
                        "error": {"code": "FILE_NOT_FOUND", "reason": "not_found"},
                    },
                    success=False,
                )
            if len(self.handles) >= self.max_handles:
                return _err(node_id, "NODE_BUSY")
            data, mime, kind, w, h = self.files[path]
            self._seq += 1
            pid = f"{PID_PREFIX}{self._seq:015d}"
            self.handles[pid] = data
            body: dict[str, Any] = {
                "success": True,
                "preview_id": pid,
                "path": path,
                "kind": kind,
                "mime": self.mime_override or mime,
                "size": len(data),
                "modified_at": "2026-09-27T08:00:00Z",
                "chunk_size": CHUNK,
                "chunk_count": max(1, math.ceil(len(data) / CHUNK)),
            }
            if w is not None:
                body["width"], body["height"] = w, h
            return _msg("filesystem.preview_opened", node_id, body)
        if type_ == "filesystem.preview_chunk":
            index = payload["index"]
            if self.on_chunk is not None:
                result = self.on_chunk(index)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, ControlMessage):
                    return result
            data = self.handles.get(payload["preview_id"])
            if data is None:
                return _err(node_id, "FILE_PREVIEW_EXPIRED")
            piece = data[index * CHUNK : (index + 1) * CHUNK]
            return _msg(
                "filesystem.preview_data",
                node_id,
                {
                    "preview_id": payload["preview_id"],
                    "index": index,
                    "data": base64.b64encode(piece).decode(),
                },
            )
        if type_ == "filesystem.preview_close":
            self.handles.pop(payload["preview_id"], None)
            return _msg("filesystem.preview_closed", node_id, {"preview_id": payload["preview_id"]})
        if type_ == "filesystem.read":
            return _msg(
                "filesystem.content",
                node_id,
                {
                    "success": False,
                    "rel_path": payload["path"],
                    "error": {"code": "FILE_BINARY", "reason": "binary"},
                },
            )
        raise AssertionError(f"unexpected request {type_}")


@contextmanager
def use_daemon(fake: FakePreviewDaemon) -> Iterator[FakePreviewDaemon]:
    app.dependency_overrides[get_registry] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def _login(
    client: AsyncClient,
    maker: async_sessionmaker,
    *,
    role_name: str,
    actions: list[str] | None = None,
) -> tuple[dict, uuid.UUID]:
    username = f"u-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        if actions is None:
            role = (
                await session.execute(sa.select(Role).where(Role.name == role_name))
            ).scalar_one()
        else:
            role = Role(name=f"r-{uuid.uuid4().hex[:8]}", permissions={"actions": actions})
            session.add(role)
            await session.flush()
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
    maker: async_sessionmaker, owner_id: uuid.UUID, *, runtime: str = "claude"
) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.flush()
        parent_id = None
        if runtime == "shell":
            parent = TerminalSession(
                node_id=node.id,
                user_id=owner_id,
                name="p",
                runtime="claude",
                workspace="/home/neil/projects/app",
                status="running",
                rows=40,
                columns=120,
            )
            session.add(parent)
            await session.flush()
            parent_id = parent.id
        ts = TerminalSession(
            node_id=node.id,
            user_id=owner_id,
            name="s1",
            runtime=runtime,
            workspace="/home/neil/projects/app",
            status="running",
            rows=40,
            columns=120,
        )
        if parent_id is not None:
            ts.parent_session_id = parent_id
        session.add(ts)
        await session.commit()
        return ts.id


def _url(sid: uuid.UUID) -> str:
    return f"/api/sessions/{sid}/files/binary-preview"


async def _setup(
    api: tuple, role: str = "Viewer"
) -> tuple[AsyncClient, async_sessionmaker, dict, uuid.UUID, uuid.UUID]:
    client, maker = api
    headers, uid = await _login(client, maker, role_name=role)
    sid = await _make_session(maker, uid)
    return client, maker, headers, uid, sid


async def _audit_rows(maker: async_sessionmaker, action: str) -> list[tuple[str, dict]]:
    async with maker() as session:
        rows = (
            await session.execute(
                sa.text(
                    "select action, metadata from audit_logs where action = :a order by created_at"
                ),
                {"a": action},
            )
        ).all()
    return [(r[0], r[1]) for r in rows]


# --------------------------------------------------------------------------- #
# Authorization and gates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["Viewer", "Developer", "Admin"])
async def test_roles_matrix(api: tuple, role: str) -> None:
    client, maker, headers, _, sid = await _setup(api, role)
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content == PNG


async def _drop_custom_roles(maker: async_sessionmaker) -> None:
    """Custom roles are this module's own; the shared fixture only clears users, and
    a leftover role breaks `test_seeded_roles_are_exactly_the_three_documented_roles`."""
    custom = "SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name LIKE 'r-%'"
    async with maker() as session:
        await session.execute(sa.text(f"DELETE FROM audit_logs WHERE user_id IN ({custom})"))
        await session.execute(sa.text(f"DELETE FROM users WHERE id IN ({custom})"))
        await session.execute(sa.text("DELETE FROM roles WHERE name LIKE 'r-%'"))
        await session.commit()


async def test_a_user_without_file_browse_is_refused(api: tuple) -> None:
    client, maker = api
    try:
        await _refused_without_file_browse(client, maker)
    finally:
        await _drop_custom_roles(maker)


async def _refused_without_file_browse(client: AsyncClient, maker: async_sessionmaker) -> None:
    owner_headers, owner = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, owner)
    headers, _ = await _login(client, maker, role_name="", actions=["session.view", "node.view"])
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        refused = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
        # A user who cannot view sessions at all gets the same refusal for a real
        # session and for one that does not exist.
        blind, _ = await _login(client, maker, role_name="", actions=["file.browse"])
        real = await client.post(_url(sid), json={"path": "a.png"}, headers=blind)
        missing = await client.post(_url(uuid.uuid4()), json={"path": "a.png"}, headers=blind)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "FORBIDDEN"
    assert real.status_code == 403
    assert missing.status_code in (403, 404)
    assert real.json()["error"]["message"] == refused.json()["error"]["message"]
    assert fake.calls == []


async def test_shell_session_refused(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid, runtime="shell")
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == 403, resp.text
    assert fake.calls == []


async def test_old_daemon_is_never_asked(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon(live=False)
    fake.add("a.png", PNG)
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "FILE_PREVIEW_UNSUPPORTED_NODE"
    assert fake.calls == [], "a node that did not report binary_preview must receive no frame"


async def test_preview_does_not_imply_download(api: tuple) -> None:
    """The node's download switch and live preview capability are independent."""
    client, _, headers, _, sid = await _setup(api)
    preview_only = FakePreviewDaemon(download_enabled=False)
    preview_only.add("a.png", PNG)
    with use_daemon(preview_only):
        preview = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
        download = await client.get(
            f"/api/sessions/{sid}/files/download?path=a.png", headers=headers
        )
    assert preview.status_code == 200 and preview.content == PNG
    assert download.status_code == 403
    assert download.json()["error"]["code"] == "FILE_DOWNLOAD_DISABLED"
    assert "filesystem.preview_open" in preview_only.types()
    assert "filesystem.download" in preview_only.types()

    download_only = FakePreviewDaemon(live=False)
    download_only.add("a.png", PNG)
    with use_daemon(download_only):
        preview = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
        download = await client.get(
            f"/api/sessions/{sid}/files/download?path=a.png", headers=headers
        )
    assert preview.status_code == 409
    assert preview.json()["error"]["code"] == "FILE_PREVIEW_UNSUPPORTED_NODE"
    assert download.status_code == 200 and download.content == PNG
    assert "filesystem.preview_open" not in download_only.types()
    assert "filesystem.download" in download_only.types()


async def test_flag_off_is_never_asked(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, headers, _, sid = await _setup(api)
    monkeypatch.setenv("CLIORA_BINARY_PREVIEW_ENABLED", "false")
    get_settings.cache_clear()
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert (
        resp.status_code == 409 and resp.json()["error"]["code"] == "FILE_PREVIEW_UNSUPPORTED_NODE"
    )
    assert fake.calls == []


async def test_the_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIORA_BINARY_PREVIEW_ENABLED", raising=False)
    get_settings.cache_clear()
    assert get_settings().binary_preview_enabled is False


async def test_offline_node(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    with use_daemon(FakePreviewDaemon(connected=False)) as fake:
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "NODE_OFFLINE"
    assert fake.calls == []


async def test_cookie_without_bearer_is_401(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    token = headers["Authorization"].split()[1]
    with use_daemon(FakePreviewDaemon()) as fake:
        resp = await client.post(
            _url(sid),
            json={"path": "a.png"},
            cookies={"access_token": token, "cliora_session": token},
        )
    assert resp.status_code == 401
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# Request shape: the path travels in a body, never in a URL
# --------------------------------------------------------------------------- #


async def test_path_never_in_url(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        for query in ({"path": "a.png"}, {"x": "1"}):
            resp = await client.post(
                _url(sid), params=query, json={"path": "a.png"}, headers=headers
            )
            assert resp.status_code == 400, (query, resp.text)
    assert fake.calls == []


async def test_requires_json_body(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        plain = await client.post(
            _url(sid),
            content=b'{"path":"a.png"}',
            headers={**headers, "Content-Type": "text/plain"},
        )
        huge = await client.post(
            _url(sid),
            content=json.dumps({"path": "a" * 30000}).encode(),
            headers={**headers, "Content-Type": "application/json"},
        )
        extra = await client.post(
            _url(sid), json={"path": "a.png", "mime": "image/png"}, headers=headers
        )
        not_object = await client.post(_url(sid), json=["a.png"], headers=headers)
        not_string = await client.post(_url(sid), json={"path": 7}, headers=headers)
        broken = await client.post(
            _url(sid), content=b"{", headers={**headers, "Content-Type": "application/json"}
        )
        escape = await client.post(_url(sid), json={"path": "../etc/passwd.png"}, headers=headers)
        absolute = await client.post(_url(sid), json={"path": "/etc/passwd"}, headers=headers)
    assert plain.status_code == 415
    assert huge.status_code == 413
    assert (
        extra.status_code == 422 and not_object.status_code == 422 and not_string.status_code == 422
    )
    assert broken.status_code == 422
    assert escape.status_code == 400 and absolute.status_code == 400
    assert escape.json()["error"]["code"] == "FILE_INVALID_PATH"
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #


async def test_headers_are_a_set(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG, w=300, h=200)
    fake.add("b.pdf", b"%PDF-1.7\n" + b"x" * 100 + b"\n%%EOF\n", mime="application/pdf")
    with use_daemon(fake):
        image = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
        pdf = await client.post(_url(sid), json={"path": "b.pdf"}, headers=headers)
    h = image.headers
    assert h["content-type"] == "application/octet-stream"
    assert h["x-content-type-options"] == "nosniff"
    assert h["content-length"] == str(len(PNG))
    assert h["cache-control"] == "no-store, private"
    assert h["vary"] == "Authorization"
    assert h["cross-origin-resource-policy"] == "same-origin"
    assert h["content-security-policy"] == "sandbox; default-src 'none'"
    assert h["x-cliora-preview-mime"] == "image/png" and h["x-cliora-preview-kind"] == "image"
    assert h["x-cliora-preview-width"] == "300" and h["x-cliora-preview-height"] == "200"
    assert "content-disposition" not in h
    assert pdf.headers["x-cliora-preview-kind"] == "pdf"
    assert "x-cliora-preview-width" not in pdf.headers
    assert "content-disposition" not in pdf.headers


async def test_mime_header_comes_from_enum(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    fake.mime_override = "image/svg+xml"  # a node that bypassed its own schema
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == 502, resp.text
    assert "svg" not in resp.text
    assert "filesystem.preview_close" in fake.types(), "the handle must still be released"
    assert fake.handles == {}


async def test_multi_chunk_stream_and_close_on_success(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    big = bytes(i % 251 for i in range(3 * CHUNK + 1234))
    fake.add("big.pdf", big, mime="application/pdf")
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert resp.status_code == 200 and resp.content == big
    assert fake.types() == ["filesystem.preview_open"] + ["filesystem.preview_chunk"] * 4 + [
        "filesystem.preview_close"
    ]
    assert fake.handles == {}


async def test_successive_previews_beyond_handle_limit(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon(max_handles=4)
    fake.add("a.png", PNG)
    with use_daemon(fake):
        for i in range(5):
            resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
            assert resp.status_code == 200, (i, resp.text)
            assert fake.handles == {}, f"preview {i + 1} left a handle open"
    assert fake.types().count("filesystem.preview_close") == 5


async def test_close_sent_on_error(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    big = bytes(3 * CHUNK)
    fake.add("big.pdf", big, mime="application/pdf")

    def timeout_on_second(index: int):
        if index == 1:
            raise ApiError(
                "REQUEST_TIMEOUT", "Node did not respond in time", status.HTTP_504_GATEWAY_TIMEOUT
            )
        return None

    fake.on_chunk = timeout_on_second
    with use_daemon(fake):
        timed_out = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert timed_out.status_code == 200  # headers were already sent
    assert len(timed_out.content) < len(big), "a stream cut short must be short, never padded"
    assert fake.types().count("filesystem.preview_close") == 1
    assert fake.handles == {}

    fake2 = FakePreviewDaemon()
    fake2.add("big.pdf", big, mime="application/pdf")
    fake2.on_chunk = (
        lambda index: _err(uuid.uuid4(), "FILE_PREVIEW_EXPIRED") if index == 1 else None
    )
    with use_daemon(fake2):
        expired = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert len(expired.content) < len(big)
    assert fake2.types().count("filesystem.preview_close") == 1


async def test_truncated_stream_is_error(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    big = bytes(4 * CHUNK)
    fake.add("big.pdf", big, mime="application/pdf")

    def drop_on_third(index: int):
        if index == 2:
            fake.connected = False
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)
        return None

    fake.on_chunk = drop_on_third
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert int(resp.headers["content-length"]) == len(big)
    assert len(resp.content) == 2 * CHUNK < len(big)


async def test_budget_total(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, headers, _, sid = await _setup(api)
    monkeypatch.setenv("CLIORA_FILE_PREVIEW_TOTAL_SECONDS", "0.3")
    get_settings.cache_clear()
    fake = FakePreviewDaemon()
    big = bytes(4 * CHUNK)
    fake.add("big.pdf", big, mime="application/pdf")

    async def slow(index: int):
        await asyncio.sleep(0.2)

    fake.on_chunk = slow
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert len(resp.content) < len(big), "the 60 s (here 0.3 s) budget must cut the stream"
    assert fake.types().count("filesystem.preview_close") == 1


async def test_chunk_that_disagrees_with_the_handle_aborts(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    big = bytes(2 * CHUNK)
    fake.add("big.pdf", big, mime="application/pdf")
    fake.on_chunk = (
        lambda index: _msg(
            "filesystem.preview_data",
            uuid.uuid4(),
            {
                "preview_id": f"{PID_PREFIX}{1:015d}",
                "index": index,
                "data": base64.b64encode(b"short").decode(),
            },
        )
        if index == 0
        else None
    )
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "big.pdf"}, headers=headers)
    assert resp.content == b"", "a chunk of the wrong size must not be forwarded"
    assert fake.types().count("filesystem.preview_close") == 1


async def test_busy_limits(api: tuple) -> None:
    client, maker, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon(max_handles=10)
    fake.add("a.pdf", bytes(CHUNK * 2), mime="application/pdf")
    gate = asyncio.Event()
    entered = asyncio.Queue()

    async def hold(index: int):
        await entered.put(index)
        await gate.wait()

    fake.on_chunk = hold
    with use_daemon(fake):
        first = asyncio.create_task(client.post(_url(sid), json={"path": "a.pdf"}, headers=headers))
        second = asyncio.create_task(
            client.post(_url(sid), json={"path": "a.pdf"}, headers=headers)
        )
        await asyncio.wait_for(entered.get(), 5)
        await asyncio.wait_for(entered.get(), 5)
        third = await client.post(_url(sid), json={"path": "a.pdf"}, headers=headers)
        # Another user on the same node is not limited by this user's two.
        other_headers, _ = await _login(client, maker, role_name="Developer")
        other = asyncio.create_task(
            client.post(_url(sid), json={"path": "a.pdf"}, headers=other_headers)
        )
        await asyncio.wait_for(entered.get(), 5)
        gate.set()
        results = await asyncio.gather(first, second, other)
    assert third.status_code == 429 and third.json()["error"]["code"] == "FILE_PREVIEW_BUSY"
    assert all(r.status_code == 200 for r in results)
    assert fake.handles == {}


# --------------------------------------------------------------------------- #
# Denials and audit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("error", "http_status"),
    [
        ({"code": "FILE_DENIED", "reason": "not_regular"}, 403),
        ({"code": "FILE_NOT_FOUND", "reason": "not_found"}, 404),
        ({"code": "FILE_PERMISSION_DENIED", "reason": "permission"}, 403),
        ({"code": "FILE_TOO_LARGE", "reason": "too_large", "size": 9000000, "limit": 8388608}, 413),
        ({"code": "FILE_PREVIEW_UNSUPPORTED", "reason": "unsupported_type"}, 415),
        ({"code": "FILE_PREVIEW_INVALID", "reason": "malformed"}, 422),
        ({"code": "FILE_PREVIEW_LIMIT", "reason": "pixels"}, 413),
    ],
)
async def test_in_band_denial_maps_to_its_own_status(
    api: tuple, error: dict, http_status: int
) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.denials["x.png"] = error
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "x.png"}, headers=headers)
    assert resp.status_code == http_status, resp.text
    body = resp.json()["error"]
    assert body["code"] == error["code"]
    assert body["details"]["reason"] == error["reason"]
    if "limit" in error:
        assert (
            body["details"]["size"] == error["size"] and body["details"]["limit"] == error["limit"]
        )
    assert "x.png" not in resp.text
    assert fake.types() == ["filesystem.preview_open"], (
        "a denial holds no handle, so nothing to close"
    )


@pytest.mark.parametrize(
    ("code", "http_status"), [("FILE_PREVIEW_DISABLED", 403), ("NODE_BUSY", 503)]
)
async def test_node_level_refusal(api: tuple, code: str, http_status: int) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()

    async def refuse(node_id, type_, payload, *, timeout_seconds, request_id=None):
        fake.calls.append((type_, payload))
        return _err(node_id, code)

    fake.request = refuse  # type: ignore[method-assign]
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    assert resp.status_code == http_status and resp.json()["error"]["code"] == code


async def test_sensitive_denial_audit_persists_after_403(api: tuple) -> None:
    client, maker, headers, uid, sid = await _setup(api, "Viewer")
    fake = FakePreviewDaemon()
    fake.denials["config/.env.png"] = {"code": "FILE_DENIED", "reason": "dotenv"}
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": "config/.env.png"}, headers=headers)
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "FILE_DENIED"
    # Read on ANOTHER session, after the response: the row was committed before the
    # route raised, or it would have been discarded with the request's session.
    rows = await _audit_rows(maker, "file.sensitive_read_denied")
    assert len(rows) == 1
    meta = rows[0][1]
    assert meta["classification"] == "dotenv" and meta["extension"] == "png"
    assert set(meta) <= {"classification", "extension", "request_id", "source"}
    assert "config" not in json.dumps(meta) and ".env" not in json.dumps(meta)


async def test_success_audit_has_no_path(api: tuple) -> None:
    client, maker, headers, uid, sid = await _setup(api, "Viewer")
    canary = f"bp-canary-{uuid.uuid4().hex[:12]}/機密-{uuid.uuid4().hex[:12]}.pdf"
    fake = FakePreviewDaemon()
    fake.add(canary, b"%PDF-1.7\n%%EOF\n", mime="application/pdf")
    with use_daemon(fake):
        resp = await client.post(_url(sid), json={"path": canary}, headers=headers)
    assert resp.status_code == 200
    rows = await _audit_rows(maker, "file.binary_preview")
    assert len(rows) == 1
    meta = rows[0][1]
    assert {"kind", "mime", "size_bytes"} <= set(meta)
    assert meta["kind"] == "pdf" and meta["mime"] == "application/pdf" and meta["size_bytes"] == 15
    assert set(meta) - {"kind", "mime", "size_bytes"} <= {"request_id", "source"}
    for forbidden in (
        "path",
        "rel_path",
        "filename",
        "name",
        "extension",
        "content",
        "data",
        "bytes",
    ):
        assert forbidden not in meta
    blob = json.dumps(meta, ensure_ascii=False)
    directory, name = canary.split("/")
    for fragment in (directory, name, name.rsplit(".", 1)[0], directory.split("-")[-1]):
        assert fragment not in blob, fragment


async def test_success_audit_on_own_session(api: tuple) -> None:
    client, maker, headers, uid, sid = await _setup(api, "Viewer")
    fake = FakePreviewDaemon()
    fake.add("a.png", PNG)
    with use_daemon(fake):
        await client.post(_url(sid), json={"path": "a.png"}, headers=headers)
    rows = await _audit_rows(maker, "file.binary_preview")
    assert len(rows) == 1
    async with maker() as session:
        row = (
            await session.execute(
                sa.text(
                    "select user_id, session_id, node_id from audit_logs "
                    "where action = 'file.binary_preview'"
                )
            )
        ).one()
    assert row[0] == uid and row[1] == sid and row[2] is not None

    # A stream that does not finish records no success.
    fake2 = FakePreviewDaemon()
    fake2.add("b.pdf", bytes(3 * CHUNK), mime="application/pdf")
    fake2.on_chunk = (
        lambda index: _err(uuid.uuid4(), "FILE_PREVIEW_EXPIRED") if index == 1 else None
    )
    with use_daemon(fake2):
        await client.post(_url(sid), json={"path": "b.pdf"}, headers=headers)
    assert len(await _audit_rows(maker, "file.binary_preview")) == 1


async def test_log_has_no_path(api: tuple, caplog: pytest.LogCaptureFixture) -> None:
    client, _, headers, _, sid = await _setup(api, "Viewer")
    marker = uuid.uuid4().hex[:12]
    canary = f"bp-canary-{marker}/機密-{marker}.pdf"
    denied = f"bp-canary-{marker}/.env.png"
    fake = FakePreviewDaemon()
    fake.add(canary, b"%PDF-1.7\n%%EOF\n", mime="application/pdf")
    fake.denials[denied] = {"code": "FILE_DENIED", "reason": "dotenv"}
    caplog.set_level(logging.DEBUG)
    with use_daemon(fake):
        ok = await client.post(_url(sid), json={"path": canary}, headers=headers)
        refused = await client.post(_url(sid), json={"path": denied}, headers=headers)
    assert ok.status_code == 200 and refused.status_code == 403
    text = "\n".join(
        [r.getMessage() for r in caplog.records]
        + [json.dumps(r.__dict__, default=str, ensure_ascii=False) for r in caplog.records]
    )
    assert "binary_preview" in text, "the relay must log something, or this test proves nothing"
    for needle in (marker, quote(marker), quote(f"機密-{marker}"), "機密"):
        assert needle not in text, needle


async def test_read_content_unchanged(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    with use_daemon(FakePreviewDaemon()) as fake:
        resp = await client.get(
            f"/api/sessions/{sid}/files/content", params={"path": "a.png"}, headers=headers
        )
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == "FILE_BINARY"
    assert fake.types() == ["filesystem.read"]


# --------------------------------------------------------------------------- #
# The full middleware stack, driven like a real server (BP-OM-11)
# --------------------------------------------------------------------------- #


class RawClient:
    """Calls the ASGI app directly, with a send() the test can hold (a slow client)
    and a receive() the test can turn into a disconnect."""

    def __init__(self, path: str, body: bytes, headers: dict[str, str]) -> None:
        self.scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            + [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }
        self.body = body
        self.sent_body = False
        self.disconnect = asyncio.Event()
        self.release = asyncio.Semaphore(0)
        self.chunks: list[bytes] = []
        self.status: int | None = None
        self.chunk_arrived = asyncio.Event()

    async def receive(self) -> dict:
        if not self.sent_body:
            self.sent_body = True
            return {"type": "http.request", "body": self.body, "more_body": False}
        await self.disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
        elif message["type"] == "http.response.body" and message.get("body"):
            self.chunks.append(message["body"])
            self.chunk_arrived.set()
            if self.disconnect.is_set():
                return  # like uvicorn: a send after the client left is a no-op
            await self.release.acquire()  # the client is slow: one chunk per release

    def run(self) -> asyncio.Task:
        return asyncio.create_task(app(self.scope, self.receive, self.send))


async def test_stream_backpressure(api: tuple) -> None:
    client, _, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("big.pdf", bytes(8 * CHUNK), mime="application/pdf")
    with use_daemon(fake):
        raw = RawClient(_url(sid), json.dumps({"path": "big.pdf"}).encode(), headers)
        task = raw.run()
        await asyncio.wait_for(raw.chunk_arrived.wait(), 5)
        await asyncio.sleep(0.3)  # a slow client: the first chunk is not yet consumed
        pulled_while_stalled = fake.types().count("filesystem.preview_chunk")
        for _ in range(8):
            raw.release.release()
        await asyncio.wait_for(task, 10)
    assert raw.status == 200 and b"".join(raw.chunks) == bytes(8 * CHUNK)
    # Pull-based: while the client holds the first chunk, Central may have at most
    # one more in flight (BaseHTTPMiddleware's hand-off), never the whole file.
    assert pulled_while_stalled <= 2, pulled_while_stalled
    assert fake.types().count("filesystem.preview_close") == 1


async def test_disconnect_sends_close(api: tuple) -> None:
    client, maker, headers, _, sid = await _setup(api)
    fake = FakePreviewDaemon()
    fake.add("big.pdf", bytes(8 * CHUNK), mime="application/pdf")
    with use_daemon(fake):
        raw = RawClient(_url(sid), json.dumps({"path": "big.pdf"}).encode(), headers)
        task = raw.run()
        await asyncio.wait_for(raw.chunk_arrived.wait(), 5)
        raw.disconnect.set()
        raw.release.release()
        await asyncio.wait_for(task, 10)
        for _ in range(50):
            if "filesystem.preview_close" in fake.types():
                break
            await asyncio.sleep(0.02)
    assert fake.types().count("filesystem.preview_close") == 1
    assert fake.handles == {}
    assert fake.types().count("filesystem.preview_chunk") < 8
    assert (
        metrics.counter_value(
            metrics.FILESYSTEM_REQUEST_TOTAL, op="binary_preview", code="CANCELLED"
        )
        == 1
    )
    assert await _audit_rows(maker, "file.binary_preview") == [], (
        "a cancelled stream is not a success"
    )
