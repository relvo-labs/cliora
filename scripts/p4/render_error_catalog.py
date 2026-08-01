#!/usr/bin/env python3
"""Render `docs/error-catalog.md` from `app/api/error_catalog.py` (P4-07).

Generated rather than hand-written for the same reason `docs/permission-matrix.md` is:
a table of error codes is true the day it is written and quietly false a phase later,
and an error catalogue nobody trusts is worse than none — an operator who finds one
stale row stops believing the rest.

    uv run --project backend python ../scripts/p4/render_error_catalog.py --write
    uv run --project backend python ../scripts/p4/render_error_catalog.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.error_catalog import CATALOG, DAEMON, ErrorEntry  # noqa: E402

TARGET = ROOT / "docs/error-catalog.md"

HEADER = """<!-- GENERATED FILE — do not edit.
     Source: backend/app/api/error_catalog.py
     Regenerate: uv run --project backend python ../scripts/p4/render_error_catalog.py --write
-->

# Error catalog

Every stable error code a client can receive, the safe message it carries, and what to
do about it. The `code` is the contract; the message is wording and may improve.

Two rules this table encodes:

- **Daemon internal errors never reach a client.** A daemon error frame is mapped to a
  code below and answered with *this* message. The daemon's own string — which can
  contain an absolute path, a command line or internal state — goes to the server log
  with the request id (ADR 0014).
- **Retry is only offered where it can work.** Offering it on a permanent failure
  teaches users to ignore it, so `Retryable` is part of the contract rather than a UI
  choice.

`Audited` marks the refusals that also write a security event
(`docs/permission-matrix.md`, ADR 0016). Ordinary read 403s and validation errors are
deliberately not audited: at their volume they would bury the signal.

`Origin` is `daemon` for codes that can arrive from a node — those are also in the
closed enum in `contracts/v1/schemas/control-envelope.schema.json`.

"""

SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Authentication and authorization",
        (
            "UNAUTHENTICATED",
            "INVALID_CREDENTIALS",
            "ACCOUNT_DISABLED",
            "TOKEN_EXPIRED",
            "TOKEN_INVALID",
            "FORBIDDEN",
        ),
    ),
    (
        "Request shape",
        (
            "INVALID_ARGUMENT",
            "INVALID_QUERY",
            "NOT_FOUND",
            "INTERNAL_ERROR",
            "CANCELLED",
        ),
    ),
    ("Enrollment", ("ENROLLMENT_TOKEN_INVALID",)),
    (
        "Port forwarding",
        (
            "SECRET_KEY_MISSING",
            "TUNNEL_INTEGRATION_DISABLED",
            "TUNNEL_NODE_DISABLED",
            "TUNNEL_PROVIDER_NOT_CONFIGURED",
            "TUNNEL_PROVIDER_UNAVAILABLE",
            "TUNNEL_PROVIDER_UNAUTHORIZED",
            "TUNNEL_PROVIDER_UNTRUSTED",
            "TUNNEL_PORT_NOT_ALLOWED",
            "TUNNEL_LIMIT_REACHED",
        ),
    ),
    (
        "Node and relay",
        (
            "NODE_NOT_FOUND",
            "NODE_OFFLINE",
            "NODE_DISABLED",
            "NODE_BUSY",
            "NODE_AUTH_FAILED",
            "REQUEST_TIMEOUT",
            "QUEUE_OVERFLOW",
        ),
    ),
    (
        "Protocol",
        (
            "INVALID_MESSAGE",
            "PROTOCOL_VERSION_UNSUPPORTED",
            "MESSAGE_TYPE_UNSUPPORTED",
            "FRAME_TOO_LARGE",
            "INVALID_SESSION",
        ),
    ),
    (
        "Runtime",
        (
            "RUNTIME_NOT_ALLOWED",
            "RUNTIME_NOT_FOUND",
            "RUNTIME_DISABLED",
            "RUNTIME_NOT_EXECUTABLE",
        ),
    ),
    (
        "Session and terminal",
        (
            "SESSION_NOT_FOUND",
            "SESSION_ALREADY_EXISTS",
            "SESSION_NOT_RUNNING",
            "SESSION_INVALID_STATE",
            "SESSION_LIMIT_REACHED",
            "SESSION_START_FAILED",
            "SHELL_ALREADY_OPEN",
            "INVALID_TERMINAL_SIZE",
            "TERMINAL_ALREADY_CONTROLLED",
        ),
    ),
    (
        "Workspace",
        (
            "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
            "WORKSPACE_NOT_FOUND",
            "WORKSPACE_NOT_DIRECTORY",
            "WORKSPACE_PERMISSION_DENIED",
            "WORKSPACE_INVALID",
        ),
    ),
    (
        "Files",
        (
            "FILE_NOT_FOUND",
            "FILE_INVALID_PATH",
            "FILE_PERMISSION_DENIED",
            "FILE_DENIED",
            "FILE_TOO_LARGE",
            "FILE_BINARY",
        ),
    ),
    (
        "Daemon update",
        (
            "UPDATE_NOT_ALLOWED",
            "UPDATE_DOWNLOAD_FAILED",
            "UPDATE_CHECKSUM_MISMATCH",
            "UPDATE_HEALTHCHECK_FAILED",
            "UPDATE_ROLLED_BACK",
            "UPDATE_IN_PROGRESS",
        ),
    ),
]


def _row(item: ErrorEntry) -> str:
    http = str(item.http_status) if item.http_status else "—"
    return (
        f"| `{item.code}` | {http} | {item.message} | {item.cause} | {item.next_step} "
        f"| {'yes' if item.retryable else 'no'} | {'yes' if item.audited else 'no'} "
        f"| {'daemon' if item.origin == DAEMON else 'central'} |"
    )


def render() -> str:
    parts = [HEADER]
    for title, codes in SECTIONS:
        parts.append(f"## {title}\n")
        parts.append(
            "| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |"
        )
        parts.append("|---|---:|---|---|---|:--:|:--:|:--:|")
        parts.extend(_row(CATALOG[code]) for code in codes)
        parts.append("")
    parts.append(
        "Coverage is asserted by `backend/tests/test_error_catalog.py`: every code "
        "Central raises must appear here, every entry here must be raised by Central or "
        "present in the protocol's error enum, and every code must be listed in exactly "
        "one section above.\n"
    )
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.write:
        TARGET.write_text(rendered, encoding="utf-8")
        print(f"wrote {TARGET.relative_to(ROOT)}")
        return 0
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print("docs/error-catalog.md is stale; re-run with --write")
            return 1
        return 0
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
