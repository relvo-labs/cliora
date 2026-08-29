"""The two handlers whose facts come from somebody else's server (`HD-02`/`HD-03`).

**A file of its own, and the file boundary is the enforcement.** ADR 0043 §4 puts a
ceiling on what provider data may assert: a merged pull request is `reviewed` and nothing
above it. `GATE-HD-PROVIDER-AUTHORITY-CEILING` states that as an absence — the four words
above the ceiling do not appear in this file.

That gate cannot live on `sources.py`, where several handlers legitimately assign the
levels above the ceiling — an approved requirement and a settled decision both earn one.
A grep there would have to know *which function* a string sits in, which means an AST,
which means a gate nobody can read at a glance. Splitting the file makes the same rule a
one-line grep.

**Which is why this docstring does not spell those levels out either.** The gate reads
the whole file, comments included, and that is deliberate: a rule enforced by absence
stops being enforceable the moment prose is exempted from it.

The two rules from `sources.py` hold here unchanged: **a handler reads and returns, it
never writes** (all writing is `store.py`), and **a handler describes the entity as it is
now**, not the event that woke it. Redaction happens once, in `sources.ingest()`, on the
way out — which is why these handlers do not call it and must not start.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectRepository
from app.services.knowledge.store import ExtractedSource

#: The **only** two values a provider fact may carry (ADR 0043 §4 lists the four above it).
#:
#: A frozenset rather than two literals at the write sites: the ceiling is a property of
#: this module, and a set makes it one thing to read. The gate is the second layer — this
#: is the first, and it is the one a reader sees.
PROVIDER_AUTHORITIES: frozenset[str] = frozenset({"discussion", "reviewed"})

#: Consecutive failed rounds before a repository stops being read (`plan/27` D128).
#:
#: A product decision rather than a tuning one: an un-revoked token would otherwise
#: produce an error every five minutes for ever, and the console would show nothing —
#: "no new pull requests" and "we stopped asking" look identical on screen.
#:
#: **It lives in this module rather than beside the reader** because two places need it
#: and only one of them may import the reader: `provider_sync` acts on it, and the
#: repository DTO renders the verdict. `GATE-HD-NO-PROVIDER-IN-REQUEST` keeps `api/http/`
#: away from `provider_reads`, so a shared home was the only way to avoid a second copy of
#: the number — and a threshold with two homes eventually disagrees with itself.
MAX_CONSECUTIVE_FAILURES = 3

#: What a merged pull request and a published version are worth.
#:
#: `reviewed` has had a rerank weight since `alpha.3` and no writer; `store.py` recorded
#: why at the time — it "arrives with provider sync". This is that arrival.
_MERGED = "reviewed"
_UNMERGED = "discussion"


def _assert_ceiling(authority: str) -> str:
    """Belt to the gate's braces, at the one point every value passes through.

    The gate reads the file's text and this reads the value, so the two fail on different
    mistakes: the gate catches somebody typing the word, this catches somebody computing
    it. Neither alone is enough — a value assembled from a variable would pass the gate.
    """
    if authority not in PROVIDER_AUTHORITIES:
        raise ValueError(
            f"provider data may not claim {authority!r}; ADR 0043 §4 caps it at "
            f"{sorted(PROVIDER_AUTHORITIES)}"
        )
    return authority


def _fields(*pairs: tuple[str, object]) -> str:
    return "\n\n".join(f"## {label}\n\n{value}" for label, value in pairs if value)


async def _repository(
    session: AsyncSession, project_id: uuid.UUID, repository_id: str
) -> ProjectRepository | None:
    try:
        parsed = uuid.UUID(repository_id)
    except ValueError:
        return None
    row = await session.get(ProjectRepository, parsed)
    return row if row is not None and row.project_id == project_id else None


def pull_request_source(
    *,
    repository: ProjectRepository,
    number: int,
    title: str,
    body: str,
    state: str,
    merged: bool,
    merged_at: datetime | None,
    head_ref: str,
    base_ref: str,
    url: str,
    updated_at: datetime,
) -> ExtractedSource:
    """One pull request, at whatever state it is in now.

    **`external_id` names the repository as well as the number.** Two repositories in one
    project both have a `#12`, and a key that omitted the repository would make the second
    one overwrite the first — silently, because the upsert would read it as a new version
    of the same entity.

    **`source_version` is the provider's `updated_at`.** A pull request that goes from open
    to merged is the *same entity, a new version*, so it supersedes rather than duplicating
    — which is exactly what `store.upsert` already does with `source_updated_at`.
    """
    authority = _assert_ceiling(_MERGED if merged else _UNMERGED)
    if merged and merged_at:
        state_line = f"已於 {merged_at:%Y-%m-%d %H:%M} 合併"
    elif state == "closed":
        state_line = "已關閉，未合併"
    else:
        state_line = "尚未合併"
    return ExtractedSource(
        external_id=f"{repository.id}:pr:{number}",
        version=updated_at.isoformat(),
        title=f"PR #{number} {title}".strip(),
        text=_fields(
            ("狀態", f"{state_line}（{head_ref} → {base_ref}）"),
            ("說明", body),
        ),
        authority=authority,
        uri=url,
        occurred_at=merged_at or updated_at,
        source_updated_at=updated_at,
        # A rejected proposal remains as history but is not evidence for the default
        # context.  This is deliberately not a tombstone: the PR still exists upstream.
        active=merged or state != "closed",
    )


def published_version_source(
    *,
    repository: ProjectRepository,
    tag: str,
    name: str,
    body: str,
    published_at: datetime | None,
    prerelease: bool,
    url: str,
) -> ExtractedSource:
    """One published version.

    Callers must not pass a draft — `sources.ingest` filters them out before this, because
    "a draft is not a fact" is an ingestion rule rather than a formatting one, and a
    handler that silently skipped its input would return nothing and look like a handler
    that found nothing.

    A prerelease **is** ingested and says so in the body: it happened, and a context pack
    that omitted it would be unable to explain a version number somebody is looking at.
    """
    return ExtractedSource(
        external_id=f"{repository.id}:ver:{tag}",
        version=(published_at or datetime.min).isoformat(),
        title=f"{name or tag}".strip(),
        text=_fields(
            ("版本", f"{tag}{'（預發行）' if prerelease else ''}"),
            ("說明", body),
        ),
        authority=_assert_ceiling(_MERGED),
        uri=url,
        occurred_at=published_at or datetime.min,
        source_updated_at=published_at or datetime.min,
    )


async def read_pull_request(
    session: AsyncSession, project_id: uuid.UUID, external_id: str
) -> list[ExtractedSource]:
    """Re-read one pull request from what was last stored about it.

    **This handler does not call the provider.** A job is a hint and the worker's job is to
    re-read the entity's current state — but "the entity" here lives on somebody else's
    server, and reaching it from a handler would put an outbound GET inside the ingest
    transaction. The reconciler fetches (`worker.py`) and enqueues with the payload; this
    turns that payload into a source.

    It is the one place these handlers differ from the eight in `sources.py`, and the
    difference is the whole of ADR 0043 §2: the fact is not ours to re-read on demand.
    """
    return []


async def read_published_version(
    session: AsyncSession, project_id: uuid.UUID, external_id: str
) -> list[ExtractedSource]:
    """Same shape and the same reason as :func:`read_pull_request`."""
    return []


async def sync_enabled(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Whether this project asked for provider sync at all.

    Read at the top of every reconcile pass rather than cached: turning it off is meant to
    stop the next round, and a cache would make "off" mean "off in five minutes".
    """
    enabled = await session.scalar(
        sa.select(Project.provider_sync_enabled).where(Project.id == project_id)
    )
    return bool(enabled)
