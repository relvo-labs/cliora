"""Hermetic unit tests for the session state machine (P2-05, ADR 0013)."""

from __future__ import annotations

from app.services.sessions import (
    DISCONNECTED,
    EXITED,
    FAILED,
    RUNNING,
    STARTING,
    TERMINAL_STATES,
    TERMINATED,
    TERMINATING,
    can_transition,
)


def test_start_to_running_and_failed() -> None:
    assert can_transition(STARTING, RUNNING)
    assert can_transition(STARTING, FAILED)


def test_running_lifecycle() -> None:
    assert can_transition(RUNNING, DISCONNECTED)
    assert can_transition(RUNNING, TERMINATING)
    assert can_transition(RUNNING, EXITED)
    assert can_transition(DISCONNECTED, RUNNING)
    assert can_transition(TERMINATING, TERMINATED)


def test_terminal_states_are_immutable() -> None:
    for terminal in TERMINAL_STATES:
        for target in (RUNNING, STARTING, TERMINATING, DISCONNECTED):
            assert not can_transition(terminal, target)


def test_illegal_shortcuts_rejected() -> None:
    assert not can_transition(STARTING, TERMINATED)  # must pass through terminating/running
    assert not can_transition(RUNNING, TERMINATED)  # terminate goes via TERMINATING
    assert not can_transition(EXITED, TERMINATED)
