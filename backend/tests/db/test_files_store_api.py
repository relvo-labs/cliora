"""HTTP file-upload API against the real schema (FU-05, ADR 0026).

The daemon round-trip is faked by overriding the files router's get_registry.
These tests assert the properties the design leans on rather than the happy path
alone, and the list is deliberately the mirror image of test_files_upload_api's:

* the relayed frame DOES name its destination — that is the difference between
  this path and image drop — but a filename can never hold a path,
* a collision is refused and reported as such, because never overwriting is the
  property that lets this path exist without version tokens or an undo,
* the size cap holds even when Content-Length lies (shared code with image drop,
  so there is a regression test for image drop here too),
* the audit records the user-chosen path and the byte count, never the content,
* and `file.upload` still means Viewer cannot do any of it.
"""

from __future__ import annotations

import base64
import urllib.parse

import pytest
import sqlalchemy as sa
from fastapi import status
from httpx import AsyncClient
from test_files_api import FakeRegistry, _err_msg, _msg, use_registry
from test_files_upload_api import PNG, _login, _make_session

from app import metrics
from app.db.models import AuditLog
from app.services import audit

pytestmark = pytest.mark.asyncio

CSV = b"a,b\n1,2\n"


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


def _store_registry(path: str = "datasets/data.csv", size: int = len(CSV)) -> FakeRegistry:
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.stored",
        node_id,
        {"path": path, "size": size, "modified_at": "2026-08-05T09:00:00Z"},
    )
    return fake


async def _put(
    client: AsyncClient,
    sid,
    headers,
    body: bytes,
    *,
    directory: str = "datasets",
    filename: str = "data.csv",
    ctype: str = "application/octet-stream",
    **kw,
):
    query = urllib.parse.urlencode({"directory": directory, "filename": filename})
    return await client.post(
        f"/api/sessions/{sid}/files/upload?{query}",
        content=body,
        headers={**headers, "content-type": ctype, **kw.pop("extra_headers", {})},
        **kw,
    )


