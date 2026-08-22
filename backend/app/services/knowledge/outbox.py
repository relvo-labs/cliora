"""The one place ingestion work is enqueued (ADR 0038 §3.1, D80).

**Why one place.** The obvious design puts an `enqueue()` call in each service that
writes an ingestable fact — eight of them. That design's failure mode is that
*forgetting one is silent*: that source type simply stops updating, and on screen it is
indistinguishable from a project where nothing has been written lately. There is no
error, no failed test, and no way to notice except by wondering.

`ActivityService.record()` is already called from twenty-seven places, already runs
inside the caller's transaction (its docstring: "Does **not** commit"), and its `kind`
comes from a closed vocabulary. That last property is what makes the coverage
assertable: a test can require that every source type appears in `_INGEST_MAP`, which
is a thing no list of call sites can offer.

**Why the job holds an entity key rather than content.** A row here means *"this entity
may have changed; go and look"*. The worker re-reads the entity's current state. Three
consequences, all of them the point: retries are free, duplicate enqueues collapse, and
the scheduled reconciler and a human's "resync" button run the same code. The bug class
"the payload in the job was stale by the time it ran" does not exist.

**Why there is no cursor.** Tailing `activity_events` in order was the other candidate
and it is unsafe: its `id` is a `uuid4` and its `occurred_at` is the transaction's start
time, so a row that began earlier and committed later is skipped forever. A `BIGSERIAL`
would only move the problem to sequence holes. Claiming with `FOR UPDATE SKIP LOCKED`
needs no order at all.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeJob, Project
from app.logging import get_logger
from app.services import activity as kinds

log = get_logger("cliora.knowledge.outbox")

#: How an activity payload names the entity to re-read. `project` and `task` come from
#: `record()`'s own arguments; `requirement` has to come out of the payload, and the
#: absence of a key means "nothing to enqueue" rather than an error — several activity
#: kinds are recorded for entities this phase does not index.
_EntityKey = Callable[[dict[str, Any], uuid.UUID, uuid.UUID | None], str | None]


def _project(_payload: dict[str, Any], project_id: uuid.UUID, _task: uuid.UUID | None) -> str:
    return f"project:{project_id}"


def _task(
    _payload: dict[str, Any], _project_id: uuid.UUID, task_id: uuid.UUID | None
) -> str | None:
    return f"task:{task_id}" if task_id is not None else None


def _requirement(
    payload: dict[str, Any], _project_id: uuid.UUID, task_id: uuid.UUID | None
) -> str | None:
    value = payload.get("requirement_id") or payload.get("requirement")
    if value:
        return f"requirement:{value}"
    # A specification decision recorded against a card and not a requirement still has
    # something to index — the card's conversation carries it.
    return f"task:{task_id}" if task_id is not None else None


#: activity kind → (source type, how to name the entity).
#:
#: The mapping is by **entity**, not by event: five requirement-shaped events all point
#: at `decision`, because what the worker does with each of them is the same — re-read
#: that requirement's current state.
#:
#: `repo_doc` is deliberately absent. Its trigger is an agent's sync call, not an
#: activity row: a commit is not something Cliora did.
_INGEST_MAP: dict[str, tuple[str, _EntityKey]] = {
    kinds.PROJECT_UPDATED: ("policy", _project),
    kinds.TASK_CREATED: ("ticket", _task),
    kinds.TASK_UPDATED: ("ticket", _task),
    kinds.TASK_STAGE_CHANGED: ("ticket", _task),
    kinds.TASK_MESSAGE_POSTED: ("conversation", _task),
    kinds.PROPOSAL_ACCEPTED: ("decision", _requirement),
    kinds.PROPOSAL_REJECTED: ("decision", _requirement),
    kinds.REQUIREMENT_APPROVED: ("decision", _requirement),
    kinds.REQUIREMENT_SPEC_ADDED: ("decision", _requirement),
    kinds.PATCH_PROPOSAL_DECIDED: ("decision", _requirement),
    kinds.ARTIFACT_ATTACHED: ("artifact", _task),
    kinds.VERIFICATION_REPORTED: ("verification", _task),
    kinds.TASK_GATE_APPROVED: ("activity", _task),
    kinds.TASK_FORCED_DONE: ("activity", _task),
    kinds.RUN_FINISHED: ("activity", _task),
}

#: `record()` is one of the hottest paths in the service layer, and this lookup must not
#: add a query to it. Sixty seconds of staleness is acceptable in both directions and
#: the reasons differ: a project that was just enabled starts ingesting a minute late
#: (and the reconciler would have caught it anyway), and a project that was just
#: disabled may enqueue for another minute — which is harmless, because disabling means
#: `active=false`, not "stop writing immediately" (ADR 0038 §7).
_ENABLED_TTL_SECONDS = 60.0
_enabled_cache: dict[uuid.UUID, tuple[bool, float]] = {}


def invalidate_enabled_cache(project_id: uuid.UUID | None = None) -> None:
    """Drop the cached switch after it is toggled.

    In-process only, so a multi-replica deployment still settles within the TTL. That is
    stated rather than hidden: "why is it still empty after I turned it on" is the first
    support question this feature will generate, and the answer is a number.
    """
    if project_id is None:
        _enabled_cache.clear()
    else:
        _enabled_cache.pop(project_id, None)


class KnowledgeOutbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _enabled(self, project_id: uuid.UUID) -> bool:
        cached = _enabled_cache.get(project_id)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]
        enabled = bool(
            await self._session.scalar(
                sa.select(Project.knowledge_enabled).where(Project.id == project_id)
            )
        )
        _enabled_cache[project_id] = (enabled, now + _ENABLED_TTL_SECONDS)
        return enabled

    async def note(
        self,
        kind: str,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Record that an entity may need re-reading. Never raises into the caller.

        Deliberately swallowing: this runs inside the transaction of whatever just
        happened, and a knowledge hint failing must not roll back a card update. The
        reconciler is the safety net that makes swallowing acceptable — it is the
        *correctness* path, and this is only the freshness one.
        """
        mapped = _INGEST_MAP.get(kind)
        if mapped is None:
            return
        source_type, entity = mapped
        try:
            if not await self._enabled(project_id):
                return
            external_id = entity(payload or {}, project_id, task_id)
            if external_id is None:
                return
            await self.enqueue(
                project_id=project_id, source_type=source_type, external_id=external_id
            )
        except Exception as exc:  # noqa: BLE001 - a hint must never fail the fact
            log.warning(
                "knowledge_outbox_note_failed",
                extra={"event": "knowledge_outbox_note_failed", "error": type(exc).__name__},
            )

    async def enqueue(
        self,
        *,
        project_id: uuid.UUID,
        source_type: str,
        external_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Insert a pending job, or leave the existing one alone.

        The conflict target is the **partial** unique index, so `index_where` is
        required rather than decorative: without it PostgreSQL cannot tell which index
        is meant. Collapsing five edits in one second into one job loses nothing,
        because the worker re-reads the entity rather than replaying the events.
        """
        stmt = pg_insert(KnowledgeJob).values(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type=source_type,
            external_id=external_id[:255],
            payload=payload or {},
            state="pending",
        )
        await self._session.execute(
            stmt.on_conflict_do_nothing(
                index_elements=["project_id", "source_type", "external_id"],
                index_where=sa.text("state = 'pending'"),
            )
        )
