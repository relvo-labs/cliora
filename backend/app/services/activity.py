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

# The closed vocabulary. V2.1 adds task kinds, V2.2 adds run kinds.
ALL_KINDS: frozenset[str] = frozenset(
    {
        PROJECT_CREATED,
        PROJECT_UPDATED,
        WORKSPACE_BOUND,
        WORKSPACE_UNBOUND,
        SESSION_STARTED,
        SESSION_ENDED,
    }
)


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
                kind=kind,
                activity_payload=redact_mapping(body) if body else {},
            )
        )
