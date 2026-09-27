import base64
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.protocol import ProtocolError, decode_binary, decode_control, encode_binary
from app.protocol.codec import LARGE_FRAME_TYPES, MAX_FILE_PAYLOAD, MAX_PAYLOAD

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "contracts/v1/fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())


@pytest.mark.parametrize("item", MANIFEST["json"], ids=lambda item: item["path"])
def test_json_manifest(item: dict) -> None:
    raw = (FIXTURES / item["path"]).read_bytes()
    if item["accept"]:
        assert decode_control(raw).type == item["type"]
    else:
        with pytest.raises(ProtocolError) as error:
            decode_control(raw)
        assert error.value.code == item["code"]


@pytest.mark.parametrize("item", MANIFEST["binary"], ids=lambda item: item["name"])
def test_binary_manifest(item: dict) -> None:
    if item["accept"]:
        session_id = UUID(item["session_id"])
        payload = bytes.fromhex(item["payload_hex"])
        frame = encode_binary(item["kind"], session_id, payload)
        kind, decoded_id, decoded = decode_binary(frame)
        assert (kind, decoded_id, decoded) == (item["kind"], session_id, payload)
    else:
        with pytest.raises(ProtocolError) as error:
            decode_binary(bytes.fromhex(item["hex"]))
        assert error.value.code == item["code"]


@pytest.mark.parametrize("raw", [b"", b"\x01\x02", b"\x01\x03" + bytes(16) + b"x"])
def test_binary_invalid_never_leaks_payload(raw: bytes) -> None:
    with pytest.raises(ProtocolError) as error:
        decode_binary(raw)
    assert "x" not in error.value.safe_message


def test_oversize_control_and_binary_are_rejected() -> None:
    with pytest.raises(ProtocolError) as control_error:
        decode_control(b'{"x":"' + b"a" * (64 * 1024) + b'"}')
    assert control_error.value.code == "FRAME_TOO_LARGE"
    with pytest.raises(ProtocolError) as binary_error:
        decode_binary(bytes((1, 2)) + bytes(16) + b"a" * (64 * 1024 + 1))
    assert binary_error.value.code == "FRAME_TOO_LARGE"


def _fs_content_frame(content: str) -> str:
    """A filesystem.content response of the given content size, as the daemon
    sends it (protocol v1.3)."""
    return json.dumps(
        {
            "version": 1,
            "type": "filesystem.content",
            "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
            "node_id": "11111111-1111-4111-8111-111111111111",
            "timestamp": "2026-07-25T00:00:00Z",
            "success": True,
            "payload": {
                "success": True,
                "rel_path": "src/large.ts",
                "size": len(content),
                "modified_at": "2026-07-25T00:00:00Z",
                "encoding": "utf-8",
                "language_hint": "typescript",
                "content": content,
            },
        }
    )


def test_two_mib_preview_frame_is_accepted() -> None:
    """A ≤2 MiB preview (FR-FILE-003) exceeds the 64 KiB control bound by design
    and must decode via MAX_FILE_PAYLOAD — otherwise the response is dropped and
    the read times out instead of answering."""
    content = "const answer = 42;\n" * ((2 * 1024 * 1024) // 19)
    frame = _fs_content_frame(content)
    assert len(frame.encode()) > MAX_PAYLOAD
    message = decode_control(frame)
    assert message.type == "filesystem.content"
    assert message.payload["content"] == content


def test_large_directory_listing_frame_is_accepted() -> None:
    entries = [
        {
            "name": f"file_{i:05d}.py",
            "rel_path": f"src/file_{i:05d}.py",
            "type": "file",
            "size": 2048,
            "modified_at": "2026-07-25T00:00:00Z",
            "hidden": False,
            "symlink": False,
            "excluded": False,
            "expandable": False,
        }
        for i in range(2000)
    ]
    frame = json.dumps(
        {
            "version": 1,
            "type": "filesystem.entries",
            "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
            "node_id": "11111111-1111-4111-8111-111111111111",
            "timestamp": "2026-07-25T00:00:00Z",
            "success": True,
            "payload": {
                "path": "src",
                "entries": entries,
                "truncated": True,
                "next_cursor": "2000",
            },
        }
    )
    assert len(frame.encode()) > MAX_PAYLOAD
    assert len(decode_control(frame).payload["entries"]) == 2000


def test_large_bound_applies_only_to_filesystem_responses() -> None:
    """Every other control type keeps the tight 64 KiB bound, so the larger
    filesystem ceiling cannot be used to smuggle an oversize session frame."""
    oversize_session = json.dumps(
        {
            "version": 1,
            "type": "session.started",
            "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
            "node_id": "11111111-1111-4111-8111-111111111111",
            "timestamp": "2026-07-25T00:00:00Z",
            "success": True,
            "payload": {
                "session_id": "22222222-2222-4222-8222-222222222222",
                "pad": "a" * MAX_PAYLOAD,
            },
        }
    )
    with pytest.raises(ProtocolError) as error:
        decode_control(oversize_session)
    assert error.value.code == "FRAME_TOO_LARGE"


def test_filesystem_frame_beyond_the_file_bound_is_rejected() -> None:
    with pytest.raises(ProtocolError) as error:
        decode_control(_fs_content_frame("x" * (MAX_FILE_PAYLOAD + 1)))
    assert error.value.code == "FRAME_TOO_LARGE"


def _update_frame(payload: dict) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": "daemon.update",
            "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
            "node_id": "11111111-1111-4111-8111-111111111111",
            "timestamp": "2026-07-25T00:00:00Z",
            "payload": payload,
        }
    )


