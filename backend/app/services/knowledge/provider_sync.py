"""The polling pass: read a provider, write what changed (`HD-02`/`HD-03`, ADR 0043 §2).

**No second background loop.** This is called from `KnowledgeWorker.reconcile`, inside the
advisory lock that already exists, on the 300-second cadence that already exists. A loop
of its own would need its own lock, its own metric, its own failure handling and its own
way of going wrong — and the reconciler's shape is already the right one: a pass that asks
"what changed since I last looked", is safe to run twice, and is safe to miss.

**Writing goes through the store, like every other handler.** The reads happen here
because the entity is on somebody else's server and a handler cannot fetch it (see
`provider_sources.read_pull_request`), but the upsert is `KnowledgeStore.upsert` and the
redaction is `sources.ingest`'s. This module composes; it does not persist.

Two limits, both from ADR 0043 §6 and both derived rather than counted:

* **≤ 3 reads per repository per round.** The pull-request list, the version list, and at
  most one pull-request detail.
* **≤ 36 rounds per repository per hour**, read off `provider_synced_at` — how often that
  column moved in the last hour *is* how many rounds this repository cost. A counter table
  would be a second answer that can disagree with the first (`knowledge/repo.py:255`).

**Three consecutive failures stop a repository.** Not a tuning choice: a revoked token
otherwise produces an error every five minutes for ever, and on screen "we stopped asking"
is indistinguishable from "nothing has been merged".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.clock import now_utc
from app.db.models import Project, ProjectRepository
from app.logging import get_logger
from app.services import provider_reads
from app.services.knowledge import provider_sources
from app.services.knowledge.store import ExtractedSource, KnowledgeStore
from app.services.secrets import SecretService
from app.settings import Settings

log = get_logger("cliora.knowledge.provider_sync")

#: How far back a round looks when a repository has never been synced. Bounded because
#: the first pass on an old repository would otherwise ingest its entire history in one
#: transaction — and `PAGE_SIZE` already caps the rows, so this only decides how much of
#: that page is considered new.
FIRST_PASS_WINDOW = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    repositories: int = 0
    sources: int = 0
    failures: int = 0
    skipped: int = 0


async def sync_project(
    session: AsyncSession, *, project_id: uuid.UUID, settings: Settings
) -> SyncOutcome:
    """One pass over one project's repositories.

    Returns rather than raises: a provider that is unwell must not abort the reconcile
    pass for the *other* projects, which is why every failure is caught per repository and
    turned into a stored reason.
    """
    project = await session.get(Project, project_id)
    if project is None or not project.provider_sync_enabled:
        return SyncOutcome()

    repositories = (
        (
            await session.execute(
                sa.select(ProjectRepository).where(ProjectRepository.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )

    outcome = SyncOutcome()
    store = KnowledgeStore(session)
    secrets = SecretService(session, settings=settings)

    for repository in repositories:
        if repository.provider_sync_failures >= provider_sources.MAX_CONSECUTIVE_FAILURES:
            outcome = _with(outcome, skipped=1)
            continue
        if not provider_reads.supports_host(repository.host):
            # Not a failure and not retried: a host with no reader will not grow one on
            # the next pass. Counting it as a failure would eventually "stop" a repository
            # that was never started.
            outcome = _with(outcome, skipped=1)
            continue
        if not await _within_rate_ceiling(session, repository):
            outcome = _with(outcome, skipped=1)
            continue

        token = await _token(secrets, project, repository)
        if token is None:
            repository.provider_sync_error = (
                "This repository has no provider token; provider sync needs one to read."
            )
            outcome = _with(outcome, skipped=1)
            continue

        try:
            written = await _sync_repository(
                session, store=store, repository=repository, token=token, settings=settings
            )
        except provider_reads.ProviderReadError as exc:
            repository.provider_sync_failures += 1
            # The provider's own words, already stripped of the token by `_safe_detail`.
            repository.provider_sync_error = exc.message
            metrics.increment(metrics.PROVIDER_READ_TOTAL, host=repository.host, status="refused")
            log.warning(
                "provider_sync_failed",
                extra={
                    "event": "provider_sync_failed",
                    "code": exc.code,
                    # No repository id and no path: a log line is redacted, but the habit
                    # of not putting identifiers in one is what keeps it that way.
                },
            )
            outcome = _with(outcome, failures=1)
            continue

        repository.provider_sync_failures = 0
        repository.provider_sync_error = None
        repository.provider_synced_at = now_utc()
        metrics.increment(metrics.PROVIDER_READ_TOTAL, host=repository.host, status="ok")
        outcome = _with(outcome, repositories=1, sources=written)

    return outcome


async def _sync_repository(
    session: AsyncSession,
    *,
    store: KnowledgeStore,
    repository: ProjectRepository,
    token: str,
    settings: Settings,
) -> int:
    """The ≤3 reads, and whatever they turn out to be worth."""
    reader = provider_reads.reader_for(repository.host, settings)
    if reader is None:  # pragma: no cover - guarded by `supports_host` above
        return 0

    since = repository.provider_synced_at or (now_utc() - FIRST_PASS_WINDOW)
    extracted: list[tuple[str, ExtractedSource]] = []

    for state in await reader.list_pull_requests(
        repo_path=repository.path, token=token, since=since
    ):
        extracted.append(
            (
                "pull_request",
                provider_sources.pull_request_source(
                    repository=repository,
                    number=state.number,
                    title=state.title,
                    body=state.body,
                    merged=state.merged,
                    merged_at=state.merged_at,
                    head_ref=state.head_ref,
                    base_ref=state.base_ref,
                    url=state.url,
                    updated_at=state.updated_at,
                ),
            )
        )

    for version in await reader.list_published_versions(repo_path=repository.path, token=token):
        # **Drafts are filtered here, not in the handler.** "A draft is not a fact" is an
        # ingestion rule; a handler that silently returned nothing for one would look like
        # a handler that found nothing.
        if version.draft:
            continue
        if version.published_at is not None and version.published_at <= since:
            continue
        extracted.append(
            (
                "release",
                provider_sources.published_version_source(
                    repository=repository,
                    tag=version.tag,
                    name=version.name,
                    body=version.body,
                    published_at=version.published_at,
                    prerelease=version.prerelease,
                    url=version.url,
                ),
            )
        )

    written = 0
    for source_type, source in extracted:
        result = await store.upsert(
            project_id=repository.project_id, source_type=source_type, source=source
        )
        if result is not None and result.inserted:
            written += 1
    return written


async def _within_rate_ceiling(session: AsyncSession, repository: ProjectRepository) -> bool:
    """Whether this repository has budget left this hour.

    Derived from `provider_synced_at` rather than from a counter: the column moves once
    per successful round, so "how many rounds did this repository cost" is already
    recorded. A counter table would be a second place the answer lives.

    The approximation this accepts, stated: only the *last* success is stored, so this
    cannot count rounds — it can only tell whether the last one was too recent. At a
    300-second cadence that is the same question, and a table that could answer the
    stronger one is a table that can disagree with the column.
    """
    if repository.provider_synced_at is None:
        return True
    minimum_gap = timedelta(hours=1) / 36
    return now_utc() - repository.provider_synced_at >= minimum_gap


async def _token(
    secrets: SecretService, project: Project, repository: ProjectRepository
) -> str | None:
    """The existing `provider_token` kind, per repository. `secrets.py` is unchanged.

    It is in `UNDELIVERABLE_KINDS`, so it is never delivered to a node — which is why this
    read happens in Central and could not happen anywhere else even if the design wanted
    it to.
    """
    if repository.provider_token_secret_id is None:
        return None
    return await secrets.provider_token(project.id, repository.provider_token_secret_id)


def _with(outcome: SyncOutcome, **delta: int) -> SyncOutcome:
    return SyncOutcome(
        repositories=outcome.repositories + delta.get("repositories", 0),
        sources=outcome.sources + delta.get("sources", 0),
        failures=outcome.failures + delta.get("failures", 0),
        skipped=outcome.skipped + delta.get("skipped", 0),
    )
