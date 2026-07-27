"""Structured JSON logging with redaction (tech §18.3).

Common fields: timestamp, level, service, request_id, user_id, node_id,
session_id, event, message. Secrets and terminal content must never be logged;
this module redacts known-sensitive keys as a defence-in-depth backstop, but the
primary rule is to not pass them in the first place.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

SERVICE = "central"
_CONTEXT_FIELDS = ("user_id", "node_id", "session_id", "event")
_SENSITIVE = (
    "password",
    "token",
    "secret",
    "authorization",
    "credential",
    "pepper",
    "challenge",
    "private_key",
    "signature",
    # P4-04 additions: header and API-key shaped names that a caller could
    # plausibly pass through as metadata.
    "bearer",
    "cookie",
    "api_key",
    "apikey",
    "passphrase",
)
_REDACTED = "***"
# Attributes present on every LogRecord that are not user-supplied context.
_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime", "taskName"}

# Defence in depth for values whose *key* looks innocent. The primary rule is
# still "do not pass a secret in"; these two shapes are the ones that have
# actually leaked in practice — a JWT (three base64url segments) and an
# enrollment token (its documented `enroll_` prefix).
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_ENROLL_TOKEN = re.compile(r"\benroll_[A-Za-z0-9_-]{6,}\b")

# Audit metadata is bounded so an oversized payload cannot be parked in the
# audit table by accident (ADR 0016). Applied per top-level value after
# redaction; the entry is marked rather than silently shortened.
MAX_METADATA_BYTES = 4 * 1024
TRUNCATED_KEY = "truncated"


def _redact_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE)


def _carries_no_secret(value: Any) -> bool:
    """True for values that cannot themselves be a secret.

    Key-substring matching is deliberately broad, which makes it over-match: a
    flag like `credentials_revoked: True` or a count like `credential_version: 2`
    hits the "credential" marker while carrying nothing sensitive. Redacting those
    turns a readable audit row into `***` and loses the very fact being recorded.
    Booleans, numbers and None are therefore kept; strings, bytes and containers
    are not.
    """
    return value is None or isinstance(value, bool | int | float)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return _ENROLL_TOKEN.sub(_REDACTED, _JWT.sub(_REDACTED, value))
    return value


def _redact_value(value: Any, depth: int = 0) -> Any:
    """Recurse into nested containers. A secret one level down is still a secret;
    the previous shallow pass would have written `{"outer": {"password": "..."}}`
    to the audit table verbatim."""
    if depth > 8:  # pathological nesting: keep the shape, drop the content
        return _REDACTED
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if _redact_key(str(key)) and not _carries_no_secret(item)
                else _redact_value(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(item, depth + 1) for item in value]
    return _mask_value(value)


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with sensitive values replaced, recursively, and oversized
    values truncated (for audit metadata and log extras)."""
    redacted = {
        key: (
            _REDACTED
            if _redact_key(str(key)) and not _carries_no_secret(value)
            else _redact_value(value)
        )
        for key, value in data.items()
    }
    return _bound(redacted)


def _bound(data: dict[str, Any]) -> dict[str, Any]:
    """Truncate over-long values and flag that it happened."""
    result: dict[str, Any] = {}
    truncated = False
    for key, value in data.items():
        if isinstance(value, str) and len(value.encode("utf-8", "replace")) > MAX_METADATA_BYTES:
            result[key] = value[:MAX_METADATA_BYTES] + "…"
            truncated = True
        else:
            result[key] = value
    encoded = len(json.dumps(result, default=str).encode("utf-8", "replace"))
    if encoded > MAX_METADATA_BYTES:
        # Whole-payload overflow (many small values): keep the keys, drop the
        # bodies, so the event is still attributable.
        result = {
            key: (value if isinstance(value, int | float | bool) else _REDACTED)
            for key, value in result.items()
        }
        truncated = True
    if truncated:
        result[TRUNCATED_KEY] = True
    return result


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": SERVICE,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid is not None:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key in _STD_ATTRS or key.startswith("_"):
                continue
            payload[key] = (
                _REDACTED
                if _redact_key(key) and not _carries_no_secret(value)
                else _redact_value(value)
            )
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str = "cliora") -> logging.Logger:
    return logging.getLogger(name)
