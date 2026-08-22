"""The operations a person performs on project memory (`KN-10`, ADR 0038 §2/§7).

Six of them, and what they have in common is more interesting than what separates them:
**every one is a person's action, and none is available to a run credential.** Authority
is written by the ingestion pipeline and by a human, never by a caller claiming it
(ADR 0038 §2), so the run-token surface has no path here at all — which is why
`cliora knowledge` has no `mark-authoritative`, `retract` or `pin`.

There is deliberately **no delete**. `knowledge_enabled=false` already answers "I do not
want this feature", and a destructive endpoint with no user need behind it is a surface
that only ever costs something.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import (
    KnowledgeChunk,
    KnowledgeJob,
    KnowledgeSource,
    Project,
    Task,
    TaskKnowledgePin,
    User,
)
from app.services import audit as audit_actions
from app.services.audit import AuditService
from app.services.knowledge.outbox import KnowledgeOutbox, invalidate_enabled_cache

#: Authority values a person may set by hand. The rest are the pipeline's, and letting a
#: person write `canonical` would make the word mean "somebody said so".
HUMAN_AUTHORITIES = ("authoritative", "retracted", "accepted")


@dataclass(frozen=True, slots=True)
class SourceFamily:
    source_type: str
    sources: int
    chunks: int
    last_ingested_at: datetime | None


@dataclass(frozen=True, slots=True)
class Health:
    families: list[SourceFamily]
    pending_jobs: int
    failed_jobs: int
    dead_jobs: int
    dead_letter_age_seconds: float
    last_error: str | None
    repo_last_synced_at: datetime | None
    repo_commit: str | None


class KnowledgeAdmin:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise ApiError("PROJECT_NOT_FOUND", "Project not found", 404)
        return project

    async def _require_enabled(self, project_id: uuid.UUID) -> Project:
        project = await self._project(project_id)
        if not project.knowledge_enabled:
            raise ApiError("KNOWLEDGE_DISABLED", "Project memory is not enabled", 404)
        return project

    # --- the switch ----------------------------------------------------------

    async def set_enabled(self, actor: User, project_id: uuid.UUID, enabled: bool) -> Project:
        """Turn project memory on or off.

        **Off marks sources inactive and deletes nothing** (ADR 0038 §6). Deleting is a
        separate action with a second confirmation, and this release does not offer one:
        "I do not want this feature" is fully served by the switch.

        Turning it **on** is also the backfill trigger, so there is no backfill script
        anywhere — the reconciler's watermarks find every entity with no source yet.
        """
        project = await self._project(project_id)
        if project.knowledge_enabled == enabled:
            return project
        project.knowledge_enabled = enabled
        if not enabled:
            await self._session.execute(
                sa.update(KnowledgeSource)
                .where(KnowledgeSource.project_id == project_id)
                .values(active=False)
            )
        invalidate_enabled_cache(project_id)
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={"project_id": str(project_id), "knowledge_enabled": enabled},
        )
        return project

    # --- authority -----------------------------------------------------------

    async def set_authority(
        self, actor: User, project_id: uuid.UUID, source_id: uuid.UUID, authority: str
    ) -> KnowledgeSource:
        """Mark a source as a formal decision, or withdraw it.

        The allowlist is short on purpose. A person may say "this is our decision"
        (`authoritative`), "we accepted this" (`accepted`) or "ignore this"
        (`retracted`). They may not say `canonical` or `verified` — those mean *the
        platform observed it*, and a word anyone can assert stops meaning anything.
        """
        if authority not in HUMAN_AUTHORITIES:
            raise ApiError(
                "INVALID_ARGUMENT",
                "That authority level is not one a person sets",
                400,
                details={"allowed": list(HUMAN_AUTHORITIES)},
            )
        await self._require_enabled(project_id)
        source = await self._session.get(KnowledgeSource, source_id)
        if source is None or source.project_id != project_id:
            raise ApiError("SOURCE_NOT_FOUND", "Source not found", 404)
        previous = source.authority
        source.authority = authority
        source.active = authority != "retracted"
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            # Metadata only: the audit log records that a trust level changed and who
            # changed it, never the text whose trust level it was.
            metadata={
                "project_id": str(project_id),
                "source_id": str(source_id),
                "authority_from": previous,
                "authority_to": authority,
            },
        )
        return source

    # --- pins ----------------------------------------------------------------

    async def set_pin(
        self,
        actor: User,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        source_id: uuid.UUID,
        mode: str,
    ) -> TaskKnowledgePin:
        if mode not in ("pin", "exclude"):
            raise ApiError("INVALID_ARGUMENT", "mode must be pin or exclude", 400)
        await self._require_enabled(project_id)
        task = await self._session.get(Task, task_id)
        source = await self._session.get(KnowledgeSource, source_id)
        # Both checks answer 404 rather than 403: a different status for "exists but not
        # yours" is how a caller enumerates another project's ids.
        if task is None or task.project_id != project_id:
            raise ApiError("TASK_NOT_FOUND", "Task not found", 404)
        if source is None or source.project_id != project_id:
            raise ApiError("SOURCE_NOT_FOUND", "Source not found", 404)
        existing = await self._session.get(TaskKnowledgePin, (task_id, source_id))
        if existing is not None:
            existing.mode = mode
            pin = existing
        else:
            pin = TaskKnowledgePin(
                task_id=task_id, source_id=source_id, mode=mode, created_by=actor.id
            )
            self._session.add(pin)
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={
                "project_id": str(project_id),
                "task_id": str(task_id),
                "source_id": str(source_id),
                "pin_mode": mode,
            },
        )
        return pin

    async def clear_pin(
        self, actor: User, project_id: uuid.UUID, task_id: uuid.UUID, source_id: uuid.UUID
    ) -> None:
        await self._require_enabled(project_id)
        await self._session.execute(
            sa.delete(TaskKnowledgePin).where(
                TaskKnowledgePin.task_id == task_id, TaskKnowledgePin.source_id == source_id
            )
        )
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={
                "project_id": str(project_id),
                "task_id": str(task_id),
                "source_id": str(source_id),
                "pin_mode": "cleared",
            },
        )

    # --- resync --------------------------------------------------------------

    async def resync(self, actor: User, project_id: uuid.UUID) -> int:
        """Re-read every entity this project has.

        The same code path as the scheduled reconciler and as the event path, because a
        job is a hint rather than content (ADR 0038 §3.2). "Resync" is therefore not a
        second implementation of ingestion that could disagree with the first — it is
        the first one, asked to run now.
        """
        await self._require_enabled(project_id)
        from app.services.knowledge import sources as handlers

        outbox = KnowledgeOutbox(self._session)
        queued = 0
        for source_type, stale in handlers.WATERMARKS.items():
            for external_id in await stale(self._session, project_id, 500):
                await outbox.enqueue(
                    project_id=project_id, source_type=source_type, external_id=external_id
                )
                queued += 1
        await self._audit.record(
            audit_actions.PROJECT_UPDATE,
            user_id=actor.id,
            metadata={"project_id": str(project_id), "knowledge_resync": queued},
        )
        return queued

    # --- reads ---------------------------------------------------------------

    async def health(self, project_id: uuid.UUID) -> Health:
        await self._require_enabled(project_id)
        families = [
            SourceFamily(
                source_type=row.source_type,
                sources=int(row.sources),
                chunks=int(row.chunks or 0),
                last_ingested_at=row.last_ingested_at,
            )
            for row in (
                await self._session.execute(
                    sa.select(
                        KnowledgeSource.source_type,
                        sa.func.count().label("sources"),
                        sa.func.sum(KnowledgeSource.chunk_count).label("chunks"),
                        sa.func.max(KnowledgeSource.ingested_at).label("last_ingested_at"),
                    )
                    .where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.active.is_(True),
                        KnowledgeSource.deleted_at.is_(None),
                    )
                    .group_by(KnowledgeSource.source_type)
                    .order_by(KnowledgeSource.source_type)
                )
            ).all()
        ]
        # Labelled `jobs`, not `count`: a `Row` already has a `.count` method, so
        # `row.count` would be the bound method rather than the number — and it reads
        # exactly like the value. mypy caught this one; a runtime read would have got a
        # `TypeError` several layers away from the cause.
        counts: dict[str, int] = {
            str(row.state): int(row.jobs)
            for row in (
                await self._session.execute(
                    sa.select(KnowledgeJob.state, sa.func.count().label("jobs"))
                    .where(KnowledgeJob.project_id == project_id)
                    .group_by(KnowledgeJob.state)
                )
            ).all()
        }
        oldest_dead = await self._session.scalar(
            sa.select(sa.func.min(KnowledgeJob.dead_lettered_at)).where(
                KnowledgeJob.project_id == project_id, KnowledgeJob.state == "dead"
            )
        )
        last_error = await self._session.scalar(
            sa.select(KnowledgeJob.last_error)
            .where(KnowledgeJob.project_id == project_id, KnowledgeJob.state == "dead")
            .order_by(KnowledgeJob.dead_lettered_at.desc())
            .limit(1)
        )
        repo = (
            await self._session.execute(
                sa.select(KnowledgeSource.ingested_at, KnowledgeSource.source_version)
                .where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == "repo_doc",
                    KnowledgeSource.active.is_(True),
                )
                .order_by(KnowledgeSource.ingested_at.desc())
                .limit(1)
            )
        ).first()
        return Health(
            families=families,
            pending_jobs=counts.get("pending", 0),
            failed_jobs=counts.get("failed", 0),
            dead_jobs=counts.get("dead", 0),
            dead_letter_age_seconds=(
                0.0 if oldest_dead is None else max(0.0, (now_utc() - oldest_dead).total_seconds())
            ),
            last_error=last_error,
            repo_last_synced_at=repo.ingested_at if repo else None,
            repo_commit=repo.source_version if repo else None,
        )

    async def recent(self, project_id: uuid.UUID, limit: int = 20) -> list[KnowledgeSource]:
        await self._require_enabled(project_id)
        return list(
            (
                await self._session.execute(
                    sa.select(KnowledgeSource)
                    .where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.active.is_(True),
                        KnowledgeSource.deleted_at.is_(None),
                    )
                    .order_by(KnowledgeSource.ingested_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def decisions(self, project_id: uuid.UUID) -> dict[str, list[KnowledgeSource]]:
        """Accepted, superseded and conflicting, in three columns.

        **`conflicting` may well be empty forever**, and that is worth knowing rather
        than hiding: supersede is automatic, so two live sources at accepted-or-above
        under one external id should not happen. The column stays because the day it is
        non-empty is a day somebody needs to see it, and `KN-13` records whether it ever
        was. An always-empty column is a `beta.1` decision, not a bug.
        """
        await self._require_enabled(project_id)
        rows = list(
            (
                await self._session.execute(
                    sa.select(KnowledgeSource)
                    .where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.source_type.in_(("decision", "policy")),
                        KnowledgeSource.deleted_at.is_(None),
                    )
                    .order_by(KnowledgeSource.occurred_at.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        accepted = [row for row in rows if row.authority in ("authoritative", "accepted")]
        superseded = [row for row in rows if row.authority == "superseded"]
        seen: dict[str, KnowledgeSource] = {}
        conflicting: list[KnowledgeSource] = []
        for row in accepted:
            other = seen.get(row.source_external_id)
            if other is not None:
                conflicting.extend([other, row])
            else:
                seen[row.source_external_id] = row
        return {"accepted": accepted, "superseded": superseded, "conflicting": conflicting}

    async def sources(
        self, project_id: uuid.UUID, *, source_type: str | None = None, limit: int = 100
    ) -> list[KnowledgeSource]:
        await self._require_enabled(project_id)
        stmt = (
            sa.select(KnowledgeSource)
            .where(
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.deleted_at.is_(None),
            )
            .order_by(KnowledgeSource.ingested_at.desc())
            .limit(limit)
        )
        if source_type:
            stmt = stmt.where(KnowledgeSource.source_type == source_type)
        return list((await self._session.execute(stmt)).scalars().all())

    async def versions(self, project_id: uuid.UUID, source_id: uuid.UUID) -> list[KnowledgeSource]:
        """Every version of the thing this source is a version of."""
        await self._require_enabled(project_id)
        source = await self._session.get(KnowledgeSource, source_id)
        if source is None or source.project_id != project_id:
            raise ApiError("SOURCE_NOT_FOUND", "Source not found", 404)
        return list(
            (
                await self._session.execute(
                    sa.select(KnowledgeSource)
                    .where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.source_type == source.source_type,
                        KnowledgeSource.source_external_id == source.source_external_id,
                    )
                    .order_by(KnowledgeSource.source_updated_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def source_text(self, project_id: uuid.UUID, source_id: uuid.UUID) -> str:
        await self._require_enabled(project_id)
        source = await self._session.get(KnowledgeSource, source_id)
        if source is None or source.project_id != project_id:
            raise ApiError("SOURCE_NOT_FOUND", "Source not found", 404)
        rows = (
            (
                await self._session.execute(
                    sa.select(KnowledgeChunk.content)
                    .where(KnowledgeChunk.source_id == source_id, KnowledgeChunk.valid_to.is_(None))
                    .order_by(KnowledgeChunk.chunk_key)
                )
            )
            .scalars()
            .all()
        )
        return "\n\n".join(rows)

    async def stale_repo(self, project_id: uuid.UUID) -> bool:
        """Whether the repository has never been synced, or not for a fortnight.

        D77's accepted cost, made visible: a project whose agents never run has no
        repository knowledge, and **a knowledge base that cannot show you it is empty is
        worse than not having one**.
        """
        latest = await self._session.scalar(
            sa.select(sa.func.max(KnowledgeSource.ingested_at)).where(
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.source_type == "repo_doc",
                KnowledgeSource.active.is_(True),
            )
        )
        return latest is None or latest < now_utc() - timedelta(days=14)
