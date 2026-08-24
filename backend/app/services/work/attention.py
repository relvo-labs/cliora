"""What this card needs from a person, in one ordered answer (D92, plan/26/03 §2).

**Eight levels, and two of them are not in the database.** `no_eligible_runner` and
`assigned_runner_offline` are decided by ``NodeConnectionRegistry`` — a dict in this
process — and ``services/runners.py`` refuses to store a copy of it:

> A runner has no online state of its own. … A stored copy would be a second answer
> that can go stale, and this module deliberately does not create one (ADR 0029 §1).

So attention cannot be a column and cannot be a ``WHERE`` clause. It is evaluated in two
phases instead:

* **phase A** — the six levels a row can answer, computed from :class:`WorkRow` fields
  that the read model's query already produces. These are filterable, groupable and
  countable, because they are made of columns.
* **phase B** — :func:`resolve_runtime_signals`, one runner query and one registry
  snapshot for the whole page, evaluated only over the queued set. Its cost is bound to
  the length of the dispatch queue, not to the size of the board.

Two consequences are load-bearing and are written here because they are invisible at the
call site: levels 5 and 6 **cannot be sort keys** (they are not in SQL), and under more
than one worker process they are **per process** (plan/26/11 #2). Central runs a single
uvicorn worker today, which is the only reason the second one is currently harmless.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.db.models import AgentRunner, Task
from app.repositories.tasks import ActiveRunProjection
from app.services.work.projection import PENDING, REVIEW, WorkRow

WAITING_FOR_YOUR_INPUT = "waiting_for_your_input"
PENDING_HUMAN_APPROVAL = "pending_human_approval"
VERIFICATION_FAILED = "verification_failed"
RUN_FAILED = "run_failed"
NO_ELIGIBLE_RUNNER = "no_eligible_runner"
ASSIGNED_RUNNER_OFFLINE = "assigned_runner_offline"
DEPENDENCY_BLOCKED = "dependency_blocked"
OVER_WIP_OR_STALE = "over_wip_or_stale"

# **The one definition of the order.** The frontend renders it and does not rebuild it
# (plan/26/03 §2): a second ordered list is a second product decision, and the two would
# be equal on the day they were written.
#
# The order is by *what a person can do about it now*, not by severity. Level 1 is first
# because it is the only state one sentence clears — and it is burning a lease while it
# waits. Level 8 is last because it is a trend rather than an event.
ATTENTION_ORDER: tuple[str, ...] = (
    WAITING_FOR_YOUR_INPUT,
    PENDING_HUMAN_APPROVAL,
    VERIFICATION_FAILED,
    RUN_FAILED,
    NO_ELIGIBLE_RUNNER,
    ASSIGNED_RUNNER_OFFLINE,
    DEPENDENCY_BLOCKED,
    OVER_WIP_OR_STALE,
)

# The levels phase B owns. Named so that callers can say "this answer is incomplete"
# without hardcoding two strings in three places.
RUNTIME_LEVELS = frozenset({NO_ELIGIBLE_RUNNER, ASSIGNED_RUNNER_OFFLINE})

_ATTENTION_RANK = {name: index for index, name in enumerate(ATTENTION_ORDER)}

# Verification results that mean "there is a conclusion and it is bad". `not_started` is
# a placeholder a run writes before it has anything to say, and `passed` is the point.
_FAILED_VERIFICATION = frozenset({"failed", "partial"})

# `WaitingReason.kind` → attention level. `any` means "a machine could take this, it just
# has not yet", which is not something a person is being asked to fix.
_KIND_TO_LEVEL: Mapping[str, str] = {
    "no_eligible_runner": NO_ELIGIBLE_RUNNER,
    "assigned_offline": ASSIGNED_RUNNER_OFFLINE,
}


@dataclass(frozen=True, slots=True)
class RuntimeSignals:
    """Phase B's answer for one page of cards.

    ``resolved`` holds only the cards phase B looked at — the queued set. A card absent
    from it was not queued, which is a different fact from "queued and a runner exists",
    and the distinction is why this is a mapping rather than a defaultdict.
    """

    resolved: Mapping[uuid.UUID, str]

    def level_for(self, task_id: uuid.UUID) -> str | None:
        return self.resolved.get(task_id)


@dataclass(frozen=True, slots=True)
class AttentionDTO:
    """The primary level, the full set, and whether the set is complete."""

    primary: str | None
    signals: tuple[str, ...]
    runtime_available: bool

    @property
    def count(self) -> int:
        return len(self.signals)


def derive_attention(row: WorkRow, runtime: RuntimeSignals | None) -> AttentionDTO:
    """The single source of truth. Returns primary (highest) and the full signal set.

    ``runtime`` is None when the caller could not consult the node registry — a
    background job, a migration, a test without an app. In that case levels 5 and 6 are
    **absent from the signal set**, not ``False``: "we did not look" and "we looked and
    there is a runner" are different facts, and a caller that cannot tell them apart
    will eventually render the second when it means the first. ``runtime_available``
    carries the distinction to the UI, which shows the two runtime quick filters as
    disabled-with-a-reason rather than returning zero rows (plan/26/06 §2).

    Pure, and deliberately so: it is measured at 200 calls (plan/26/03 §5), and anything
    it had to look up would make that measurement a measurement of the lookup.
    """
    signals: list[str] = []

    # 1. A person is being waited on.
    #
    # **From `waiting_for_actor`, not from the run's status.** There are two shapes of
    # waiting and ADR 0035 §8 keeps both: an agent that asked and is still polling
    # (`waiting_for_input`), and one that asked and *exited* (`succeeded` /
    # `awaiting_input`). `ConversationService._reproject` is the only writer of this
    # column and its docstring says why it exists — "derived from question state rather
    # than from run state, which is what makes the two kinds of waiting produce one answer
    # on the board".
    #
    # The first version of this predicate was `open_question_count > 0 AND execution ==
    # 'waiting_for_input'`, which is what `plan/26/03` §2 specifies. It silently missed the
    # second shape: a card whose agent asked a question and then ended showed **no
    # attention at all**, which is the worst available answer — the person it is waiting
    # for cannot see that it is waiting. Found by J4 against a real daemon; no unit test
    # would have, because a fixture picks one shape.
    if row.open_question_count > 0 and row.waiting_for_actor == "human":
        signals.append(WAITING_FOR_YOUR_INPUT)

    # 2. Only in review. Every card starts with six unapproved gates, so "any gate
    #    unapproved" would mark the whole board and mean nothing; a card reaches review
    #    precisely when it is asking somebody to look.
    if row.lifecycle == REVIEW and row.human_decision == PENDING:
        signals.append(PENDING_HUMAN_APPROVAL)

    # 3. There is a conclusion and it is bad. Ranked above 4 because "finished and
    #    wrong" needs a person; "failed" may only need a retry.
    if row.latest_verification_result in _FAILED_VERIFICATION:
        signals.append(VERIFICATION_FAILED)

    # 4. The newest run failed and nothing newer has superseded it. `latest_run_status`
    #    is the newest run by definition, so "no newer run" needs no second check.
    if row.latest_run_status == "failed":
        signals.append(RUN_FAILED)

    # 5 and 6 — phase B. Absent, not false, when nobody looked.
    if runtime is not None:
        level = runtime.level_for(row.task_id)
        if level is not None:
            signals.append(level)

    # 7. Waiting on another card, which has attention of its own.
    if row.blocking_count > 0:
        signals.append(DEPENDENCY_BLOCKED)

    # 8. A trend, not an event.
    if row.stale or row.over_wip:
        signals.append(OVER_WIP_OR_STALE)

    signals.sort(key=lambda name: _ATTENTION_RANK[name])
    return AttentionDTO(
        primary=signals[0] if signals else None,
        signals=tuple(signals),
        runtime_available=runtime is not None,
    )


def resolve_runtime_signals(
    queued: Sequence[ActiveRunProjection],
    tasks: Mapping[uuid.UUID, Task],
    runners: Iterable[AgentRunner],
    *,
    is_online: Callable[[uuid.UUID], bool],
) -> RuntimeSignals:
    """Levels 5 and 6, for the queued set only.

    One runner query and one registry snapshot for the whole page — the same shape
    ``TaskRepository.waiting_reasons()`` already uses. Per-run resolution
    (``RunService.resolve_waiting_reason``) is the console path and stays as it is; this
    is the board path and it must not be N queries.

    **The two must agree.** They apply the same four predicates in the same order —
    online, runtime compatible, ``tag_match``, ``accepts_secrets`` — and
    ``test_board_and_console_agree_on_every_queued_run`` pins them together on a shared
    fixture. The failure this prevents is the console saying "no machine has `docker`"
    beside a card the board calls "waiting", which is the same class of drift
    ``GATE-SC-TAG-BOTH-QUERIES`` already guards between the SQL and Python tag matchers.

    ``runners`` must be the **enabled** ones; the caller loads them once for the page,
    which is the query this function does not do.
    """
    # Imported here, not at module scope: `services.runs` pulls in dispatch, the secret
    # box and the provider adapters, and this module is imported by the read model on
    # every board request.
    from app.services.runs import accepts_secrets, tag_match

    resolved: dict[uuid.UUID, str] = {}
    if not queued:
        return RuntimeSignals(resolved)
    candidates = list(runners)
    online = {runner.node_id: is_online(runner.node_id) for runner in candidates}
    for run in queued:
        if run.assigned_runner_id is not None:
            # A named machine. Whether anything *else* could take the card is not the
            # question — the card asked for this one.
            # `is_online` directly rather than the snapshot: the snapshot holds the
            # *enabled* runners, and a card may be assigned to one that was since
            # disabled. `resolve_waiting_reason` loads the row by id for the same
            # reason, and a missing row reads as offline in both.
            node_id = run.assigned_runner_node_id
            if node_id is None or not is_online(node_id):
                resolved[run.task_id] = ASSIGNED_RUNNER_OFFLINE
            continue
        task = tasks.get(run.task_id)
        if task is None:  # pragma: no cover - the caller builds both from one query
            continue
        eligible = any(
            online[runner.node_id]
            and (run.runtime is None or run.runtime in (runner.runtimes or []))
            and tag_match(runner, task)
            and accepts_secrets(runner, task)
            for runner in candidates
        )
        if not eligible:
            resolved[run.task_id] = NO_ELIGIBLE_RUNNER
    return RuntimeSignals(resolved)


def level_for_waiting_kind(kind: str) -> str | None:
    """The console's ``WaitingReason.kind`` as an attention level, or None for ``any``.

    Exists so the consistency test compares two attention levels rather than a level
    against a string from another vocabulary — a comparison that would need the mapping
    written a second time inside the test.
    """
    return _KIND_TO_LEVEL.get(kind)