async def test_developer_can_upload_a_file(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert resp.json()["path"] == "datasets/data.csv"
    assert resp.json()["size"] == len(CSV)


async def test_the_relayed_frame_names_the_destination(api: tuple) -> None:
    """The mirror of image drop's test_the_relayed_frame_carries_no_filename.

    There, the assertion is that no naming field exists. Here the caller must name
    the destination — a name is what makes a file useful — so the assertion is that
    the two halves travel as separate fields and nothing asks to replace anything.
    """
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        await _put(client, sid, headers, CSV)
    type_, payload = fake.calls[-1][0], fake.calls[-1][1]
    assert type_ == "filesystem.store"
    assert set(payload) == {"session_id", "directory", "filename", "data"}
    assert payload["directory"] == "datasets"
    assert payload["filename"] == "data.csv"
    assert base64.b64decode(payload["data"]) == CSV
    for forbidden in ("overwrite", "mode", "mime", "precondition", "revision"):
        assert forbidden not in payload


async def test_the_workspace_root_is_a_valid_destination(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry(path="notes.md")
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV, directory=".", filename="notes.md")
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert fake.calls[-1][1]["directory"] == "."


async def test_an_empty_file_can_be_uploaded(api: tuple) -> None:
    """A placeholder or an empty __init__.py is a legitimate upload, and all three
    wire consumers decode the empty string to zero bytes."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry(path="pkg/__init__.py", size=0)
    with use_registry(fake):
        resp = await _put(client, sid, headers, b"", directory="pkg", filename="__init__.py")
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert fake.calls[-1][1]["data"] == ""


@pytest.mark.parametrize(
    "filename",
    [
        "sub/data.csv",  # a filename is not a path
        "../escape.csv",
        ".",
        "..",
        "a\x01b.csv",  # control character
        "x" * 256,  # over 255 bytes
        "測" * 84 + ".csv",  # 88 characters but 256 BYTES
    ],
)
async def test_bad_filenames_are_refused_before_relay(api: tuple, filename: str) -> None:
    """Every one of these must be refused by Central without occupying a node
    connection. The last two are the interesting pair: the wire schema's maxLength
    counts code points, so a CJK name can pass a character bound and still exceed
    255 bytes — the unit is enforced where it is known.
    """
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV, filename=filename)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert resp.json()["error"]["code"] == "FILE_INVALID_NAME"
    assert fake.calls == []


async def test_a_percent_encoded_separator_cannot_become_a_path(api: tuple) -> None:
    """URL encoding is the only way a filename could smuggle a separator through, so
    validation has to happen after decoding. `%2F` reaches the handler as `/`
    (measured: plan/15/07-open-measurements.md §2), and that is what is refused.
    """
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        resp = await client.post(
            f"/api/sessions/{sid}/files/upload?directory=.&filename=..%2F..%2Fetc%2Fpasswd",
            content=CSV,
            headers={**headers, "content-type": "application/octet-stream"},
        )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    assert resp.json()["error"]["code"] == "FILE_INVALID_NAME"
    assert fake.calls == []


async def test_a_non_ascii_filename_survives_the_query_string(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry(path="docs/測試資料.csv")
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV, directory="docs", filename="測試資料.csv")
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert fake.calls[-1][1]["filename"] == "測試資料.csv"


async def test_a_plus_in_a_filename_is_not_turned_into_a_space(api: tuple) -> None:
    """`+` means space in a query string, so a client that concatenates instead of
    percent-encoding would silently rename the file. urlencode gets this right and
    this test says so, because the failure would be invisible.
    """
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry(path="a+b.txt")
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV, directory=".", filename="a+b.txt")
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert fake.calls[-1][1]["filename"] == "a+b.txt"


async def test_escaping_directories_are_refused_before_relay(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    for directory in ("/etc", "~/x", "../elsewhere", "a/../../b"):
        with use_registry(fake):
            resp = await _put(client, sid, headers, CSV, directory=directory)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, (directory, resp.text)
        assert resp.json()["error"]["code"] == "FILE_INVALID_PATH"
    assert fake.calls == []


async def test_viewer_may_browse_but_not_upload(api: tuple) -> None:
    client, maker = api
    dev_headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    viewer_headers, _ = await _login(client, maker, role_name="Viewer")
    fake = _store_registry()
    with use_registry(fake):
        resp = await _put(client, sid, viewer_headers, CSV)
    assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
    assert fake.calls == []
    # And the same user can still read: this is a different permission, not a
    # different session.
    with use_registry(fake):
        tree = await client.get(f"/api/sessions/{sid}/files/tree", headers=viewer_headers)
    assert tree.status_code != status.HTTP_403_FORBIDDEN


async def test_oversize_is_refused_before_relay(api: tuple) -> None:
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        resp = await _put(client, sid, headers, b"x" * (4 * 1024 * 1024 + 1))
    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, resp.text
    assert fake.calls == []


async def test_a_lying_content_length_does_not_get_past_the_cap(api: tuple) -> None:
    """The shared two-stage reader: the declared length is checked first so an
    oversize body is refused before transfer, and the running total is checked again
    because Content-Length is a claim by the sender."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()

    async def chunks():
        for _ in range(5):
            yield b"y" * (1024 * 1024)

    with use_registry(fake):
        resp = await client.post(
            f"/api/sessions/{sid}/files/upload?directory=.&filename=big.bin",
            content=chunks(),
            headers={**headers, "content-type": "application/octet-stream"},
        )
    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, resp.text
    assert fake.calls == []


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("FILE_EXISTS", status.HTTP_409_CONFLICT),
        ("FILE_UPLOAD_NO_SPACE", status.HTTP_507_INSUFFICIENT_STORAGE),
        ("FILE_UPLOAD_QUOTA_EXCEEDED", status.HTTP_429_TOO_MANY_REQUESTS),
        ("FILE_UPLOAD_DISABLED", status.HTTP_403_FORBIDDEN),
        ("FILE_UPLOAD_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE),
    ],
)
async def test_daemon_refusals_keep_their_own_code(api: tuple, code: str, expected: int) -> None:
    """Each of these has a different next step for the user, so none of them may
    collapse into INTERNAL_ERROR — a full quota reported as "the server broke" sends
    the user to the wrong place."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _err_msg(node_id, code)
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV)
    assert resp.status_code == expected, resp.text
    assert resp.json()["error"]["code"] == code


async def test_a_successful_upload_is_audited_with_the_path_but_not_the_bytes(api: tuple) -> None:
    """W3, and the reason the path is recorded differs from image drop's: there the
    platform chose the name, here the user did — and it is still recordable, because
    the user already sees it. Without it, "who put what here" has only a counter."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = _store_registry()
    with use_registry(fake):
        resp = await _put(client, sid, headers, CSV)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text

    async with maker() as session:
        rows = (
            (await session.execute(sa.select(AuditLog).where(AuditLog.action == audit.FILE_UPLOAD)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    meta = rows[0].audit_metadata or {}
    assert meta["path"] == "datasets/data.csv"
    assert meta["bytes"] == len(CSV)
    # `source` is what keeps the two upload paths apart without a second action key.
    assert meta["source"] == "file"
    # No mime on this path: nothing sniffs a type, and an empty field would be
    # worse than an absent one.
    assert "mime" not in meta
    blob = repr(meta)
    assert "a,b" not in blob


async def test_image_drop_still_records_its_own_source(api: tuple) -> None:
    """Regression: the audit helper is shared now, so the older path has to keep
    saying which one it is — and keep its mime."""
    client, maker = api
    headers, uid = await _login(client, maker, role_name="Developer")
    sid = await _make_session(maker, uid)
    fake = FakeRegistry()
    fake.responder = lambda node_id, type_, payload: _msg(
        "filesystem.uploaded",
        node_id,
        {
            "path": ".cliora/uploads/2026-08-05/01K1ZQ9F3B7T2M8V4X6Y0N5R3D.png",
            "mime": "image/png",
            "size": len(PNG),
            "modified_at": "2026-08-05T09:00:00Z",
        },
    )
    with use_registry(fake):
        resp = await client.post(
            f"/api/sessions/{sid}/files/images",
            content=PNG,
            headers={**headers, "content-type": "image/png"},
        )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    async with maker() as session:
        rows = (
            (await session.execute(sa.select(AuditLog).where(AuditLog.action == audit.FILE_UPLOAD)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    meta = rows[0].audit_metadata or {}
    assert meta["source"] == "image"
    assert meta["mime"] == "image/png"
