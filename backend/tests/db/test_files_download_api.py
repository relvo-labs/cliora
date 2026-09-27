"""HTTP file-download API against the real schema (FD-05, ADR 0028).

The daemon round-trip is faked by overriding the files router's get_registry.
These tests assert the properties the design leans on rather than the happy path
alone, and they are the read-direction mirror of test_files_store_api's list:

* the relayed frame names a file and nothing else — no range, offset or encoding,
  which is what keeps this path free of an assembly state machine,
* the response is always an opaque attachment, because a workspace `.html` served
  inline from the console's origin is stored XSS with the platform's cookies in
  scope,
* the filename survives in both Content-Disposition forms, including non-ASCII,
* a refusal from the node keeps its own code rather than collapsing to a 500,
* a Viewer CAN download — that is the deliberate, documented consequence of
  reusing `file.browse` (ADR 0028 §5), and a test that pins it is how a future
  change to that has to be made on purpose,
* and a successful download is audited with the path and byte count, never the
  content.
"""

from __future__ import annotations

import base64
import urllib.parse

import pytest
import sqlalchemy as sa
from fastapi import status
from httpx import AsyncClient
from test_files_api import FakeRegistry, _err_msg, _msg, use_registry
from test_files_upload_api import _login, _make_session

from app import metrics
from app.db.models import AuditLog
from app.services import audit

pytestmark = pytest.mark.asyncio

CSV = b"a,b\n1,2\n"
# Real binary, not a placeholder string: the point of this path is that content
# the preview refuses still travels intact, so the bytes have to be able to fail.
PNG_BYTES = bytes.fromhex("89504e470d0a1a0a0000000d49484452")


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


def _download_registry(path: str = "datasets/data.csv", data: bytes = CSV) -> FakeRegistry:
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.downloaded",
        node_id,
        {
            "path": path,
            "size": len(data),
            "modified_at": "2026-09-16T09:00:00Z",
            "data": base64.b64encode(data).decode("ascii"),
        },
    )
    return fake


def _refusing_registry(code: str) -> FakeRegistry:
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _err_msg(node_id, code)
    return fake


async def _get(client: AsyncClient, sid, headers, *, path: str = "datasets/data.csv"):
    query = urllib.parse.urlencode({"path": path})
    return await client.get(f"/api/sessions/{sid}/files/download?{query}", headers=headers)


async def test_developer_downloads_the_exact_bytes(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry()):
        resp = await _get(client, sid, headers)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.content == CSV


async def test_binary_content_survives_the_round_trip(api: tuple) -> None:
    """The whole reason this endpoint exists beside /content, which refuses it."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry(path="assets/logo.png", data=PNG_BYTES)):
        resp = await _get(client, sid, headers, path="assets/logo.png")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == PNG_BYTES


async def test_an_empty_file_downloads_as_zero_bytes(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry(path="src/__init__.py", data=b"")):
        resp = await _get(client, sid, headers, path="src/__init__.py")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == b""


async def test_the_relayed_frame_names_a_file_and_nothing_else(api: tuple) -> None:
    """No range, offset, encoding or disposition on the wire (ADR 0028 §2) — which
    is what keeps this path free of an assembly state machine."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _download_registry()
    with use_registry(fake):
        await _get(client, sid, headers)

    type_, payload = fake.calls[-1]
    assert type_ == "filesystem.download"
    assert set(payload) == {"session_id", "path"}
    assert payload["path"] == "datasets/data.csv"


async def test_the_response_is_always_an_opaque_attachment(api: tuple) -> None:
    """A workspace .html served inline from the console's origin is stored XSS with
    the platform's cookies in scope (ADR 0028 §4). All three headers are the fix
    and none of them is decoration."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry(path="report.html", data=b"<script>alert(1)</script>")):
        resp = await _get(client, sid, headers, path="report.html")

    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-disposition"].startswith("attachment;")
    assert resp.headers["cache-control"] == "no-store"


async def test_the_filename_travels_in_both_disposition_forms(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry(path="報告/年度統計.csv")):
        resp = await _get(client, sid, headers, path="報告/年度統計.csv")

    disposition = resp.headers["content-disposition"]
    # The starred form carries the real name; the plain one is only a fallback and
    # must never be a transliteration pretending to be the name.
    assert "filename*=UTF-8''" in disposition
    assert urllib.parse.quote("年度統計.csv", safe="") in disposition
    # Nothing survives of the stem, so `download` stands in for it - but the
    # extension is kept, because it is the half of a fallback name that decides
    # which application opens the file.
    assert 'filename="download.csv"' in disposition


async def test_a_quote_in_a_filename_cannot_break_the_header(api: tuple) -> None:
    """The ASCII fallback is the header-injection surface: `quote` only protects
    the starred form."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry(path='odd"name.txt')):
        resp = await _get(client, sid, headers, path="odd.txt")

    disposition = resp.headers["content-disposition"]
    assert disposition.count('"') == 2
    assert 'filename="oddname.txt"' in disposition


async def test_a_viewer_can_download(api: tuple) -> None:
    """Deliberate and documented (ADR 0028 §5): download reuses `file.browse`,
    which Viewer holds. This test exists so that changing it has to be a decision
    rather than a side effect."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Viewer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry()):
        resp = await _get(client, sid, headers)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == CSV


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("FILE_DENIED", status.HTTP_403_FORBIDDEN),
        ("FILE_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE),
        ("FILE_NOT_FOUND", status.HTTP_404_NOT_FOUND),
        ("FILE_DOWNLOAD_DISABLED", status.HTTP_403_FORBIDDEN),
        ("WORKSPACE_PERMISSION_DENIED", status.HTTP_403_FORBIDDEN),
    ],
)
async def test_a_node_refusal_keeps_a_usable_status(
    api: tuple, code: str, expected_status: int
) -> None:
    """Each refusal has a different next step for the user, so collapsing them into
    one 500 would tell someone whose file is too large that the server broke."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_refusing_registry(code)):
        resp = await _get(client, sid, headers)

    assert resp.status_code == expected_status, resp.text
    # The error path is JSON even though the success path is bytes.
    assert resp.headers["content-type"].startswith("application/json")


async def test_an_escaping_path_never_reaches_the_node(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _download_registry()
    with use_registry(fake):
        resp = await _get(client, sid, headers, path="../../etc/shadow")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert fake.calls == []


async def test_a_successful_download_is_audited_without_content(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_download_registry()):
        assert (await _get(client, sid, headers)).status_code == status.HTTP_200_OK

    async with maker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(AuditLog).where(AuditLog.action == audit.FILE_DOWNLOAD)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    metadata = rows[0].audit_metadata
    assert metadata["path"] == "datasets/data.csv"
    assert metadata["size_bytes"] == len(CSV)
    assert rows[0].user_id == uid
    # `size_bytes` rather than `bytes`, which is an exact-match forbidden key and
    # would be stripped from every audit API response.
    assert "bytes" not in metadata
    blob = str(metadata)
    assert "a,b" not in blob


async def test_a_refused_download_writes_no_audit_row(api: tuple) -> None:
    """Only the success is audited here — the inverse of the preview path, and the
    reason is that only a success leaves a copy behind (ADR 0028 §7)."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    with use_registry(_refusing_registry("FILE_DENIED")):
        await _get(client, sid, headers)

    async with maker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(AuditLog).where(AuditLog.action == audit.FILE_DOWNLOAD)
                )
            )
            .scalars()
            .all()
        )
    assert rows == []
