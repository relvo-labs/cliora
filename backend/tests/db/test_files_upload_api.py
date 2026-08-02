"""HTTP image-drop API against the real schema (WF-06, ADR 0024).

The daemon round-trip is faked by overriding the files router's get_registry.
These tests assert the properties the design leans on, not the happy path alone:
`file.upload` is a different permission from `file.browse` (Viewer must not have
it), the relayed frame carries no filename, the size cap holds even when
Content-Length lies, the content decides the type, and a successful drop is
audited with the path but never the bytes.
"""

from __future__ import annotations

import base64
import uuid

import pytest
import sqlalchemy as sa
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_files_api import FakeRegistry, _err_msg, _msg, use_registry

from app import metrics
from app.db.models import AuditLog, Node, NodeWorkspaceRoot, Role, TerminalSession, User
from app.security.passwords import hash_password
from app.services import audit

pytestmark = pytest.mark.asyncio

# A real 1x1 PNG. Using actual image bytes matters: the endpoint sniffs the
# leading bytes, so a placeholder string would pass or fail for the wrong reason.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c636000000200010005fe02fe0000000049454e44ae426082"
)
STORED_PATH = ".cliora/uploads/2026-08-05/01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png"


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


def _upload_registry() -> FakeRegistry:
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.uploaded",
        node_id,
        {
            "path": STORED_PATH,
            "mime": "image/png",
            "size": len(PNG),
            "modified_at": "2026-08-05T09:00:00Z",
        },
    )
    return fake


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


async def _make_session(maker: async_sessionmaker, owner_id: uuid.UUID) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
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


async def _post(client: AsyncClient, sid, headers, body: bytes, *, ctype="image/png", **kw):
    return await client.post(
        f"/api/sessions/{sid}/files/images",
        content=body,
        headers={**headers, "content-type": ctype, **kw.pop("extra_headers", {})},
        **kw,
    )


async def test_developer_can_drop_an_image(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    with use_registry(fake):
        resp = await _post(client, sid, headers, PNG)

    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body = resp.json()
    assert body["path"] == STORED_PATH
    assert body["mime"] == "image/png"
    # The browser learns a workspace-relative path and nothing about the node's
    # real filesystem layout (ADR 0014).
    assert not body["path"].startswith("/")


async def test_the_relayed_frame_carries_no_filename(api: tuple) -> None:
    """The single property that makes one write path safe (ADR 0024 §3)."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    with use_registry(fake):
        await _post(client, sid, headers, PNG)

    type_, payload = fake.calls[-1]
    assert type_ == "filesystem.upload"
    assert set(payload) == {"session_id", "data"}
    assert base64.b64decode(payload["data"]) == PNG


async def test_viewer_may_browse_but_not_upload(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Viewer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    with use_registry(fake):
        resp = await _post(client, sid, headers, PNG)

    assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
    # And nothing was relayed: the refusal happens before the node is involved.
    assert fake.calls == []


@pytest.mark.parametrize(
    ("ctype", "body"),
    [
        ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'),
        ("application/pdf", b"%PDF-1.7\n"),
        ("text/plain", b"hello"),
        ("application/octet-stream", PNG),
    ],
)
async def test_unsupported_declared_types_are_refused(api: tuple, ctype: str, body: bytes) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    with use_registry(fake):
        resp = await _post(client, sid, headers, body, ctype=ctype)

    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, resp.text
    assert fake.calls == []


async def test_content_decides_the_type_not_the_header(api: tuple) -> None:
    """An ELF announced as a PNG must not reach the node."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    with use_registry(fake):
        resp = await _post(client, sid, headers, b"\x7fELF" + b"\x00" * 64)

    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, resp.text
    assert fake.calls == []


async def test_oversize_is_refused_before_relay(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    big = PNG + b"\x00" * (4 * 1024 * 1024 + 1)
    with use_registry(fake):
        resp = await _post(client, sid, headers, big)

    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, resp.text
    assert fake.calls == []


async def test_a_lying_content_length_does_not_get_past_the_cap(api: tuple) -> None:
    """Content-Length is the sender's claim, so the read is capped as well."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _upload_registry()
    big = PNG + b"\x00" * (4 * 1024 * 1024 + 1)

    async def _stream():
        yield big

    with use_registry(fake):
        resp = await client.post(
            f"/api/sessions/{sid}/files/images",
            content=_stream(),
            headers={**headers, "content-type": "image/png"},
        )

    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, resp.text
    assert fake.calls == []


async def test_a_daemon_denial_surfaces_as_its_code(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _err_msg(node_id, "FILE_UPLOAD_QUOTA_EXCEEDED")
    with use_registry(fake):
        resp = await _post(client, sid, headers, PNG)

    assert resp.status_code >= 400
    assert resp.json()["error"]["code"] == "FILE_UPLOAD_QUOTA_EXCEEDED"


async def test_a_successful_drop_is_audited_with_the_path_but_not_the_bytes(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_upload_registry()):
        resp = await _post(client, sid, headers, PNG)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text

    async with maker() as session:
        rows = (
            (await session.execute(sa.select(AuditLog).where(AuditLog.action == audit.FILE_UPLOAD)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    meta = rows[0].audit_metadata or {}
    # The path is recorded because the platform chose it (ADR 0024 W3)...
    assert meta.get("path") == STORED_PATH
    assert meta.get("mime") == "image/png"
    assert meta.get("bytes") == len(PNG)
    # ...but nothing that could carry the image or the user's own filename.
    blob = repr(meta)
    assert "data" not in meta
    assert base64.b64encode(PNG).decode()[:24] not in blob
