"""Bounds, cursor codec and output filtering for the audit query (P4-05).

These are the parts that decide whether `GET /api/audit` stays a *filter* or
becomes an arbitrary query surface over the one append-only table, so they are
tested without a database: the rejections must happen before a statement is ever
built.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.api.errors import ApiError
from app.services.audit import FORBIDDEN_METADATA_KEYS
from app.services.audit_query import (
    AuditQueryService,
    decode_cursor,
    encode_cursor,
    sanitize_metadata,
)
from app.settings import Settings

AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def service() -> AuditQueryService:
    # No session is touched: every case here raises during validation.
    return AuditQueryService(session=None, settings=Settings())  # type: ignore[arg-type]


def rejected_window(start: datetime | None, end: datetime | None) -> ApiError:
    with pytest.raises(ApiError) as caught:
        service()._window(start, end)
    return caught.value


def rejected_limit(limit: int) -> ApiError:
    with pytest.raises(ApiError) as caught:
        service()._limit(limit)
    return caught.value


def rejected_actions(actions: list[str]) -> ApiError:
    with pytest.raises(ApiError) as caught:
        AuditQueryService._actions(actions)
    return caught.value


# --------------------------------------------------------------------------- #
# Time window
# --------------------------------------------------------------------------- #


def test_naive_from_is_refused() -> None:
    """Assuming UTC for a naive instant would shift every boundary by the
    operator's own offset, so the ambiguity is rejected rather than guessed
    (ADR 0009)."""
    error = rejected_window(datetime(2026, 7, 1, 0, 0), AT)
    assert error.code == "INVALID_QUERY"
    assert error.status_code == 422
    assert "timezone" in error.message


def test_naive_to_is_refused() -> None:
    error = rejected_window(AT - timedelta(days=1), datetime(2026, 7, 25, 12, 0))
    assert error.status_code == 422


def test_range_wider_than_the_cap_is_refused() -> None:
    error = rejected_window(AT - timedelta(days=91), AT)
    assert error.status_code == 422
    assert "90 days" in error.message


def test_reversed_range_is_refused() -> None:
    error = rejected_window(AT, AT - timedelta(days=1))
    assert "must not be after" in error.message


def test_omitting_the_range_bounds_it_to_the_cap_rather_than_all_history() -> None:
    """The default must be a window, not the whole table: an unbounded default is
    the same defect as an unbounded explicit range."""
    start, end = service()._window(None, None)
    assert end - start == timedelta(days=Settings().audit_query_max_days)


def test_omitting_only_from_anchors_the_window_to_to() -> None:
    start, end = service()._window(None, AT)
    assert end == AT
    assert end - start == timedelta(days=Settings().audit_query_max_days)


def test_range_exactly_at_the_cap_is_accepted() -> None:
    start, end = service()._window(AT - timedelta(days=90), AT)
    assert (start, end) == (AT - timedelta(days=90), AT)


def test_offset_aware_input_is_normalized_to_utc_not_rejected() -> None:
    """A `+08:00` instant is unambiguous, so it is a legitimate filter value; it is
    converted to UTC because that is the only form the app holds internally."""
    taipei = timezone(timedelta(hours=8))
    start = datetime(2026, 7, 25, 8, 0, tzinfo=taipei)
    resolved_start, _ = service()._window(start, AT)
    assert resolved_start == start
    assert resolved_start.tzinfo is UTC


# --------------------------------------------------------------------------- #
# Limit and action vocabulary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("limit", [0, -1, 201, 10_000])
def test_out_of_range_limit_is_refused(limit: int) -> None:
    assert rejected_limit(limit).status_code == 422


@pytest.mark.parametrize("limit", [1, 50, 200])
def test_in_range_limit_is_accepted(limit: int) -> None:
    assert service()._limit(limit) == limit


def test_absent_limit_uses_the_default_page() -> None:
    assert service()._limit(None) == Settings().audit_page_default


def test_unknown_action_is_refused_rather_than_pattern_matched() -> None:
    """`action=user.` must not become a prefix search. A filter that silently
    widens is how a bounded endpoint turns into an arbitrary one."""
    error = rejected_actions(["user."])
    assert error.status_code == 422
    assert "user." in error.message


def test_a_known_action_survives_and_duplicates_collapse() -> None:
    assert AuditQueryService._actions(["user.login", "user.login"]) == ["user.login"]


def test_one_unknown_action_rejects_the_whole_query() -> None:
    """Dropping the unknown value and answering anyway would return results the
    caller did not ask for, under a filter they think applied."""
    assert rejected_actions(["user.login", "nope.nope"]).status_code == 422


def test_empty_action_list_means_no_filter() -> None:
    assert AuditQueryService._actions([]) is None


# --------------------------------------------------------------------------- #
# Cursor codec
# --------------------------------------------------------------------------- #


def test_cursor_round_trips() -> None:
    entry_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(AT, entry_id)) == (AT, entry_id)


def test_cursor_carries_both_halves_of_the_sort_key() -> None:
    """`created_at` alone is not unique — two rows written in one transaction share
    it — so a timestamp-only cursor would repeat or skip them."""
    decoded = json.loads(base64.urlsafe_b64decode(encode_cursor(AT, uuid.uuid4()) + "=="))
    assert set(decoded) == {"t", "i"}


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!",
        base64.urlsafe_b64encode(b"{}").decode(),
        base64.urlsafe_b64encode(b'{"t":"nonsense","i":"x"}').decode(),
        base64.urlsafe_b64encode(b'{"t":"2026-07-25T12:00:00+00:00","i":"not-a-uuid"}').decode(),
        # Naive instant: would compare against an aware column and fail in the DB.
        base64.urlsafe_b64encode(
            b'{"t":"2026-07-25T12:00:00","i":"%s"}' % uuid.uuid4().hex.encode()
        )
        .decode()
        .rstrip("="),
    ],
)
def test_malformed_cursor_is_a_422_not_a_silent_first_page(cursor: str) -> None:
    """Falling back to page one on a bad cursor would loop a paging client
    forever without ever reporting an error."""
    with pytest.raises(ApiError) as caught:
        decode_cursor(cursor)
    assert caught.value.status_code == 422


# --------------------------------------------------------------------------- #
# Output filtering
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(FORBIDDEN_METADATA_KEYS))
def test_every_forbidden_key_is_stripped_on_the_way_out(key: str) -> None:
    """The write path already minimizes metadata; this is the same rule applied at
    the boundary that publishes it, for rows that predate the rule."""
    assert sanitize_metadata({key: "x", "runtime": "claude"}) == {"runtime": "claude"}


def test_request_id_is_promoted_out_of_metadata() -> None:
    """It is a response field, so leaving it in `metadata` too would show it twice
    in the expanded row."""
    assert sanitize_metadata({"request_id": "abc", "result": "ok"}) == {"result": "ok"}


def test_absent_metadata_becomes_an_empty_object() -> None:
    """`null` would force every consumer to branch before rendering."""
    assert sanitize_metadata(None) == {}
    assert sanitize_metadata({}) == {}


def test_sanitizer_is_case_insensitive() -> None:
    assert sanitize_metadata({"PASSWORD": "x"}) == {}
