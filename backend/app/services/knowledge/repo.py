"""Repository content, pushed from inside a run (ADR 0038 §3.4, D77).

**Central never fetches a repository.** It has no git client, no outbound connection
outside `services/providers.py` (`SCOPE-013`), and the one existing path to a node's
files resolves through a `terminal_sessions` row and authorises a `User` — a background
worker has neither. So the direction is inverted: the agent, which already has a clean
checkout of exactly the commit in question and already holds a run token, pushes.

The protocol is two calls and is **content-addressed**:

    ① manifest   every candidate path with its sha256 and size
       ←         the subset Central does not already have, plus what it just tombstoned
    ② content    only those paths

An unchanged repository therefore costs one request and zero bytes, which is what makes
syncing on every run affordable rather than something a person has to remember.

**The manifest is full, never incremental**, and that is what makes deletion work:
Central compares it against the previous commit's set and tombstones the paths that are
gone. It is also why a force-push needs no special handling — nothing in the comparison
depends on one commit being an ancestor of another.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import KnowledgeChunk, KnowledgeSource, Project, ProjectRepository
from app.services.knowledge.secrets_filter import is_sensitive_path
from app.services.knowledge.store import ExtractedSource, KnowledgeStore

#: D88's four bounds. The asymmetry between them is deliberate: **one oversized file is
#: skipped, an oversized batch is refused.** A repository with a 5 MB CHANGELOG must not
#: lose its whole memory over one file, while a caller trying to push 200 MB has a
#: configuration problem, and silently truncating that would look like success.
MAX_FILES = 800
MAX_FILE_BYTES = 256 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SYNCS_PER_HOUR = 12


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ManifestResult:
    want: list[str]
    skipped: list[dict[str, str]]
    removed: int
    unchanged: int


def _too_large(limit: str, count: int, ceiling: int) -> ApiError:
    return ApiError(
        "KNOWLEDGE_SYNC_TOO_LARGE",
        "This repository sync is over a limit",
        400,
        details={"limit": limit, "count": count, "ceiling": ceiling},
    )


class RepoSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._store = KnowledgeStore(session)

    async def _repository(
        self, project_id: uuid.UUID, repository_id: uuid.UUID | None
    ) -> ProjectRepository:
        if repository_id is None:
            # The card names none. If the project has **exactly one** registered
            # repository, that is unambiguously the one meant, and resolving it here
            # keeps a platform uuid out of the agent's hands — which is the whole reason
            # `repository_id` is optional on the request. Zero or several is genuinely
            # ambiguous and refuses: guessing which of three repositories a checkout is
            # would attribute documents to the wrong one, silently.
            candidates = (
                (
                    await self._session.execute(
                        sa.select(ProjectRepository).where(
                            ProjectRepository.project_id == project_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(candidates) == 1:
                return candidates[0]
            raise ApiError(
                "SOURCE_NOT_FOUND",
                (
                    "This card names no repository and the project has "
                    f"{len(candidates)}, so there is nothing to sync"
                ),
                404,
            )
        repository = await self._session.get(ProjectRepository, repository_id)
        # 404 rather than 403 on a mismatch, and the reason is the same one the rest of
        # this layer follows: a 403 confirms the id exists somewhere.
        if repository is None or repository.project_id != project_id:
            raise ApiError("SOURCE_NOT_FOUND", "Repository not found", 404)
        return repository

    async def _require_enabled(self, project_id: uuid.UUID) -> None:
        enabled = await self._session.scalar(
            sa.select(Project.knowledge_enabled).where(Project.id == project_id)
        )
        if not enabled:
            raise ApiError("KNOWLEDGE_DISABLED", "Project memory is not enabled", 404)

    async def manifest(
        self,
        *,
        project_id: uuid.UUID,
        repository_id: uuid.UUID | None,
        commit: str,
        entries: list[ManifestEntry],
    ) -> ManifestResult:
        """Decide what Central still needs, and tombstone what has gone.

        Both halves happen here, in call ①, on purpose. Deletion must not wait for call
        ② because that call may be cut short by a byte ceiling — and a repository whose
        deletions only land when the upload happens to fit is one where "I deleted that
        document" is sometimes true.
        """
        await self._require_enabled(project_id)
        repository = await self._repository(project_id, repository_id)
        repository_id = repository.id
        await self._check_rate(project_id)

        if len(entries) > MAX_FILES:
            raise _too_large("files", len(entries), MAX_FILES)

        skipped: list[dict[str, str]] = []
        candidates: dict[str, ManifestEntry] = {}
        for entry in entries:
            if is_sensitive_path(entry.path):
                # Refused before collection rather than redacted after: a file that is
                # never read cannot be partly leaked by a pattern that did not quite
                # match.
                skipped.append({"path": entry.path, "reason": "sensitive"})
                continue
            if entry.size > MAX_FILE_BYTES:
                skipped.append({"path": entry.path, "reason": "too_large"})
                continue
            candidates[entry.path] = entry

        prefix = f"{repository_id}:"
        known = {
            row.source_external_id: row
            for row in (
                await self._session.execute(
                    sa.select(KnowledgeSource).where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.source_type == "repo_doc",
                        KnowledgeSource.source_external_id.startswith(prefix),
                        KnowledgeSource.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        }

        want: list[str] = []
        unchanged = 0
        for path, entry in candidates.items():
            existing = known.get(f"{prefix}{path}")
            # The checksum, not the version: the same content at a new commit is the
            # same content, and re-uploading it would cost bytes to learn nothing.
            if existing is not None and existing.checksum == entry.sha256:
                unchanged += 1
                continue
            want.append(path)

        gone = [
            external_id
            for external_id in known
            if external_id.removeprefix(prefix) not in candidates
        ]
        removed = await self._store.tombstone(
            project_id=project_id, source_type="repo_doc", external_ids=gone
        )
        return ManifestResult(
            want=sorted(want), skipped=skipped, removed=removed, unchanged=unchanged
        )

    async def content(
        self,
        *,
        project_id: uuid.UUID,
        repository_id: uuid.UUID | None,
        commit: str,
        files: list[tuple[str, str]],
    ) -> tuple[int, int]:
        """Store the bodies the manifest asked for."""
        await self._require_enabled(project_id)
        repository = await self._repository(project_id, repository_id)
        repository_id = repository.id

        total = sum(len(text.encode("utf-8")) for _path, text in files)
        if total > MAX_UPLOAD_BYTES:
            raise _too_large("bytes", total, MAX_UPLOAD_BYTES)

        ingested = 0
        now = now_utc()
        for path, text in files:
            if is_sensitive_path(path):
                continue
            if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                continue
            await self._store.upsert(
                project_id=project_id,
                source_type="repo_doc",
                source=ExtractedSource(
                    external_id=f"{repository_id}:{path}",
                    # The commit **is** the version: a document at a commit is immutable,
                    # so the identity of the version needs nothing else.
                    version=commit,
                    authority="canonical",
                    title=path,
                    text=text,
                    # The file's own digest, so the manifest's comparison in call ① is
                    # against the same number the agent computed. Anything else makes
                    # every sync a full upload.
                    checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    occurred_at=now,
                    # There is no per-file timestamp in a checkout worth trusting, so
                    # arrival order decides. Out-of-order delivery of two commits is
                    # handled by this comparison, which is why a later push always wins
                    # regardless of which SHA is "greater" — SHAs have no order.
                    source_updated_at=now,
                    # Deliberately not a clickable link: Cliora has no repository
                    # browser, and a link that pretends to work is worse than text.
                    uri=f"repo://{repository.host}/{repository.path.strip('/')}/{path}@{commit}",
                ),
            )
            ingested += 1
        return ingested, total

    async def _check_rate(self, project_id: uuid.UUID) -> None:
        """At most `MAX_SYNCS_PER_HOUR` manifests per project.

        Counted from the sources themselves rather than from a counter table: a sync
        that changed nothing writes nothing, so this bounds the syncs that *cost*
        something, which is the thing worth bounding.
        """
        since = now_utc() - timedelta(hours=1)
        recent = await self._session.scalar(
            sa.select(sa.func.count(sa.distinct(KnowledgeSource.source_version))).where(
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.source_type == "repo_doc",
                KnowledgeSource.ingested_at > since,
            )
        )
        if (recent or 0) > MAX_SYNCS_PER_HOUR:
            raise ApiError(
                "KNOWLEDGE_SYNC_TOO_LARGE",
                "Too many repository syncs for this project in the last hour",
                429,
                details={"limit": "rate", "count": int(recent or 0), "ceiling": MAX_SYNCS_PER_HOUR},
            )


async def live_repo_paths(
    session: AsyncSession, project_id: uuid.UUID, repository_id: uuid.UUID
) -> list[str]:
    """Every repository path currently in the index. Used by the health panel and tests."""
    prefix = f"{repository_id}:"
    rows = (
        (
            await session.execute(
                sa.select(KnowledgeSource.source_external_id)
                .join(KnowledgeChunk, KnowledgeChunk.source_id == KnowledgeSource.id)
                .where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == "repo_doc",
                    KnowledgeSource.active.is_(True),
                    KnowledgeSource.deleted_at.is_(None),
                    KnowledgeChunk.valid_to.is_(None),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return sorted(row.removeprefix(prefix) for row in rows)
