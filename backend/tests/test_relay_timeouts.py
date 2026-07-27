"""The relay budgets PRD FR-CONN-006 and FR-SESSION-005 put a number on.

`test_correlation.py` proves a request that never gets an answer times out and
releases its slot. It says nothing about *how long* it waits, so the criteria that
name a duration had no assertion behind them at all — a budget could drift from
15 s to 15 minutes and every test would stay green.

Two of the PRD's four control-command figures are pinned here. The other two are
in `docs/traceability/gaps.md` under the rewrite queue rather than asserted against
a number the code does not have: there is no single "general control command"
budget, and the file-read budget is 15 s where the PRD says 30 s. Writing a test
around either would record the implementation as the requirement.
"""

from __future__ import annotations

from app.settings import Settings


def _defaults() -> Settings:
    return Settings(jwt_secret="a-real-secret", token_pepper="a-real-pepper")


def test_directory_listing_budget_is_the_prd_fifteen_seconds() -> None:
    assert _defaults().file_list_timeout_seconds == 15


def test_session_start_budget_is_the_prd_thirty_seconds() -> None:
    assert _defaults().session_start_timeout_seconds == 30


def test_session_stop_waits_a_bounded_number_of_seconds() -> None:
    """FR-SESSION-005 says the stop path waits before giving up. Unbounded would
    hold the request open behind an unresponsive daemon; zero would never give the
    session a chance to exit on its own."""
    stop = _defaults().session_stop_timeout_seconds
    assert 0 < stop <= 60


def test_every_relay_budget_is_positive_and_bounded() -> None:
    """A budget of 0 disables the wait and a very large one is indistinguishable
    from hanging, so both ends are refused for every relay operation."""
    settings = _defaults()
    budgets = {
        name: getattr(settings, name)
        for name in Settings.model_fields
        if name.endswith("_timeout_seconds")
    }
    assert budgets, "no relay budgets found; the naming convention changed"
    for name, value in budgets.items():
        assert 0 < value <= 600, f"{name} = {value}"