# The security property of daemon.update is what it *cannot* express. If any of
# these ever decoded, a spoofed control frame could point a node at an artifact
# of the sender's choosing (ADR 0017 / SEC-002).
@pytest.mark.parametrize(
    "extra",
    [
        {"url": "https://evil.example.com/agentd.tar.gz"},
        {"download_url": "http://127.0.0.1:8000/x.tar.gz"},
        {"binary_path": "/tmp/payload"},
        {"filename": "agentd_1.0.0_linux_amd64.tar.gz"},
        {"sha256": "0" * 64},
        {"command": "/bin/sh -c id"},
        {"argv": ["sh", "-c", "id"]},
    ],
    ids=lambda extra: next(iter(extra)),
)
def test_daemon_update_refuses_any_artifact_reference(extra: dict) -> None:
    with pytest.raises(ProtocolError) as error:
        decode_control(_update_frame({"target_version": "1.0.0", **extra}))
    assert error.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "version",
    ["latest", "", "1.0", "../../etc/passwd", "1.0.0/../../x", "v1.0.0", "1.0.0 ", "a" * 65],
    ids=repr,
)
def test_daemon_update_target_version_must_be_semver(version: str) -> None:
    with pytest.raises(ProtocolError) as error:
        decode_control(_update_frame({"target_version": version}))
    assert error.value.code == "INVALID_MESSAGE"


def test_daemon_update_frames_keep_the_tight_control_bound() -> None:
    """The 8 MiB ceiling from 1.3.1 is limited to filesystem responses; an
    oversize update frame must not slip through it."""
    with pytest.raises(ProtocolError) as error:
        decode_control(_update_frame({"target_version": "1.0.0", "pad": "a" * MAX_PAYLOAD}))
    assert error.value.code == "FRAME_TOO_LARGE"


# --- read-only binary preview, contract 1.11.0 (ADR 0029) ---

PREVIEW_ID = "01K6B9R3V1EW7Q2M8N4X6Y0Z5T"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


def _preview_frame(msg_type: str, payload: dict, *, success: bool | None = None) -> str:
    frame: dict = {
        "version": 1,
        "type": msg_type,
        "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
        "node_id": "11111111-1111-4111-8111-111111111111",
        "timestamp": "2026-09-27T00:00:00Z",
        "payload": payload,
    }
    if success is not None:
        frame["success"] = success
    return json.dumps(frame)


def test_preview_data_is_the_only_preview_type_allowed_the_large_bound() -> None:
    """Only the response that carries bytes gets the 8 MiB ceiling. The requests
    and the small responses keep 64 KiB, so the preview family cannot be used to
    smuggle an oversize control frame in either direction."""
    assert "filesystem.preview_data" in LARGE_FRAME_TYPES
    for small in (
        "filesystem.preview_open",
        "filesystem.preview_opened",
        "filesystem.preview_chunk",
        "filesystem.preview_close",
        "filesystem.preview_closed",
    ):
        assert small not in LARGE_FRAME_TYPES, small


@pytest.mark.parametrize(
    ("msg_type", "payload"),
    [
        ("filesystem.preview_open", {"session_id": SESSION_ID, "path": "a" * 4000}),
        ("filesystem.preview_chunk", {"session_id": SESSION_ID, "preview_id": PREVIEW_ID}),
    ],
)
def test_preview_requests_keep_the_tight_control_bound(msg_type: str, payload: dict) -> None:
    padded = {**payload, "pad": "a" * MAX_PAYLOAD}
    with pytest.raises(ProtocolError) as error:
        decode_control(_preview_frame(msg_type, padded))
    assert error.value.code == "FRAME_TOO_LARGE"


def test_a_full_preview_chunk_decodes_under_the_file_bound() -> None:
    """512 KiB raw is 699052 base64 characters. The frame is ten times the 64 KiB
    control bound and must still decode, or every full chunk would be dropped and
    the stream would time out instead of answering."""
    data = base64.b64encode(bytes(512 * 1024)).decode()
    assert len(data) == 699052
    frame = _preview_frame(
        "filesystem.preview_data",
        {"preview_id": PREVIEW_ID, "index": 31, "data": data},
        success=True,
    )
    assert MAX_PAYLOAD < len(frame.encode()) < MAX_FILE_PAYLOAD
    assert decode_control(frame).payload["data"] == data


def test_preview_data_frame_must_claim_success() -> None:
    frame = _preview_frame(
        "filesystem.preview_data", {"preview_id": PREVIEW_ID, "index": 0, "data": "QUJD"}
    )
    with pytest.raises(ProtocolError) as error:
        decode_control(frame)
    assert error.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "extra",
    [{"mime": "image/png"}, {"raw": True}, {"offset": 0}, {"range": "0-1"}, {"password": "x"}],
    ids=lambda extra: next(iter(extra)),
)
def test_preview_open_cannot_claim_anything(extra: dict) -> None:
    payload = {"session_id": SESSION_ID, "path": "docs/a.png", **extra}
    with pytest.raises(ProtocolError) as error:
        decode_control(_preview_frame("filesystem.preview_open", payload))
    assert error.value.code == "INVALID_MESSAGE"


def test_binary_preview_false_is_invalid_so_a_disabled_daemon_must_omit_it() -> None:
    """ADR 0029 §9: `false` is not a way to say "disabled"; omission is. The schema
    is `const: true`, so a daemon bug that emits `false` fails here instead of on
    the day Central is rolled back."""
    raw = (FIXTURES / "valid/node-register.json").read_text()
    frame = json.loads(raw)
    frame["payload"]["binary_preview"] = False
    with pytest.raises(ProtocolError):
        decode_control(json.dumps(frame))
    frame["payload"]["binary_preview"] = True
    assert decode_control(json.dumps(frame)).payload["binary_preview"] is True
