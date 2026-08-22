"""Project activity timeline: what happened on a project (FR-PROJECT-004, ADR 0027).

**Not a second audit log.** The two are written together on most operations and
answer different questions, and the difference decides who may read them and who
cleans them up:

* ``audit_logs`` — who did what, fleet-wide. Metadata needs ``audit.view``. It has
  the existing retention.
* ``activity_events`` — what happened on *this* project. Readable by
  ``project.view``, which **all three roles hold**. No retention at all: it is
  product content, not diagnostics, so it lives as long as the project does. That
  is the opposite of the answer ``run_logs`` gets in V2.2, and confusing the two is
  the easiest mistake available in V2 (ADR 0027 sec 7).

Two rules follow from the wider audience, and both are enforced here rather than
left to reviewers:

1. **The audit module's forbidden-key list guards this payload too.** A constraint
   on a wider surface can only be tighter, never looser. Importing the list rather
   than copying it means the two cannot drift.
2. **Actor identity is redacted for callers without** ``audit.view`` — see
   :func:`redact_actors`. This is not a new decision; it is
   ``services/dashboard.py::project_for`` applied to a second timeline.

Every ``kind`` below must have a real write site, for the same reason every audit
action must: a kind nobody writes is a filter that silently returns nothing.
``test_every_activity_kind_has_a_write_site`` fails on one that does not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityEvent
from app.logging import redact_mapping
from app.services.audit import FORBIDDEN_METADATA_KEYS

# --- V2.0: the project layer (ADR 0027) ---
PROJECT_CREATED = "project.created"
# Covers status transitions as well as renames; the payload carries `from`/`to` when
# the status moved. Unlike the audit trail — where `project.archive` is its own
# action because "who archived that project" is asked on its own — a timeline reader
# is scanning one project in order, so a single kind with a readable payload beats
# two kinds they would have to mentally merge.
PROJECT_UPDATED = "project.updated"
WORKSPACE_BOUND = "workspace.bound"
WORKSPACE_UNBOUND = "workspace.unbound"
SESSION_STARTED = "session.started"
SESSION_ENDED = "session.ended"
SESSION_CONTEXT_PROJECTION = "session.context_projection"

# --- V2.1: the task layer (ADR 0028) ---
EPIC_CREATED = "epic.created"
USER_STORY_CREATED = "user_story.created"
TASK_CREATED = "task.created"
# Split from `task.updated` on purpose: a reader scanning a project's history is
# asking "what moved", and a title edit and a lane change are not the same event
# to them even though they are the same request to us.
TASK_UPDATED = "task.updated"
TASK_STAGE_CHANGED = "task.stage_changed"
TASK_GATE_APPROVED = "task.gate_approved"
REQUIREMENT_CREATED = "requirement.created"
REQUIREMENT_SPEC_ADDED = "requirement.spec_added"
REQUIREMENT_APPROVED = "requirement.approved"
PROPOSAL_ACCEPTED = "requirement.proposal_accepted"
# V2.5. Recorded because the *reason* is the only signal that accumulates on this path:
# the next decomposition of the same requirement receives it as a negative example
# (ADR 0034 §6).
PROPOSAL_REJECTED = "requirement.proposal_rejected"
PATCH_PROPOSAL_DECIDED = "document.patch_decided"

# --- V2.2: the agent runner (ADR 0029) ---
# Only kinds with a write site in this phase. `test_every_activity_kind_has_a_write_site`
# fails in both directions, so a kind added ahead of its writer is as loud as a missing
# one — `run.claimed` and `run.finished` arrive with the queue service that emits them.
RUN_DISPATCHED = "run.dispatched"
# Written by the atomic claim and by the finish/lost paths. Both carry
# `actor_kind="agent"` or `"system"` rather than a user: an unattended run has no
# person behind it, and attributing one would be a lie the timeline cannot correct.
RUN_CLAIMED = "run.claimed"
RUN_FINISHED = "run.finished"
# A card's conversation is also stored in `task_messages`; this kind is the project
# timeline's view of the same act. The two have different readers, which is why both
# exist (ADR 0029). System events are **not** posted here — they already are activity.
TASK_MESSAGE_POSTED = "task.message_posted"
ARTIFACT_ATTACHED = "artifact.attached"
# V2.4. `task.forced_done` is a **second** row beside the stage change, not a variant of
# it: the stage change says the card moved, this says the completion criteria were
# skipped and why — and it is what the third cross-project metric counts (ADR 0033 §5).
# `verification.source_ignored` records that a submitted report claimed a credibility
# level the server discarded; without it, an agent overstating its evidence and an agent
# with a typo leave identical traces.
TASK_FORCED_DONE = "task.forced_done"
# V2.4. `verification.source_ignored` records that a submitted report claimed a
# credibility level the server discarded; without it, an agent overstating its evidence
# and an agent with a typo leave identical traces (ADR 0033 §3b).
VERIFICATION_SOURCE_IGNORED = "verification.source_ignored"
EXECUTION_PLAN_RECORDED = "task.plan_recorded"
VERIFICATION_REPORTED = "task.verification_reported"

# The closed vocabulary. V2.1 adds task kinds, V2.2 adds run kinds.
ALL_KINDS: frozenset[str] = frozenset(
    {
        PROJECT_CREATED,
        PROJECT_UPDATED,
        WORKSPACE_BOUND,
        WORKSPACE_UNBOUND,
        SESSION_STARTED,
        SESSION_ENDED,
        SESSION_CONTEXT_PROJECTION,
        EPIC_CREATED,
        USER_STORY_CREATED,
        TASK_CREATED,
        TASK_UPDATED,
        TASK_STAGE_CHANGED,
        TASK_GATE_APPROVED,
        REQUIREMENT_CREATED,
        REQUIREMENT_SPEC_ADDED,
        REQUIREMENT_APPROVED,
        PROPOSAL_ACCEPTED,
        PROPOSAL_REJECTED,
        PATCH_PROPOSAL_DECIDED,
        RUN_DISPATCHED,
        RUN_CLAIMED,
        RUN_FINISHED,
        TASK_MESSAGE_POSTED,
        ARTIFACT_ATTACHED,
        TASK_FORCED_DONE,
        VERIFICATION_SOURCE_IGNORED,
        EXECUTION_PLAN_RECORDED,
        VERIFICATION_REPORTED,
    }
)

# Who did it, as opposed to *whether the reader may see who*. The distinction is the
# reason this field exists: ``actor_user_id IS NULL`` already means "the system", and
# :func:`redact_actors` produces the same NULL for a user event the reader lacks
# ``audit.view`` for. Without a third field an agent's write is indistinguishable from
# both (ADR 0028 sec 3).
ACTOR_USER = "user"
ACTOR_AGENT = "agent"
ACTOR_SYSTEM = "system"
ACTOR_KINDS = frozenset({ACTOR_USER, ACTOR_AGENT, ACTOR_SYSTEM})


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """One timeline row as the API returns it.

    ``actor_name`` is resolved by the repository; ``actor_id`` and ``actor_name`` are
    both cleared together by :func:`redact_actors`, never one without the other.
    """

    id: uuid.UUID
    kind: str
    occurred_at: Any
    payload: dict[str, Any]
    actor_id: uuid.UUID | None
    actor_name: str | None
    session_id: uuid.UUID | None
    # Survives redaction deliberately — see :func:`redact_actors`.
    actor_kind: str = ACTOR_USER


def redact_actors(items: list[ActivityItem], *, can_view_audit: bool) -> list[ActivityItem]:
    """Drop actor identity for viewers without ``audit.view``.

    Without the action a row keeps the kind and the instant but loses who did it —
    the same rule ``services/dashboard.py::project_for`` applies to the dashboard's
    recent activity, and for the same reason: knowing *that* a workspace was unbound
    is operational context, knowing *who* unbound it is the audit trail
    (``FR-AUTH-002``).

    This matters more here than it does there. ``project.view`` is held by **all
    three roles**, so a timeline that carried actor names would hand every Viewer an
    actor feed — reopening, in a place nobody would think to look, the channel P4
    deliberately closed.

    Applied at the boundary rather than in the query, so one caller's permissions can
    never leak into another's response through a cached result.
    """
    if can_view_audit:
        return items
    # ``actor_kind`` is deliberately *not* cleared. "An agent did this" is the nature
    # of the event rather than an actor's identity, and stripping it would collapse
    # three different rows — a system event, an agent's write, and a person's write
    # the reader may not attribute — into one indistinguishable blank.
    return [replace(item, actor_id=None, actor_name=None) for item in items]


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        kind: str,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        actor_kind: str = ACTOR_USER,
        session_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append one timeline row.

        Does **not** commit: an activity row records something that happened, so it
        has to land in the same transaction as the thing it describes. A separate
        commit would let the timeline claim a binding that was rolled back.

        ``actor_user_id`` is ``None`` for system-originated events. That is a
        different thing from an actor the reader may not see, and the UI must show
        them differently — a blank actor on a system event is correct, a blank actor
        on a user action means "you need `audit.view`".
        """
        if actor_kind not in ACTOR_KINDS:
            raise ValueError(f"unknown actor kind: {actor_kind!r}")
        if kind not in ALL_KINDS:
            # A typo would otherwise create a row no filter can ever find.
            raise ValueError(f"unknown activity kind: {kind!r}")

        body: dict[str, Any] = dict(payload or {})
        forbidden = sorted(FORBIDDEN_METADATA_KEYS & body.keys())
        if forbidden:
            # Loud rather than redacted-in-silence: reaching here means a caller
            # tried to put file content, a keyword or a credential on a surface that
            # every role can read, and that is a bug in the caller.
            raise ValueError(f"forbidden keys in activity payload: {forbidden}")

        self._session.add(
            ActivityEvent(
                project_id=project_id,
                task_id=task_id,
                session_id=session_id,
                actor_user_id=actor_user_id,
                actor_kind=actor_kind,
                kind=kind,
                activity_payload=redact_mapping(body) if body else {},
            )
        )
        # V2-K1 (ADR 0038 §3.1): the **only** place project memory is told that
        # something may have changed. Here rather than in the eight services that write
        # ingestable facts, because forgetting one of those eight is silent — that
        # source type just stops updating and looks like a quiet week. Same transaction
        # as the row above, deliberately: a hint that survived a rolled-back fact would
        # make the worker re-read a state that never existed.
        #
        # It never raises (see `KnowledgeOutbox.note`), and the scheduled reconciler is
        # what makes swallowing acceptable: this is the freshness path, that one is the
        # correctness path.
        # Imported here rather than at module scope: `knowledge.outbox` reads this
        # module's kind constants to build its map, so a top-level import would be a
        # cycle. The direction is the right one — knowledge depends on activity, not the
        # other way round — and a function-local import is the cheaper of the two ways
        # to say so (the other being a third module holding the constants, which would
        # separate them from the vocabulary check that gives them meaning).
        from app.services.knowledge.outbox import KnowledgeOutbox

        await KnowledgeOutbox(self._session).note(
            kind, project_id=project_id, task_id=task_id, payload=body
        )
