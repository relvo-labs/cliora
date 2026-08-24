"""Four orthogonal state faces, projected from the columns that already exist (P1).

A single ``tasks.stage`` was carrying four different questions at once: how far the work
has got, whether the card is executable, what the agent is doing, and whether a person
still owes a decision. Answering them with one enum is why the board grew a ``blocked``
lane that means "something is in the way" *and* loses the card's real position.

**Nothing here is a new column.** ``0043`` adds ``is_blocked`` and three neighbours, but
the lifecycle, readiness, execution and human-decision faces are all derived — from
``stage``, from ``tasks.readiness`` against the effective process, from
``task_runs.status`` and from ``tasks.gates``. A stored projection would be a second
answer that goes stale, which is the same argument ADR 0029 §1 makes about runner
liveness.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.repositories.tasks import ActiveRunProjection

# --- A. work lifecycle ------------------------------------------------------------

BACKLOG = "backlog"
READY = "ready"
IN_PROGRESS = "in_progress"
REVIEW = "review"
DONE = "done"

LIFECYCLE_ORDER = (BACKLOG, READY, IN_PROGRESS, REVIEW, DONE)

# `blocked` projects onto `ready` and **not onto a lifecycle value of its own**: being
# blocked is the `is_blocked` face, and a card that is blocked is still somewhere in the
# work. Losing that was the defect — the V1 board could not say whether a blocked card
# had been started (plan/26/03 §1.A, D49).
_LIFECYCLE_FOR_STAGE: Mapping[str, str] = {
    "backlog": BACKLOG,
    "blocked": READY,
    "ready": READY,
    "implementing": IN_PROGRESS,
    "verify": REVIEW,
    "done": DONE,
}


def project_lifecycle(stage: str) -> str:
    """One of five, from ``tasks.stage``'s six. Unknown values fall to ``backlog``.

    A fall-through rather than a raise: this runs inside a board query, and a card with
    a stage nobody recognises should show up somewhere a person can see and fix it,
    not take the whole board down.
    """
    return _LIFECYCLE_FOR_STAGE.get(stage, BACKLOG)


def project_is_blocked(stage: str, stored: bool | None) -> bool:
    """The blocked face, with the two rules D102 makes unconditional.

    ``stage='blocked'`` is **always** blocked even when the column says otherwise, and
    ``stage='done'`` is **never** blocked. Both exist because the platform still writes
    the legacy stage from three places nobody is about to change in this phase —
    ``run_reaper.py`` twice (lease expiry, retries exhausted) and ``runs.py`` once (a
    question unanswered for 24 hours). Until `beta.2`'s `HD-06` moves those three, the
    column and the stage can disagree, and the stage is the one that was written by the
    thing that actually knows.

    ``stored`` is ``None`` before migration ``0043``: wave 0 runs on the existing
    backend, so the whole answer comes from the stage there (plan/26/05 §9 rule 2).
    """
    if stage == "blocked":
        return True
    if stage == "done":
        return False
    return bool(stored)


# --- B. readiness -----------------------------------------------------------------

DRAFT = "draft"
NEEDS_CLARIFICATION = "needs_clarification"
READINESS_READY = "ready"


def missing_readiness(
    readiness: Mapping[str, Any] | None, readiness_keys: Sequence[str]
) -> tuple[str, ...]:
    """Which of *this project's* readiness items are still unticked.

    ``readiness_keys`` comes from ``EffectiveProcess`` and is **per project** — a
    project may switch items off (``process.py``'s ``readiness_disabled``). So the
    caller resolves the process **once per project**, never once per card: at 200 cards
    the naive version is 200 process reads plus 200 integration lookups.
    """
    values = readiness or {}
    return tuple(key for key in readiness_keys if not values.get(key))


def project_readiness(missing: Sequence[str], total: int) -> str:
    """``draft`` → ``needs_clarification`` → ``ready``.

    ``total == 0`` (every item disabled for this project) is ``ready``: there is nothing
    left to state, and calling that "draft" would mark every card in such a project.
    """
    if not missing:
        return READINESS_READY
    if total and len(missing) >= total:
        return DRAFT
    return NEEDS_CLARIFICATION


# --- C. execution -----------------------------------------------------------------

NOT_QUEUED = "not_queued"


def project_execution(active_run: ActiveRunProjection | None, latest_run_status: str | None) -> str:
    """``task_runs.status`` verbatim, or ``not_queued``.

    Two inputs because "active" and "latest" are different questions: a card whose last
    run failed has no active run, and reporting ``not_queued`` there would hide the
    failure behind a word that means "nothing has happened". The active run wins when
    there is one — it is the run a person can still act on.
    """
    if active_run is not None:
        return active_run.status
    return latest_run_status or NOT_QUEUED


# --- D. human decision ------------------------------------------------------------

NOT_REQUIRED = "not_required"
PENDING = "pending"
APPROVED = "approved"

# ⚠️ The plan (plan/26/03 §1.D, from research/03/04 §2) lists a fourth value,
# `changes_requested`. **It has no source in this repository and is therefore not
# emitted.** `tasks.gates` stores `{gate_key: {approved_by, approved_at}}` and
# `decide_gate(approve=False)` *removes* the key, so "a reviewer asked for changes" and
# "nobody has looked yet" are the same row. Emitting a value the data cannot distinguish
# would be `plan/25` §2.12's `CROSS_PROJECT_DENIED` again: a name in a document that no
# code can produce. Recorded in plan/26/12 §2.
HUMAN_DECISIONS = (NOT_REQUIRED, PENDING, APPROVED)

# --- the closed value sets the filter allowlist checks against --------------------

READINESS_STATES = (DRAFT, NEEDS_CLARIFICATION, READINESS_READY)

# `task_runs.status`'s eight values plus `not_queued`. Restated here rather than imported
# from the run service: this is the read model's vocabulary, and the day the run state
# machine grows a ninth status the filter allowlist should be a deliberate edit rather
# than a silent widening.
EXECUTION_STATUSES = (
    NOT_QUEUED,
    "queued",
    "claimed",
    "running",
    "waiting_for_input",
    "succeeded",
    "failed",
    "cancelled",
    "lost",
)

# The value set of `tasks.blocking_reason`. **This is where it is enforced**, because the
# column has no CHECK constraint on purpose: two of these can only be produced by the
# runtime phase of `derive_attention`, and a CHECK would turn "what we derived at the
# time" into "an authoritative classification" (ADR 0042, migration `0043`'s docstring).
BLOCKING_REASONS = (
    "dependency",
    "human_input",
    "no_eligible_runner",
    "assigned_runner_offline",
    "verification_failed",
    "gate_unmet",
    "unknown",
)


def project_human_decision(
    gates: Mapping[str, Any] | None, *, required_gate_keys: Sequence[str]
) -> str:
    """Whether a person still owes this card a formal decision.

    ``required_gate_keys`` is the **enabled** subset from ``EffectiveProcess``: a gate
    the deployment cannot satisfy (no tunnel integration) or the project switched off is
    not pending, it is absent. Counting it would make every card in such a project wait
    forever on a gate no screen offers.
    """
    if not required_gate_keys:
        return NOT_REQUIRED
    approved = gates or {}
    return APPROVED if all(approved.get(key) for key in required_gate_keys) else PENDING


# --- the row the read model works on ----------------------------------------------

# How long a card in flight may sit untouched before it counts as stale (attention 8).
#
# **A first guess, not a measurement.** Seven days is one working week: a card that has
# been in `ready`, `in_progress` or `review` across a whole week without anybody
# touching it has stopped being work in progress and started being a queue. It is
# deliberately a module constant rather than a process setting — a per-project knob
# would need a migration, a UI and a default, and the default is the only part anybody
# would use. Listed in plan/26/11 as an open measurement.
STALE_AFTER = timedelta(days=7)

# Staleness is only meaningful where somebody is supposed to be moving the card.
# `backlog` is a queue by definition and `done` is finished; flagging either would put a
# warning on most of the board and train people to ignore the warning.
_STALE_LIFECYCLES = frozenset({READY, IN_PROGRESS, REVIEW})


def is_stale(lifecycle: str, updated_at: datetime | None, *, now: datetime) -> bool:
    if lifecycle not in _STALE_LIFECYCLES or updated_at is None:
        return False
    return updated_at < now - STALE_AFTER


@dataclass(frozen=True, slots=True)
class WorkRow:
    """One card as the read model sees it, before attention.

    Deliberately **not** ``BoardCard``: that type is pinned at 89,251 bytes for 200 cards
    (``repositories/tasks.py``) and shares a query with the V1 board. Widening it is how
    that pin gets undone. This one has its own budget (D94) and its own query.

    ``over_wip`` and ``stale`` are computed where the row is built rather than inside
    :func:`~app.services.work.attention.derive_attention`, because both need facts a
    single row does not hold — the size of the card's group, and the clock.
    :func:`derive_attention` stays pure so that it can be measured (plan/26/03 §5) and so
    that the same function serves the SQL path and a test with no database.
    """

    # identity
    task_id: uuid.UUID
    project_id: uuid.UUID
    card_ref: str
    title: str
    card_kind: str
    # lifecycle. `stage` travels beside `lifecycle` under the name `legacy_stage` on the
    # wire: "what does this card look like on the old board" stays answerable, which is
    # what makes the projection reversible while the three legacy writers still exist.
    stage: str
    lifecycle: str
    is_blocked: bool
    readiness: str
    readiness_missing: tuple[str, ...]
    # blocking
    blocking_reason: str | None
    blocking_message: str | None
    blocking_count: int
    blocking_refs: tuple[str, ...]
    # execution and decision
    execution: str
    human_decision: str
    gates_approved_count: int
    gates_required_count: int
    active_run: ActiveRunProjection | None
    latest_run_status: str | None
    latest_verification_result: str | None
    # ownership
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    risk: str
    priority: str
    delivery: str
    labels: tuple[str, ...]
    # relations
    requirement_id: uuid.UUID | None
    epic_id: uuid.UUID | None
    user_story_id: uuid.UUID | None
    # conversation
    conversation_seq: int
    open_question_count: int
    waiting_for_actor: str | None
    # trend inputs, computed where the row is built
    over_wip: bool
    stale: bool
    # ordering
    rank: str | None
    version: int
    created_at: datetime | None
    updated_at: datetime | None
