from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from referencing import Registry, Resource

MAX_PAYLOAD = 64 * 1024
# Filesystem responses (P3) legitimately exceed the 64 KiB control bound: a
# ≤2 MiB preview (FR-FILE-003) plus JSON escaping, or a 2000-entry listing
# (ADR 0015). They get their own, still bounded, ceiling; every other control
# frame keeps the tight 64 KiB limit. Kept well under uvicorn's 16 MiB
# ws_max_size so the socket layer never truncates a legal frame.
MAX_FILE_PAYLOAD = 8 * 1024 * 1024
# Types allowed to use the larger bound. Three are responses (P3); the fourth,
# filesystem.upload, is the first *request* to need it and the first in the
# Central -> daemon direction (ADR 0024 sec 7). Its own schema caps `data` at
# the base64 length of 4 MiB, so the wider frame bound does not widen what a
# node will actually write.
LARGE_FRAME_TYPES = frozenset(
    {
        "filesystem.entries",
        "filesystem.content",
        "filesystem.search_result",
        "filesystem.upload",
    }
)
HEADER_SIZE = 18
ROOT = Path(__file__).parents[3]
SCHEMA_DIR = ROOT / "contracts/v1/schemas"
SCHEMA_PATH = SCHEMA_DIR / "control-envelope.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
# Anchor the in-memory envelope to its file URI so relative $refs
# ("messages/*.schema.json") resolve against the registered resources.
SCHEMA["$id"] = SCHEMA_PATH.as_uri()


def _schema_registry() -> Registry:
    resources = [
        (path.as_uri(), Resource.from_contents(json.loads(path.read_text())))
        for path in SCHEMA_DIR.rglob("*.schema.json")
    ]
    return Registry().with_resources(resources)


VALIDATOR = Draft202012Validator(
    SCHEMA,
    registry=_schema_registry(),
    format_checker=FormatChecker(),
)


class ProtocolError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True, slots=True)
class ControlMessage:
    version: int
    type: str
    request_id: str
    node_id: UUID
    timestamp: str
    payload: dict[str, Any]
    success: bool | None = None
    error: dict[str, Any] | None = None


def decode_control(raw: str | bytes) -> ControlMessage:
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    # Two-stage bound: reject absurd frames before parsing, then hold every
    # non-filesystem type to the tight 64 KiB control limit once the type is known.
    if size > MAX_FILE_PAYLOAD:
        raise ProtocolError("FRAME_TOO_LARGE", "Control frame exceeds the limit")
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("INVALID_MESSAGE", "Control frame is not valid UTF-8 JSON") from exc
    if size > MAX_PAYLOAD and (
        not isinstance(data, dict) or data.get("type") not in LARGE_FRAME_TYPES
    ):
        raise ProtocolError("FRAME_TOO_LARGE", "Control frame exceeds the limit")
    errors = sorted(VALIDATOR.iter_errors(data), key=lambda item: list(item.path))
    if errors:
        raise ProtocolError("INVALID_MESSAGE", "Control frame does not match protocol v1")
    return ControlMessage(
        version=data["version"],
        type=data["type"],
        request_id=data["request_id"],
        node_id=UUID(data["node_id"]),
        timestamp=data["timestamp"],
        payload=data["payload"],
        success=data.get("success"),
        error=data.get("error"),
    )


def encode_binary(kind: Literal[1, 2], session_id: UUID, payload: bytes) -> bytes:
    if not payload:
        raise ProtocolError("INVALID_MESSAGE", "Terminal payload must not be empty")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("FRAME_TOO_LARGE", "Terminal payload exceeds the limit")
    return bytes((1, kind)) + session_id.bytes + payload


def decode_binary(raw: bytes) -> tuple[int, UUID, bytes]:
    if len(raw) <= HEADER_SIZE:
        raise ProtocolError("INVALID_MESSAGE", "Terminal frame is too short")
    version, kind = raw[0], raw[1]
    if version != 1:
        raise ProtocolError("PROTOCOL_VERSION_UNSUPPORTED", "Unsupported binary version")
    if kind not in (1, 2):
        raise ProtocolError("INVALID_MESSAGE", "Unknown terminal frame kind")
    payload = raw[HEADER_SIZE:]
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("FRAME_TOO_LARGE", "Terminal payload exceeds the limit")
    return kind, UUID(bytes=raw[2:18]), payload
