"""One handler per source type: read an entity, return its versions (`KN-04`/`KN-05`).

Two rules hold for every handler in this file and neither is negotiable:

* **A handler reads and returns. It never writes.** All writing is `store.py`, so the
  idempotent upsert exists once. Eight handlers each doing their own insert would be
  eight chances to get the concurrency argument wrong.
* **A handler describes the entity as it is now**, not the event that woke it. A job is
  a hint (ADR 0038 §3.2), so a handler that tried to replay history would be answering
  a question nobody asked.

Redaction happens once, in `ingest()`, on the way out of the handler and before
anything is stored. Putting it here rather than in each handler means a new handler
cannot forget it — the same reason the enqueue point is single.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ActivityEvent,
    EvidenceItem,
    FeatureSpec,
    KnowledgeSource,
    Project,
    Requirement,
    Task,
    TaskArtifact,
    TaskDependency,
    TaskMessage,
    VerificationReport,
)
from app.services.knowledge.secrets_filter import redact_for_index
from app.services.knowledge.store import ExtractedSource, KnowledgeStore

#: Conversation kinds worth indexing. `system` is excluded: platform events are already
#: `activity`, and indexing them twice would double every one of them in the results.
_INDEXED_MESSAGE_KINDS = ("comment", "message", "question", "answer", "proposal", "decision")

#: How many of a card's most recent messages one ingest pass covers. A card with ten
#: thousand messages must not load them all; the reconciler picks up whatever a single
#: pass could not reach, because a card that busy will be enqueued again shortly.
_MESSAGE_WINDOW = 200


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    sources: int = 0
    tombstoned: int = 0
    occurred_ats: tuple[datetime, ...] = field(default_factory=tuple)


Handler = Callable[[AsyncSession, uuid.UUID, str], Awaitable[list[ExtractedSource]]]


def _entity_id(external_id: str) -> uuid.UUID | None:
    _, _, raw = external_id.partition(":")
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _fields(*pairs: tuple[str, object]) -> str:
    return "\n\n".join(f"## {label}\n\n{value}" for label, value in pairs if value)


# --- policy -----------------------------------------------------------------


async def _policy(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    project = await session.get(Project, project_id)
    if project is None:
        return []
    body = _fields(
        ("專案說明", project.description),
        (
            "驗證指令（專案層）",
            "\n".join(f"- {item.get('name')}" for item in project.verification_commands or []),
        ),
        (
            "流程調整",
            "\n".join(
                f"- {key}: {value}" for key, value in (project.process_overrides or {}).items()
            ),
        ),
        ("允許的機密名稱", "、".join(project.allowed_secret_names or [])),
    )
    if not body.strip():
        return []
    return [
        ExtractedSource(
            external_id=f"project:{project_id}",
            # A timestamp version, because a project has no counter and its text is not
            # a stable identity. Seconds, not microseconds: two edits inside one second
            # are one version, which is the behaviour anyone would expect from a page
            # somebody is typing on.
            version=project.updated_at.replace(microsecond=0).isoformat(),
            authority="authoritative",
            title=f"{project.name} — 專案規則",
            text=body,
            occurred_at=project.updated_at,
            source_updated_at=project.updated_at,
            uri=f"/projects/{project_id}",
        )
    ]


# --- ticket -----------------------------------------------------------------


async def _ticket(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    task_id = _entity_id(external_id)
    if task_id is None:
        return []
    task = await session.get(Task, task_id)
    if task is None or task.project_id != project_id:
        return []
    criteria = "\n".join(
        f"- [{item.get('result') or '未驗'}] {item.get('text', '')}"
        for item in task.acceptance_criteria or []
    )
    blocking = (
        (
            await session.execute(
                sa.select(Task.card_ref)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    body = _fields(
        ("描述", task.description),
        ("目標", task.objective),
        ("範圍", task.scope),
        ("非目標", task.non_goals),
        ("驗收標準", criteria),
        ("前置任務", "、".join(blocking)),
    )
    return [
        ExtractedSource(
            external_id=f"task:{task.id}",
            # The card's optimistic lock is already a per-card monotonic counter. Reusing
            # it means the identity of a version is a number the product already
            # maintains, rather than a second one that has to agree with it.
            version=f"v{task.version}",
            authority="discussion",
            title=f"{task.card_ref} {task.title}",
            text=body or task.title,
            occurred_at=task.updated_at,
            source_updated_at=task.updated_at,
            uri=f"/projects/{project_id}/tasks/{task.id}",
        )
    ]


# --- conversation -----------------------------------------------------------


async def _conversation(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    task_id = _entity_id(external_id)
    if task_id is None:
        return []
    task = await session.get(Task, task_id)
    if task is None or task.project_id != project_id:
        return []
    messages = (
        (
            await session.execute(
                sa.select(TaskMessage)
                .where(
                    TaskMessage.task_id == task_id,
                    TaskMessage.kind.in_(_INDEXED_MESSAGE_KINDS),
                )
                .order_by(TaskMessage.conversation_seq.desc())
                .limit(_MESSAGE_WINDOW)
            )
        )
        .scalars()
        .all()
    )
    out: list[ExtractedSource] = []
    for message in messages:
        # A message is immutable (`GATE-CV-APPEND-ONLY`), so its own sequence number is
        # its version and its `created_at` is both timestamps. That is not laziness: for
        # an immutable source the two really are the same instant.
        authority = "generated" if message.kind == "proposal" else "discussion"
        if message.kind == "decision":
            authority = "accepted"
        out.append(
            ExtractedSource(
                external_id=f"message:{message.id}",
                version=f"seq:{message.conversation_seq}",
                authority=authority,
                title=f"{task.card_ref} #{message.conversation_seq}",
                text=message.body,
                occurred_at=message.created_at,
                source_updated_at=message.created_at,
                uri=f"/projects/{project_id}/tasks/{task_id}?seq={message.conversation_seq}",
                authored_by_type=message.author_kind,
                authored_by_id=message.author_user_id or message.author_runner_id,
                links=(("references", f"task:{task_id}"),),
            )
        )
    return out


# --- decision ---------------------------------------------------------------


async def _decision(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    kind, _, _ = external_id.partition(":")
    entity_id = _entity_id(external_id)
    if entity_id is None:
        return []
    if kind == "task":
        return await _conversation(session, project_id, external_id)
    requirement = await session.get(Requirement, entity_id)
    if requirement is None or requirement.project_id != project_id:
        return []
    specs = (
        (
            await session.execute(
                sa.select(FeatureSpec)
                .where(FeatureSpec.requirement_id == requirement.id)
                .order_by(FeatureSpec.seq)
            )
        )
        .scalars()
        .all()
    )
    out: list[ExtractedSource] = [
        ExtractedSource(
            external_id=f"requirement:{requirement.id}",
            version=requirement.updated_at.replace(microsecond=0).isoformat(),
            # An approved requirement is a person's decision; an unapproved one is still
            # a discussion. The distinction is the whole point of the authority column,
            # and it is decided here rather than by whoever called the endpoint.
            authority="accepted" if requirement.approved_at else "discussion",
            title=f"{requirement.card_ref} 需求",
            text=requirement.raw_text,
            occurred_at=requirement.updated_at,
            source_updated_at=requirement.updated_at,
            uri=f"/projects/{project_id}/requirements/{requirement.id}",
        )
    ]
    for spec in specs:
        body = _fields(
            ("目標", spec.objective),
            ("範圍", spec.scope),
            ("非目標", spec.non_goals),
            (
                "驗收標準",
                "\n".join(f"- {item.get('text', '')}" for item in spec.acceptance_criteria or []),
            ),
            (
                "未決問題",
                "\n".join(f"- {item.get('text', '')}" for item in spec.open_questions or []),
            ),
        )
        if not body.strip():
            continue
        out.append(
            ExtractedSource(
                external_id=f"spec:{spec.id}",
                version=f"seq:{spec.seq}",
                # **An agent's draft is `generated` however good it is.** Only a human's
                # approval of the requirement raises the pair to `accepted`, and the
                # approval lives on the requirement rather than on the draft.
                authority="accepted"
                if (requirement.approved_at and spec.authored_by_kind == "user")
                else "generated",
                title=f"{requirement.card_ref} 規格 v{spec.seq}",
                text=body,
                occurred_at=spec.created_at,
                source_updated_at=spec.created_at,
                uri=f"/projects/{project_id}/requirements/{requirement.id}",
                authored_by_type=spec.authored_by_kind,
                authored_by_id=spec.authored_by,
                links=(("derived_from", f"requirement:{requirement.id}"),),
            )
        )
    return out


# --- artifact ---------------------------------------------------------------

#: Artifacts whose bytes are worth indexing. Everything else contributes its metadata
#: only — a filename and a size are facts, and a PNG's bytes are not text.
_TEXT_CONTENT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml")


async def _artifact(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    task_id = _entity_id(external_id)
    if task_id is None:
        return []
    artifacts = (
        (
            await session.execute(
                sa.select(TaskArtifact).where(
                    TaskArtifact.task_id == task_id,
                    TaskArtifact.project_id == project_id,
                    TaskArtifact.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    passed_runs = set(
        (
            await session.execute(
                sa.select(VerificationReport.run_id).where(
                    # `passed`, the value `0035`'s CHECK actually admits. The five are
                    # not_started / running / passed / failed / partial.
                    VerificationReport.task_id == task_id,
                    VerificationReport.result == "passed",
                )
            )
        ).scalars()
    )
    out: list[ExtractedSource] = []
    for artifact in artifacts:
        out.append(
            ExtractedSource(
                external_id=f"artifact:{artifact.id}",
                # Content address: an artifact is immutable, so its digest *is* its
                # version, and re-attaching the same bytes is the same source.
                version=f"sha256:{artifact.sha256[:12]}",
                # Attached to a run that passed verification, or merely produced. The
                # condition is evaluated here because the authority column is written by
                # the pipeline and never by a caller (ADR 0038 §2).
                authority="verified" if artifact.run_id in passed_runs else "generated",
                title=artifact.filename,
                text=f"{artifact.filename}（{artifact.content_type}, {artifact.size} bytes）",
                occurred_at=artifact.created_at,
                source_updated_at=artifact.created_at,
                uri=f"/api/artifacts/{artifact.id}",
                links=(("delivers", f"task:{task_id}"),),
            )
        )
    return out


# --- verification -----------------------------------------------------------


async def _verification(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    task_id = _entity_id(external_id)
    if task_id is None:
        return []
    reports = (
        (
            await session.execute(
                sa.select(VerificationReport).where(
                    VerificationReport.task_id == task_id,
                    VerificationReport.project_id == project_id,
                )
            )
        )
        .scalars()
        .all()
    )
    evidence = (
        (
            await session.execute(
                sa.select(EvidenceItem).where(
                    EvidenceItem.task_id == task_id, EvidenceItem.project_id == project_id
                )
            )
        )
        .scalars()
        .all()
    )
    out: list[ExtractedSource] = []
    for report in reports:
        checks = "\n".join(
            f"- {item.get('name')} → exit {item.get('exit_code')}" for item in report.checks or []
        )
        out.append(
            ExtractedSource(
                external_id=f"report:{report.id}",
                version=report.reported_at.replace(microsecond=0).isoformat(),
                authority="verified" if report.source == "machine_verified" else "generated",
                title=f"驗證報告 — {report.result}",
                text=_fields(("結論", report.completion_summary), ("檢查", checks)),
                occurred_at=report.reported_at,
                source_updated_at=report.reported_at,
                uri=f"/projects/{project_id}/tasks/{task_id}",
                links=(("verifies", f"task:{task_id}"),),
            )
        )
    for item in evidence:
        # `EvidenceItem`'s own rule: contradictions are stored, not resolved. Two items
        # disagreeing become two sources, each naming its own provenance, and nothing
        # here picks a winner.
        out.append(
            ExtractedSource(
                external_id=f"evidence:{item.id}",
                version=item.collected_at.replace(microsecond=0).isoformat(),
                authority="verified" if item.source == "machine_verified" else "generated",
                title=f"證據 — {item.kind}",
                text="\n".join(f"{key}: {value}" for key, value in (item.payload or {}).items()),
                occurred_at=item.collected_at,
                source_updated_at=item.collected_at,
                uri=f"/projects/{project_id}/tasks/{task_id}",
                links=(("verifies", f"task:{task_id}"),),
            )
        )
    return out


# --- activity ---------------------------------------------------------------

#: Timeline events worth remembering: approvals and terminal outcomes. Deliberately not
#: every kind — a card being dragged between lanes forty times is noise that would
#: outweigh the decision recorded once.
_INDEXED_ACTIVITY = ("task.gate_approved", "task.forced_done", "run.finished")


async def _activity(session: AsyncSession, project_id: uuid.UUID, external_id: str):
    task_id = _entity_id(external_id)
    if task_id is None:
        return []
    events = (
        (
            await session.execute(
                sa.select(ActivityEvent)
                .where(
                    ActivityEvent.project_id == project_id,
                    ActivityEvent.task_id == task_id,
                    ActivityEvent.kind.in_(_INDEXED_ACTIVITY),
                )
                .order_by(ActivityEvent.occurred_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    out: list[ExtractedSource] = []
    for event in events:
        payload = event.activity_payload or {}
        out.append(
            ExtractedSource(
                external_id=f"activity:{event.id}",
                version=event.occurred_at.replace(microsecond=0).isoformat(),
                # A platform-observed fact. The upstream planning table called this
                # `platform fact`, which is not one of the ten levels; it maps to
                # `verified` rather than adding an eleventh that one source would use
                # and every ranking branch would have to handle.
                authority="verified",
                title=f"{event.kind}",
                text="\n".join(f"{key}: {value}" for key, value in payload.items()) or event.kind,
                occurred_at=event.occurred_at,
                source_updated_at=event.occurred_at,
                uri=f"/projects/{project_id}?activity={event.id}",
                links=(("references", f"task:{task_id}"),),
            )
        )
    return out


_HANDLERS: dict[str, Handler] = {
    "policy": _policy,
    "ticket": _ticket,
    "conversation": _conversation,
    "decision": _decision,
    "artifact": _artifact,
    "verification": _verification,
    "activity": _activity,
}


async def ingest(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    external_id: str,
    payload: dict | None = None,
) -> IngestOutcome:
    """Re-read one entity and write what is true about it now.

    `repo_doc` has no handler here: its content arrives by push from inside a run
    (ADR 0038 §3.4) and is written by `repo.py`, so a job for it would have nothing to
    re-read. Reaching this function with one is a programming error rather than a data
    problem, and the `KeyError` says so.
    """
    handler = _HANDLERS[source_type]
    extracted = await handler(session, project_id, external_id)
    if not extracted:
        return IngestOutcome()
    # Redacted once, here, on the way out of every handler. In the handlers it would be
    # eight chances to forget, and the thing being prevented is storing a secret.
    extracted = await redact_for_index(session, project_id, extracted)
    store = KnowledgeStore(session)
    for item in extracted:
        await store.upsert(project_id=project_id, source_type=source_type, source=item)
    return IngestOutcome(
        sources=len(extracted),
        occurred_ats=tuple(item.occurred_at for item in extracted),
    )


# --- reconciliation watermarks ----------------------------------------------
#
# One query per source type, all of one of two shapes:
#
#   "the entity's own state is newer than the newest source we hold for it"      (A)
#   "the entity has a child row we have never turned into a source"              (B)
#
# The second half of each — the `IS NULL` branch — is what makes this the **backfill**
# path as well as the catch-up path. Switching a project on makes every one of its
# entities look like something the event path missed, so enabling the feature fills the
# index with no separate script (ADR 0038 §7). One filling routine is more correct than
# two that have to agree forever.

Watermark = Callable[[AsyncSession, uuid.UUID, int], Awaitable[list[str]]]


def _stale_entity(entity, source_type: str, prefix: str) -> Watermark:
    """Shape (A): the entity carries its own `updated_at`."""

    async def _query(session: AsyncSession, project_id: uuid.UUID, limit: int) -> list[str]:
        newest = (
            sa.select(
                KnowledgeSource.source_external_id.label("external_id"),
                sa.func.max(KnowledgeSource.source_updated_at).label("seen"),
            )
            .where(
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.source_type == source_type,
            )
            .group_by(KnowledgeSource.source_external_id)
            .subquery()
        )
        external = prefix + sa.cast(entity.id, sa.String)
        rows = (
            (
                await session.execute(
                    sa.select(entity.id)
                    .outerjoin(newest, newest.c.external_id == external)
                    .where(
                        entity.project_id == project_id,
                        sa.or_(newest.c.seen.is_(None), newest.c.seen < entity.updated_at),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [f"{prefix}{value}" for value in rows]

    return _query


def _stale_children(child, source_type: str, child_prefix: str, occurred) -> Watermark:
    """Shape (B): the entity is a card, and what ages is a child row of it.

    A conversation, an artifact, a report and a timeline entry all become one source
    **per child row**, so there is no per-card version to compare — the question is
    whether any child exists that never became a source. The job is still keyed by the
    card, because the handler re-reads the card's children as a set.
    """

    async def _query(session: AsyncSession, project_id: uuid.UUID, limit: int) -> list[str]:
        external = child_prefix + sa.cast(child.id, sa.String)
        rows = (
            (
                await session.execute(
                    # `GROUP BY` rather than `SELECT DISTINCT`: PostgreSQL refuses an
                    # `ORDER BY` expression that is not in a distinct select list, and
                    # the ordering earns its place — a project switched on for the first
                    # time should index its recent conversation before its oldest.
                    sa.select(child.task_id)
                    .outerjoin(
                        KnowledgeSource,
                        sa.and_(
                            KnowledgeSource.project_id == project_id,
                            KnowledgeSource.source_type == source_type,
                            KnowledgeSource.source_external_id == external,
                        ),
                    )
                    .where(
                        child.task_id.in_(sa.select(Task.id).where(Task.project_id == project_id)),
                        KnowledgeSource.id.is_(None),
                    )
                    .group_by(child.task_id)
                    .order_by(sa.func.max(occurred).desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [f"task:{value}" for value in rows if value is not None]

    return _query


async def _stale_policy(session: AsyncSession, project_id: uuid.UUID, limit: int) -> list[str]:
    """The project itself: one row, so the generic shape would be more code than this."""
    project = await session.get(Project, project_id)
    if project is None:
        return []
    seen = await session.scalar(
        sa.select(sa.func.max(KnowledgeSource.source_updated_at)).where(
            KnowledgeSource.project_id == project_id,
            KnowledgeSource.source_type == "policy",
        )
    )
    if seen is not None and seen >= project.updated_at:
        return []
    return [f"project:{project_id}"]


WATERMARKS: dict[str, Watermark] = {
    "policy": _stale_policy,
    "ticket": _stale_entity(Task, "ticket", "task:"),
    "decision": _stale_entity(Requirement, "decision", "requirement:"),
    "conversation": _stale_children(
        TaskMessage, "conversation", "message:", TaskMessage.created_at
    ),
    "artifact": _stale_children(TaskArtifact, "artifact", "artifact:", TaskArtifact.created_at),
    "verification": _stale_children(
        VerificationReport, "verification", "report:", VerificationReport.reported_at
    ),
}
