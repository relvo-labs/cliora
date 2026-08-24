"""The eight attention levels and the four state faces, without a database (PX-24).

`derive_attention` is the read model's one answer to "how is this card doing", and six
screens render it. What is asserted here is the part that has no query in it: the
priority order, the two-phase split, and the projections that turn six stage values into
four independent questions.

The database-backed half — that phase A's query produces these rows, and that phase B
agrees with the console — is in `tests/db/test_work_attention_api.py`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.clock import now_utc
from app.repositories.tasks import ActiveRunProjection
from app.services.work.attention import (
    ASSIGNED_RUNNER_OFFLINE,
    ATTENTION_ORDER,
    DEPENDENCY_BLOCKED,
    NO_ELIGIBLE_RUNNER,
    OVER_WIP_OR_STALE,
    PENDING_HUMAN_APPROVAL,
    RUN_FAILED,
    RUNTIME_LEVELS,
    VERIFICATION_FAILED,
    WAITING_FOR_YOUR_INPUT,
    RuntimeSignals,
    derive_attention,
)
from app.services.work.projection import (
    APPROVED,
    DRAFT,
    NEEDS_CLARIFICATION,
    NOT_QUEUED,
    NOT_REQUIRED,
    PENDING,
    READINESS_READY,
    STALE_AFTER,
    WorkRow,
    is_stale,
    missing_readiness,
    project_execution,
    project_human_decision,
    project_is_blocked,
    project_lifecycle,
    project_readiness,
)

TASK_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def _row(**overrides: object) -> WorkRow:
    """A card with nothing wrong with it. Each test turns on exactly one thing."""
    base: dict[str, object] = {
        "task_id": TASK_ID,
        "project_id": uuid.uuid4(),
        "card_ref": "TK-1",
        "title": "a card",
        "card_kind": "implementation",
        "stage": "implementing",
        "lifecycle": "in_progress",
        "is_blocked": False,
        "readiness": READINESS_READY,
        "readiness_missing": (),
        "blocking_reason": None,
        "blocking_message": None,
        "blocking_count": 0,
        "blocking_refs": (),
        "execution": "running",
        "human_decision": APPROVED,
        "gates_approved_count": 6,
        "gates_required_count": 6,
        "active_run": None,
        "latest_run_status": "running",
        "latest_verification_result": None,
        "owner_user_id": None,
        "owner_name": None,
        "risk": "medium",
        "priority": "normal",
        "delivery": "none",
        "labels": (),
        "requirement_id": None,
        "epic_id": None,
        "user_story_id": None,
        "conversation_seq": 0,
        "open_question_count": 0,
        "waiting_for_actor": None,
        "over_wip": False,
        "stale": False,
        "rank": "a",
        "version": 1,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    base.update(overrides)
    return WorkRow(**base)  # type: ignore[arg-type]


# --- the order ---------------------------------------------------------------------


def test_the_order_is_the_documented_one_and_has_no_second_definition() -> None:
    """A frozen list, because the frontend renders it rather than rebuilding it.

    Reordering is a product decision (plan/26/03 §2 argues each position); this test is
    what makes it a deliberate one rather than a side effect of editing the module.
    """
    assert ATTENTION_ORDER == (
        "waiting_for_your_input",
        "pending_human_approval",
        "verification_failed",
        "run_failed",
        "no_eligible_runner",
        "assigned_runner_offline",
        "dependency_blocked",
        "over_wip_or_stale",
    )
    assert len(set(ATTENTION_ORDER)) == 8
    assert RUNTIME_LEVELS == {NO_ELIGIBLE_RUNNER, ASSIGNED_RUNNER_OFFLINE}


def test_a_card_with_nothing_wrong_has_no_attention() -> None:
    attention = derive_attention(_row(), RuntimeSignals({}))
    assert attention.primary is None
    assert attention.signals == ()
    assert attention.count == 0


def test_the_primary_is_the_highest_level_present_not_the_first_found() -> None:
    """Four signals at once; the stalled agent wins.

    The row is built so that the *lowest* level (stale) would be discovered first by a
    naive implementation that returned on its first hit in field order.
    """
    attention = derive_attention(
        _row(
            stale=True,
            blocking_count=2,
            latest_run_status="failed",
            open_question_count=1,
            waiting_for_actor="human",
        ),
        RuntimeSignals({}),
    )
    assert attention.primary == WAITING_FOR_YOUR_INPUT
    assert attention.signals == (
        WAITING_FOR_YOUR_INPUT,
        RUN_FAILED,
        DEPENDENCY_BLOCKED,
        OVER_WIP_OR_STALE,
    )
    assert attention.count == 4


# --- one test per level ------------------------------------------------------------


def test_waiting_for_input_reads_the_projection_not_the_run_status() -> None:
    """**Both shapes of waiting, one answer** (ADR 0035 §8).

    An agent can ask a question and keep polling (`waiting_for_input`), or ask and *exit*
    (`succeeded` / `awaiting_input`). `waiting_for_actor` is written from question state
    precisely so the board does not have to know which happened — and the first version of
    this predicate read the run status instead, so a card whose agent asked and then ended
    showed **no attention at all**: the person it was waiting for could not see that it was
    waiting. J4 found it against a real daemon; this test is the cheap half.
    """
    for execution in ("waiting_for_input", "succeeded"):
        assert (
            derive_attention(
                _row(
                    open_question_count=1,
                    waiting_for_actor="human",
                    execution=execution,
                    latest_run_status=execution,
                ),
                RuntimeSignals({}),
            ).primary
            == WAITING_FOR_YOUR_INPUT
        ), execution

    # Either half alone is a different situation: a count with nobody waiting is stale
    # bookkeeping, and "waiting on the agent" is not waiting on a person.
    assert derive_attention(_row(open_question_count=1), RuntimeSignals({})).primary is None
    assert (
        derive_attention(
            _row(open_question_count=1, waiting_for_actor="agent"), RuntimeSignals({})
        ).primary
        is None
    )
    assert derive_attention(_row(waiting_for_actor="human"), RuntimeSignals({})).primary is None


def test_pending_approval_only_fires_in_review() -> None:
    """Every card starts with six unapproved gates.

    Without the lifecycle condition this level would be on the whole board, and a badge
    that is always on is a badge nobody reads.
    """
    unapproved = {"human_decision": PENDING, "gates_approved_count": 0}
    assert derive_attention(_row(**unapproved), RuntimeSignals({})).primary is None
    assert (
        derive_attention(
            _row(lifecycle="review", stage="verify", **unapproved), RuntimeSignals({})
        ).primary
        == PENDING_HUMAN_APPROVAL
    )


@pytest.mark.parametrize("result", ["failed", "partial"])
def test_a_bad_verification_result_outranks_a_failed_run(result: str) -> None:
    """ "Finished and wrong" needs a person; "failed" may only need a retry."""
    attention = derive_attention(
        _row(latest_verification_result=result, latest_run_status="failed"), RuntimeSignals({})
    )
    assert attention.primary == VERIFICATION_FAILED
    assert attention.signals == (VERIFICATION_FAILED, RUN_FAILED)


@pytest.mark.parametrize("result", ["passed", "not_started", None])
def test_a_verification_result_that_is_not_bad_is_not_a_signal(result: str | None) -> None:
    assert (
        derive_attention(_row(latest_verification_result=result), RuntimeSignals({})).signals == ()
    )


def test_dependency_and_staleness_are_the_two_trailing_levels() -> None:
    assert (
        derive_attention(_row(blocking_count=1), RuntimeSignals({})).primary == DEPENDENCY_BLOCKED
    )
    assert derive_attention(_row(stale=True), RuntimeSignals({})).primary == OVER_WIP_OR_STALE
    assert derive_attention(_row(over_wip=True), RuntimeSignals({})).primary == OVER_WIP_OR_STALE


# --- the two-phase split -----------------------------------------------------------


@pytest.mark.parametrize("level", sorted(RUNTIME_LEVELS))
def test_phase_b_levels_come_from_the_snapshot_and_nowhere_else(level: str) -> None:
    assert derive_attention(_row(), RuntimeSignals({TASK_ID: level})).primary == level


def test_without_a_registry_levels_five_and_six_are_absent_not_false() -> None:
    """ "We did not look" and "we looked and there is a runner" are different facts.

    A caller that cannot tell them apart eventually renders the second when it means the
    first — which is why `runtime_available` travels with the answer instead of the
    absence being silent.
    """
    looked = derive_attention(_row(), RuntimeSignals({}))
    did_not_look = derive_attention(_row(), None)
    assert looked.signals == did_not_look.signals == ()
    assert looked.runtime_available is True
    assert did_not_look.runtime_available is False


def test_a_runtime_level_still_loses_to_a_stalled_agent_and_beats_a_blocker() -> None:
    attention = derive_attention(
        _row(
            open_question_count=1,
            waiting_for_actor="human",
            blocking_count=1,
        ),
        RuntimeSignals({TASK_ID: NO_ELIGIBLE_RUNNER}),
    )
    assert attention.signals == (
        WAITING_FOR_YOUR_INPUT,
        NO_ELIGIBLE_RUNNER,
        DEPENDENCY_BLOCKED,
    )


# --- the four state faces ----------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "lifecycle"),
    [
        ("backlog", "backlog"),
        ("blocked", "ready"),
        ("ready", "ready"),
        ("implementing", "in_progress"),
        ("verify", "review"),
        ("done", "done"),
        ("something_nobody_recognises", "backlog"),
    ],
)
def test_six_stages_project_onto_five_lifecycle_values(stage: str, lifecycle: str) -> None:
    """`blocked` is not a lifecycle value.

    Being blocked is its own face, so a blocked card keeps a position in the work rather
    than losing it — the V1 board could not say whether a blocked card had been started.
    """
    assert project_lifecycle(stage) == lifecycle


@pytest.mark.parametrize("stored", [None, False, True])
def test_the_legacy_blocked_stage_always_wins(stored: bool | None) -> None:
    """The platform itself writes `stage='blocked'` from three places (D102).

    `run_reaper.py` twice and `runs.py` once, none of which this phase changes — so the
    column may say False about a card the reaper just blocked.
    """
    assert project_is_blocked("blocked", stored) is True


@pytest.mark.parametrize("stored", [None, False, True])
def test_a_done_card_is_never_blocked(stored: bool | None) -> None:
    assert project_is_blocked("done", stored) is False


def test_the_column_decides_for_every_other_stage() -> None:
    assert project_is_blocked("ready", True) is True
    assert project_is_blocked("ready", False) is False
    # Wave 0: the column does not exist yet, so the answer is the stage's alone.
    assert project_is_blocked("ready", None) is False


def test_readiness_is_three_states_over_the_projects_own_item_list() -> None:
    keys = ["problem_stated", "acceptance_criteria", "scope_bounded"]
    assert missing_readiness({}, keys) == tuple(keys)
    assert project_readiness(missing_readiness({}, keys), len(keys)) == DRAFT
    partial = missing_readiness({"problem_stated": True}, keys)
    assert project_readiness(partial, len(keys)) == NEEDS_CLARIFICATION
    everything = dict.fromkeys(keys, True)
    assert project_readiness(missing_readiness(everything, keys), len(keys)) == READINESS_READY


def test_a_project_with_every_readiness_item_disabled_is_ready_not_draft() -> None:
    """Nothing left to state is not the same as nothing stated.

    `process_overrides` can switch every item off; calling the result "draft" would mark
    every card in such a project with a warning it can never clear.
    """
    assert project_readiness(missing_readiness({}, []), 0) == READINESS_READY


def test_execution_prefers_the_active_run_and_falls_back_to_the_last_one() -> None:
    active = ActiveRunProjection(
        task_id=TASK_ID,
        status="waiting_for_input",
        runner_name="runner-03",
        assigned_runner_id=None,
        assigned_runner_node_id=None,
        runtime="claude",
    )
    assert project_execution(active, "waiting_for_input") == "waiting_for_input"
    # No active run, but the last one failed: reporting `not_queued` would hide the
    # failure behind a word that means "nothing has happened".
    assert project_execution(None, "failed") == "failed"
    assert project_execution(None, None) == NOT_QUEUED


def test_human_decision_counts_only_the_gates_this_project_can_satisfy() -> None:
    """A gate the deployment disabled is absent, not pending.

    The `ui` gate needs the tunnel integration; counting it while the integration is off
    would leave every card waiting forever on a gate no screen offers.
    """
    assert project_human_decision({}, required_gate_keys=[]) == NOT_REQUIRED
    assert project_human_decision({}, required_gate_keys=["requirements"]) == PENDING
    approved = {"requirements": {"approved_by": "u", "approved_at": "t"}}
    assert project_human_decision(approved, required_gate_keys=["requirements"]) == APPROVED
    assert project_human_decision(approved, required_gate_keys=["requirements", "ui"]) == PENDING
    # The `ui` gate is off for this project, so the same card is approved.
    assert project_human_decision(approved, required_gate_keys=["requirements"]) == APPROVED


@pytest.mark.parametrize(
    ("lifecycle", "expected"),
    [("backlog", False), ("ready", True), ("in_progress", True), ("review", True), ("done", False)],
)
def test_only_work_in_flight_goes_stale(lifecycle: str, expected: bool) -> None:
    """A backlog is a queue and `done` is finished.

    Flagging either would put a warning on most of the board, and a warning most of the
    board carries is one people learn to scroll past.
    """
    now = now_utc()
    old = now - STALE_AFTER - timedelta(hours=1)
    assert is_stale(lifecycle, old, now=now) is expected
    assert is_stale(lifecycle, now, now=now) is False
