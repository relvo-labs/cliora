"""The relay budgets PRD FR-CONN-006 and FR-SESSION-005 put a number on.

`test_correlation.py` proves a request that never gets an answer times out and
releases its slot. It says nothing about *how long* it waits, so the criteria that
name a duration had no assertion behind them at all — a budget could drift from
15 s to 15 minutes and every test would stay green.

FR-CONN-006 used to name a "general control command: 10 s" budget that the relay
never had, and a 30 s file read where the code says 15. The PRD now states the
per-operation budgets the implementation actually enforces, and this module is
what holds it to them: the table below is the requirement, transcribed.
"""

from __future__ import annotations

import pytest

from app.settings import Settings


def _defaults() -> Settings:
    return Settings(jwt_secret="a-real-secret", token_pepper="a-real-pepper")


# (setting, seconds, the criterion that names it)
PUBLISHED_BUDGETS = [
    ("file_list_timeout_seconds", 15, "FR-CONN-006.AC-03"),
    ("file_read_timeout_seconds", 15, "FR-CONN-006.AC-04"),
    ("file_search_timeout_seconds", 15, "FR-CONN-006.AC-04"),
    ("session_start_timeout_seconds", 30, "FR-CONN-006.AC-05"),
    ("session_attach_timeout_seconds", 15, "FR-CONN-006.AC-06"),
    ("session_list_timeout_seconds", 15, "FR-CONN-006.AC-06"),
    ("session_stop_timeout_seconds", 20, "FR-CONN-006.AC-07"),
    ("update_request_timeout_seconds", 180, "FR-CONN-006.AC-08"),
    ("tunnel_open_timeout_seconds", 20, "FR-CONN-006.AC-09"),
    ("tunnel_close_timeout_seconds", 10, "FR-CONN-006.AC-10"),
    ("file_upload_timeout_seconds", 20, "FR-CONN-006.AC-11"),
    ("file_download_timeout_seconds", 20, "FR-CONN-006.AC-12"),
]


@pytest.mark.parametrize(
    ("setting", "seconds", "criterion"),
    PUBLISHED_BUDGETS,
    ids=[f"{criterion}:{setting}" for setting, _, criterion in PUBLISHED_BUDGETS],
)
def test_a_published_relay_budget_is_the_number_the_prd_names(
    setting: str, seconds: int, criterion: str
) -> None:
    actual = getattr(_defaults(), setting)
    assert actual == seconds, (
        f"{setting} is {actual}s but {criterion} publishes {seconds}s. "
        "Change one or the other — they may not disagree."
    )


def test_directory_listing_budget_is_the_prd_fifteen_seconds() -> None:
    assert _defaults().file_list_timeout_seconds == 15


def test_session_start_budget_is_the_prd_thirty_seconds() -> None:
    assert _defaults().session_start_timeout_seconds == 30


def test_session_stop_waits_a_bounded_number_of_seconds() -> None:
    """FR-SESSION-005 says the stop path waits before giving up, and FR-CONN-006
    now says how long. Unbounded would hold the request open behind an
    unresponsive daemon; zero would never give the session a chance to exit."""
    stop = _defaults().session_stop_timeout_seconds
    assert stop == 20
    # It also has to leave room for the daemon's own graceful wait, or the relay
    # gives up before the CLI has been given its chance and every stop reads as a
    # timeout rather than as forced.
    assert stop > 5


def test_the_daemon_update_budget_is_far_longer_than_the_others() -> None:
    """FR-CONN-006.AC-08. An update downloads, verifies, swaps and restarts; on a
    shared control budget it would time out on a healthy node."""
    settings = _defaults()
    others = [
        value for name, value, _ in PUBLISHED_BUDGETS if name != "update_request_timeout_seconds"
    ]
    assert settings.update_request_timeout_seconds > max(others) * 2


def test_every_relay_budget_is_published() -> None:
    """A new relay operation must state its budget in the PRD, not inherit one
    silently. This is the check that notices when someone adds a setting and
    forgets the requirement."""
    settings = _defaults()
    declared = {name for name, _, _ in PUBLISHED_BUDGETS}
    # Budgets that are not relay round trips to a daemon.
    not_a_relay_budget = {"db_pool_timeout_seconds", "metrics_gauge_timeout_seconds"}
    found = {
        name
        for name in Settings.model_fields
        if name.endswith("_timeout_seconds") and name not in not_a_relay_budget
    }
    assert found == declared, (
        f"unpublished relay budgets: {sorted(found - declared)}; "
        f"published but gone: {sorted(declared - found)}"
    )
    for name in found:
        assert 0 < getattr(settings, name) <= 600, name
