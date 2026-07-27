"""Audit metadata minimization and redaction (P4-04, SEC-006, ADR 0016).

Hermetic: these are properties of `redact_mapping` and of the action vocabulary,
so they need no database. The coverage assertions (one operation, one row, with
`request_id`) are in `tests/db/test_audit_coverage.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.logging import MAX_METADATA_BYTES, TRUNCATED_KEY, redact_mapping
from app.services import audit

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "user_password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
        "credential",
        "credentials",
        "pepper",
        "challenge",
        "private_key",
        "signature",
        "bearer",
        "cookie",
        "api_key",
        "apikey",
        "passphrase",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert redact_mapping({key: "sensitive-value"})[key] == "***"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("credentials_revoked", True),
        ("credential_version", 2),
        ("rotated_to_version", 3),
        ("token_count", 0),
        ("secret_rotations", 1.5),
        ("password_changed", False),
        ("challenge_attempts", None),
    ],
)
def test_flags_and_counts_under_a_sensitive_key_are_not_redacted(key: str, value: object) -> None:
    """Key-substring matching is deliberately broad and therefore over-matches.
    `credentials_revoked: True` is the fact being recorded, not a secret; redacting
    it produced an audit row that said `***` where it should have said what
    happened."""
    assert redact_mapping({key: value})[key] == value


@pytest.mark.parametrize("value", ["s3cret", b"s3cret", {"inner": "s3cret"}, ["s3cret"]])
def test_strings_bytes_and_containers_under_a_sensitive_key_are_still_redacted(
    value: object,
) -> None:
    assert redact_mapping({"credential": value})["credential"] == "***"


def test_redaction_recurses_into_nested_containers() -> None:
    """A secret one level down is still a secret. The pre-P4 pass was shallow, so
    `{"outer": {"password": ...}}` reached the audit table verbatim."""
    result = redact_mapping(
        {
            "outer": {"password": "hunter2", "safe": "ok"},
            "items": [{"token": "abc"}, {"fine": 1}],
            "deep": {"a": {"b": {"c": {"secret": "x"}}}},
        }
    )
    assert result["outer"]["password"] == "***"
    assert result["outer"]["safe"] == "ok"
    assert result["items"][0]["token"] == "***"
    assert result["items"][1]["fine"] == 1
    assert result["deep"]["a"]["b"]["c"]["secret"] == "***"
    assert "hunter2" not in json.dumps(result)
    assert "abc" not in json.dumps(result)


def test_pathological_nesting_is_bounded_not_recursed_forever() -> None:
    payload: dict = {"v": "leaf"}
    for _ in range(40):
        payload = {"v": payload}
    dumped = json.dumps(redact_mapping(payload))
    assert "leaf" not in dumped


def test_jwt_and_enrollment_token_values_are_masked_even_under_an_innocent_key() -> None:
    """Defence in depth: the primary rule is not to pass secrets in, but these two
    shapes are the ones that actually leak, and their key is often something like
    `message` or `detail`."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"
    result = redact_mapping({"detail": f"failed with {jwt}", "note": "use enroll_abc123XYZ now"})
    assert jwt not in json.dumps(result)
    assert "enroll_abc123XYZ" not in json.dumps(result)
    assert "***" in result["detail"]
    assert "***" in result["note"]


def test_oversized_value_is_truncated_and_flagged() -> None:
    result = redact_mapping({"blob": "a" * (MAX_METADATA_BYTES * 2)})
    assert result[TRUNCATED_KEY] is True
    assert len(result["blob"]) <= MAX_METADATA_BYTES + 1


def test_many_small_values_overflowing_the_budget_keep_keys_and_drop_bodies() -> None:
    """Whole-payload overflow must stay attributable: the event and its shape
    survive, the content does not."""
    payload = {f"k{i}": "x" * 200 for i in range(60)}
    result = redact_mapping(payload)
    assert result[TRUNCATED_KEY] is True
    assert len(json.dumps(result).encode()) < MAX_METADATA_BYTES * 2
    assert set(payload) <= set(result)
    assert all(result[key] == "***" for key in payload)


def test_numbers_and_booleans_survive_overflow_so_counts_remain_readable() -> None:
    payload: dict = {f"k{i}": "x" * 200 for i in range(60)}
    payload["entries"] = 42
    payload["partial"] = True
    result = redact_mapping(payload)
    assert result["entries"] == 42
    assert result["partial"] is True


def test_empty_metadata_stays_empty() -> None:
    assert redact_mapping({}) == {}


# --------------------------------------------------------------------------- #
# The action vocabulary
# --------------------------------------------------------------------------- #


def test_every_audit_action_has_a_write_site() -> None:
    """An action nobody writes is a filter that silently returns nothing — the
    audit-side twin of the dead `audit.view` permission. Each constant must be
    referenced from somewhere other than the audit module that defines it."""
    sources = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "backend/app").rglob("*.py")
        if path.name != "audit.py" and "migrations" not in path.parts
    ]
    blob = "\n".join(sources)
    names = {
        action: name
        for name, action in vars(audit).items()
        if isinstance(action, str) and action in audit.ALL_ACTIONS
    }
    unwritten = sorted(
        action for action, name in names.items() if f"audit.{name}" not in blob and name not in blob
    )
    assert unwritten == [], f"audit actions defined but never written: {unwritten}"


def test_all_actions_is_complete() -> None:
    """`ALL_ACTIONS` is the closed vocabulary the query API validates against, so a
    constant missing from it would be unfilterable."""
    declared = {
        value
        for name, value in vars(audit).items()
        if isinstance(value, str) and not name.startswith("_") and "." in value and name.isupper()
    }
    assert declared == set(audit.ALL_ACTIONS)


def test_audit_actions_match_the_frontend_constants() -> None:
    """The audit filter offers exactly this vocabulary (P4-05).

    An action present only on the server is unfilterable in the UI; one present
    only in the browser produces a 422 the moment it is selected. Either way the
    filter lies about what it can find.
    """
    dto = (ROOT / "frontend/src/api/dto.ts").read_text(encoding="utf-8")
    block = re.search(r"export const AUDIT_ACTIONS = \[(.*?)\] as const;", dto, re.S)
    assert block is not None, "AUDIT_ACTIONS is missing from frontend/src/api/dto.ts"
    assert set(re.findall(r'"([^"]+)"', block.group(1))) == set(audit.ALL_ACTIONS)


def test_forbidden_metadata_keys_cover_the_content_bearing_names() -> None:
    for key in ("content", "keyword", "rel_path", "password", "token", "private_key", "bytes"):
        assert key in audit.FORBIDDEN_METADATA_KEYS
