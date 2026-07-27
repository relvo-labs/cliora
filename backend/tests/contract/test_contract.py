import json
from pathlib import Path
from uuid import UUID

import pytest

from app.protocol import ProtocolError, decode_binary, decode_control, encode_binary
from app.protocol.codec import MAX_FILE_PAYLOAD, MAX_PAYLOAD

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
