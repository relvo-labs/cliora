"""Lexical hybrid retrieval (`KN-07`, ADR 0038 §4, D40/D79).

Three candidate channels, one rerank, and one predicate that is never optional.

**No vector channel** (D40, 2026-08-16). Adding pgvector changes the database image with
no downgrade path, and an embedding provider adds an outbound connection whose payload
is the most sensitive content in the system. `knowledge_chunks.embedding_ref` exists and
is always `NULL`; `_candidates` is written so a second candidate source drops in beside
the two below. The architecture does not block it; this release does not do it.

**The accepted cost of that** is a query whose wording differs from its source's — "how
do we handle timeouts" against a document that says `lease expiry`. It is bought back by
explicit links and by human pins, which is why a pin outranks every computed score
rather than merely adding to it: a pin that a score can push out is not a pin.

Two channels rather than one `OR`: PostgreSQL will use one index for an `OR`, and two
GIN scans over their own top-K plus a small merge is cheaper than one scan plus a heap
filter over everything the other half matched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import (
    KnowledgeChunk,
    KnowledgeLink,
    KnowledgeSource,
    Project,
    Task,
    TaskDependency,
    TaskKnowledgePin,
)
from app.services.knowledge.store import HISTORICAL_AUTHORITIES
from app.services.knowledge.tokenize import has_cjk, lexemes

#: Per channel, before the merge. A constant rather than a multiple of `limit` so the
#: rerank always has the same amount of material to work with — a top-3 request that
#: only reranked three candidates would be ranking nothing.
CANDIDATES = 50

#: Trigram floor. Set on the connection rather than compared in SQL: a
#: `similarity(a, b) > x` comparison cannot use the GIN index, and the operator can.
#:
#: **This is the `word_similarity` floor, and the change from `similarity` is a defect
#: fix, not a tuning choice** (`plan/27` `HD-10`, 2026-08-28).
#:
#: `%` compares two strings *whole*. A chunk is ~100–800 characters and a query like a
#: card reference, a commit SHA or a function name is under twenty, so the union of their
#: trigrams is dominated by the chunk and the score is near zero however good the match:
#: measured at **0.05** for a chunk that literally contains the query. Against a floor of
#: 0.25 the channel therefore matched **nothing** — while still costing 131 ms at 20,000
#: chunks, because the GIN index returned every row as a candidate and the recheck
#: discarded all of them.
#:
#: `<%` (`word_similarity`) compares the query against the *best-matching extent* inside
#: the content, which is the question this channel was always asking. Same chunk, same
#: query: **1.0**.
#:
#: The docstring above says this channel exists to find "a SHA, a function name, a typo".
#: All three are short needles in long haystacks, and `%` cannot serve any of them.
TRIGRAM_THRESHOLD = 0.6

_CHANNEL_WEIGHTS = {"fts": 1.0, "trigram": 0.8}

#: Authority × trust. `superseded` and `retracted` are absent because they are excluded
#: in the `WHERE`, not down-weighted here — a weight of zero is still a row that gets
#: scored and still takes a candidate slot.
_AUTHORITY_WEIGHT = {
    "authoritative": 1.60,
    "accepted": 1.45,
    "canonical": 1.35,
    "verified": 1.25,
    "reviewed": 1.15,
    "generated": 0.85,
    "discussion": 0.75,
    "diagnostic": 0.60,
}

#: Half-life in days, per source type. A charter must not decay to nothing, which is why
#: `policy` is measured in years and why **every** source type has a floor below.
_HALF_LIFE_DAYS = {
    "conversation": 30.0,
    "activity": 30.0,
    "ticket": 60.0,
    "verification": 90.0,
    "artifact": 90.0,
    "repo_doc": 180.0,
    "decision": 365.0,
    "policy": 3650.0,
    # `0044`. **Chosen, not measured** (`plan/27/10` §5), and written down rather than
    # left to `.get(…, 90.0)`: the default would silently give a published version the
    # same 90 days as an artifact, and "what is in v1.4" does not become less true with
    # age. A pull request's discussion is the artifact case — it explains why the code
    # looks the way it does for a few months, and it is not a specification.
    "pull_request": 90.0,
    "release": 365.0,
}
#: **Old is not the same as wrong.** Without a floor, a three-year-old charter ranks
#: below yesterday's passing remark, and the whole point of the authority column is
#: undone by the freshness one.
_FRESHNESS_FLOOR = 0.5

_PIN_BONUS = 2.0
_GRAPH_EPIC = 0.20
_GRAPH_DEPENDENCY = 0.30
_GRAPH_LINK = 0.25


@dataclass(frozen=True, slots=True)
class SearchHit:
    source_id: uuid.UUID
    source_type: str
    title: str
    authority: str
    version: str
    occurred_at: datetime
    uri: str | None
    excerpt: str
    content: str
    score: float
    historical: bool
    why: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchResult:
    items: list[SearchHit]
    total: int
    channels: tuple[str, ...]
    degraded: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _tsquery(text: str) -> sa.ColumnElement[sa.types.NullType] | None:
    """Build the query from the **same** lexemes the index was written with.

    **`|`, not `&`**, and for CJK the difference is not a preference. A four-character
    phrase becomes three bigrams, so an `AND` over every lexeme of a sentence-length
    query is a phrase match in disguise: "租約過期時要怎麼處理" would require the
    document to contain 時要, 要怎, 怎麼 and 麼處 as well, and a document about lease
    expiry does not. Layer 4's query is *derived from the card's own title*, which is
    exactly that shape, so `AND` would make the retrieved layer almost always empty —
    silently, because an empty result is indistinguishable from a project with nothing
    written about the subject.

    `ts_rank_cd` and the authority/freshness rerank are what turn the wide candidate set
    back into an ordering. Whether an explicit human search should be stricter than a
    derived one is a real question, and it is `KN-13`'s relevance evaluation that gets to
    answer it — with numbers, not with a preference expressed in a comment.
    """
    terms = lexemes(text)
    if not terms:
        return None
    # `to_tsquery` with quoted lexemes: they come from our own tokenizer, which emits no
    # whitespace and no operators, so quoting each one is sufficient and there is nothing
    # left for a caller to inject.
    joined = " | ".join(f"'{term}'" for term in terms)
    return sa.func.to_tsquery("simple", joined)


def _freshness(source_type: str, occurred_at: datetime, now: datetime) -> float:
    half_life = _HALF_LIFE_DAYS.get(source_type, 90.0)
    age_days = max(0.0, (now - occurred_at).total_seconds() / 86400.0)
    decay = 0.5 ** (age_days / half_life)
    return _FRESHNESS_FLOOR + (1.0 - _FRESHNESS_FLOOR) * decay


class KnowledgeSearch:
    """Retrieval for one project. **The project is a constructor argument, not a filter.**

    `GATE-KN-PROJECT-SCOPED` asserts that every select against a `knowledge_*` table
    carries a `project_id` predicate, and this class is the only place those selects are
    written.
    """

    def __init__(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        self._session = session
        self._project_id = project_id

    async def require_enabled(self) -> None:
        """404, never 403 — the status must not disclose that the project exists and has
        the feature switched off (ADR 0038 §7)."""
        from app.api.errors import ApiError

        enabled = await self._session.scalar(
            sa.select(Project.knowledge_enabled).where(Project.id == self._project_id)
        )
        if not enabled:
            raise ApiError("KNOWLEDGE_DISABLED", "Project memory is not enabled", 404)

    def _scope(self, stmt: sa.Select, *, include_history: bool) -> sa.Select:
        """The isolation predicate. Every query goes through here."""
        stmt = stmt.where(
            KnowledgeChunk.project_id == self._project_id,
            KnowledgeChunk.valid_to.is_(None),
            KnowledgeSource.project_id == self._project_id,
            KnowledgeSource.deleted_at.is_(None),
        )
        if not include_history:
            stmt = stmt.where(
                KnowledgeSource.active.is_(True),
                KnowledgeSource.authority.notin_(sorted(HISTORICAL_AUTHORITIES)),
            )
        return stmt

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        source_types: list[str] | None = None,
        authorities: list[str] | None = None,
        task_id: uuid.UUID | None = None,
        include_history: bool = False,
    ) -> SearchResult:
        await self.require_enabled()
        query = query.strip()
        if not query:
            return SearchResult(items=[], total=0, channels=())

        # A one-character CJK query produces no bigram, so the full-text channel has
        # nothing to match. Saying so is the point: a silently empty page reads as "this
        # project has nothing about that", which is a different and wrong answer.
        tsquery = _tsquery(query)
        degraded = None
        if tsquery is None:
            degraded = "single_token" if has_cjk(query) else "no_lexemes"

        pins, exclusions = await self._pins(task_id)
        rows = await self._candidates(
            query,
            tsquery,
            source_types=source_types,
            authorities=authorities,
            include_history=include_history,
        )
        graph = await self._graph_neighbours(task_id)
        now = now_utc()

        hits: list[SearchHit] = []
        for row in rows:
            if row.source_id in exclusions:
                continue
            score, why = self._score(row, graph=graph, pins=pins, now=now)
            hits.append(
                SearchHit(
                    source_id=row.source_id,
                    source_type=row.source_type,
                    title=row.title or row.source_external_id,
                    authority=row.authority,
                    version=row.source_version,
                    occurred_at=row.occurred_at,
                    uri=row.source_uri,
                    excerpt=_excerpt(row.content, query),
                    content=row.content,
                    score=score,
                    historical=row.authority in HISTORICAL_AUTHORITIES,
                    why=why,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.source_id.hex))
        channels: tuple[str, ...] = () if tsquery is None else ("fts",)
        return SearchResult(
            items=hits[:limit],
            total=len(hits),
            channels=(*channels, "trigram"),
            degraded=degraded,
        )

    async def _candidates(
        self,
        query: str,
        tsquery: sa.ColumnElement | None,
        *,
        source_types: list[str] | None,
        authorities: list[str] | None,
        include_history: bool,
    ) -> list:
        """Each channel takes its own top-K; the merge happens in Python.

        Written as a list of channels rather than as one statement so that a second
        candidate source — the vector one D40 declined — is an entry here rather than a
        rewrite.
        """
        base_columns = (
            KnowledgeChunk.content,
            KnowledgeSource.id.label("source_id"),
            KnowledgeSource.source_type,
            KnowledgeSource.source_external_id,
            KnowledgeSource.source_version,
            KnowledgeSource.authority,
            KnowledgeSource.title,
            KnowledgeSource.occurred_at,
            KnowledgeSource.source_uri,
        )
        merged: dict[uuid.UUID, dict] = {}

        def _filters(stmt: sa.Select) -> sa.Select:
            stmt = self._scope(stmt, include_history=include_history)
            if source_types:
                stmt = stmt.where(KnowledgeSource.source_type.in_(source_types))
            if authorities:
                stmt = stmt.where(KnowledgeSource.authority.in_(authorities))
            return stmt

        if tsquery is not None:
            rank = sa.func.ts_rank_cd(KnowledgeChunk.search_document, tsquery)
            stmt = _filters(
                sa.select(*base_columns, rank.label("rank"))
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)
                .where(KnowledgeChunk.search_document.op("@@")(tsquery))
                .order_by(rank.desc())
                .limit(CANDIDATES)
            )
            for row in (await self._session.execute(stmt)).all():
                _merge(merged, row, "fts", float(row.rank))

        # The threshold is a per-connection setting because the operator is the only form
        # that uses the trigram index; a `word_similarity() > x` comparison reads more
        # clearly and scans the whole table.
        #
        # `SET`, not `SELECT set_limit(...)`: `%` has a setter function and `<%` does
        # not — only the GUC. Setting `similarity_threshold` while querying with `<%`
        # would leave the real threshold at its 0.6 default, silently and with plausible
        # results, which is why this line does not look like the one it replaced.
        #
        # The value is interpolated because `SET` does not take bind parameters. `float()`
        # is the guard: `TRIGRAM_THRESHOLD` is a module constant, and coercing it makes
        # the statement un-injectable regardless of what someone later assigns to it.
        await self._session.execute(
            sa.text(f"SET pg_trgm.word_similarity_threshold = {float(TRIGRAM_THRESHOLD)}")
        )
        # **Argument order matters and is not symmetric.** `word_similarity(a, b)` asks
        # "how well does `a` match some extent of `b`", so the query goes first. Reversed,
        # it asks how well a whole chunk matches part of a twelve-character query, which
        # is the near-zero number this fix exists to stop computing.
        similarity = sa.func.word_similarity(query, KnowledgeChunk.content)
        stmt = _filters(
            sa.select(*base_columns, similarity.label("rank"))
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)
            .where(sa.literal(query).op("<%")(KnowledgeChunk.content))
            .order_by(similarity.desc())
            .limit(CANDIDATES)
        )
        for row in (await self._session.execute(stmt)).all():
            _merge(merged, row, "trigram", float(row.rank))

        return [_Row(**value) for value in merged.values()]

    async def _pins(self, task_id: uuid.UUID | None) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        if task_id is None:
            return set(), set()
        rows = (
            await self._session.execute(
                sa.select(TaskKnowledgePin.source_id, TaskKnowledgePin.mode)
                .join(KnowledgeSource, KnowledgeSource.id == TaskKnowledgePin.source_id)
                .where(
                    TaskKnowledgePin.task_id == task_id,
                    KnowledgeSource.project_id == self._project_id,
                )
            )
        ).all()
        pinned = {row.source_id for row in rows if row.mode == "pin"}
        excluded = {row.source_id for row in rows if row.mode == "exclude"}
        return pinned, excluded

    async def _graph_neighbours(self, task_id: uuid.UUID | None) -> dict[uuid.UUID, list[str]]:
        """Sources related to this card by something explicit, never by similarity."""
        if task_id is None:
            return {}
        task = await self._session.get(Task, task_id)
        if task is None or task.project_id != self._project_id:
            return {}

        related: dict[uuid.UUID, list[str]] = {}

        def _note(source_id: uuid.UUID, reason: str) -> None:
            related.setdefault(source_id, []).append(reason)

        own = f"task:{task_id}"
        for source_id in await self._sources_for([own]):
            _note(source_id, "graph:this_card")

        dependencies = (
            (
                await self._session.execute(
                    sa.select(TaskDependency.depends_on_task_id).where(
                        TaskDependency.task_id == task_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if dependencies:
            for source_id in await self._sources_for([f"task:{dep}" for dep in dependencies]):
                _note(source_id, "graph:dependency")

        if task.epic_id is not None:
            siblings = (
                (
                    await self._session.execute(
                        sa.select(Task.id).where(
                            Task.epic_id == task.epic_id,
                            Task.project_id == self._project_id,
                            Task.id != task_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if siblings:
                for source_id in await self._sources_for([f"task:{sib}" for sib in siblings]):
                    _note(source_id, "graph:same_epic")

        if related:
            # Joined to `knowledge_sources` for the `project_id`, although every id in
            # `related` already came from a project-scoped query. Transitive scoping is
            # true and unreadable: a reviewer would have to trace three call sites to
            # confirm it, and `GATE-KN-PROJECT-SCOPED` cannot see it at all. One join
            # makes the predicate a property of the statement.
            source = sa.orm.aliased(KnowledgeSource)
            linked = (
                await self._session.execute(
                    sa.select(KnowledgeLink.from_source_id, KnowledgeLink.relation)
                    .join(source, source.id == KnowledgeLink.from_source_id)
                    .where(
                        KnowledgeLink.to_source_id.in_(list(related)),
                        source.project_id == self._project_id,
                    )
                )
            ).all()
            for row in linked:
                _note(row.from_source_id, f"graph:{row.relation}")
        return related

    async def _sources_for(self, external_ids: list[str]) -> list[uuid.UUID]:
        if not external_ids:
            return []
        return list(
            (
                await self._session.execute(
                    sa.select(KnowledgeSource.id).where(
                        KnowledgeSource.project_id == self._project_id,
                        KnowledgeSource.source_external_id.in_(external_ids),
                        KnowledgeSource.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

    def _score(
        self,
        row: _Row,
        *,
        graph: dict[uuid.UUID, list[str]],
        pins: set[uuid.UUID],
        now: datetime,
    ) -> tuple[float, tuple[str, ...]]:
        """The whole ranking, in one readable place.

        `why` is not decoration. It is the data behind the "why was this chosen" line in
        the UI and the only part of retrieval a person can audit without reading SQL —
        which is the entire argument for the Knowledge page existing (upstream §8).
        """
        why: list[str] = []
        lexical = 0.0
        for channel, rank in row.channels.items():
            lexical += _CHANNEL_WEIGHTS[channel] * rank
            why.append(f"{channel}:{rank:.3f}")

        authority = _AUTHORITY_WEIGHT.get(row.authority, 0.5)
        freshness = _freshness(row.source_type, row.occurred_at, now)
        score = lexical * authority * freshness
        why.append(f"authority:{row.authority}")
        if freshness < 0.95:
            why.append(f"freshness:{freshness:.2f}")

        for reason in graph.get(row.source_id, ()):
            bonus = {
                "graph:dependency": _GRAPH_DEPENDENCY,
                "graph:this_card": _GRAPH_DEPENDENCY,
                "graph:same_epic": _GRAPH_EPIC,
            }.get(reason, _GRAPH_LINK)
            score += bonus
            why.append(reason)

        if row.source_id in pins:
            # Large enough to always clear the field. A pin is a person saying "whatever
            # your arithmetic says, this card reads this", and one a score can displace
            # is not a pin.
            score += _PIN_BONUS
            why.append("pinned")
        return score, tuple(why)


@dataclass(slots=True)
class _Row:
    source_id: uuid.UUID
    source_type: str
    source_external_id: str
    source_version: str
    authority: str
    title: str | None
    occurred_at: datetime
    source_uri: str | None
    content: str
    channels: dict[str, float]


def _merge(merged: dict[uuid.UUID, dict], row, channel: str, rank: float) -> None:
    """One source, however many chunks matched.

    The best-scoring chunk wins the excerpt. Summing them would let a long document
    outrank a precise one purely by repeating the term, which is the failure mode
    `ts_rank_cd`'s density normalisation exists to avoid in the first place.
    """
    existing = merged.get(row.source_id)
    if existing is None:
        merged[row.source_id] = {
            "source_id": row.source_id,
            "source_type": row.source_type,
            "source_external_id": row.source_external_id,
            "source_version": row.source_version,
            "authority": row.authority,
            "title": row.title,
            "occurred_at": row.occurred_at,
            "source_uri": row.source_uri,
            "content": row.content,
            "channels": {channel: rank},
        }
        return
    if rank > existing["channels"].get(channel, 0.0):
        existing["channels"][channel] = rank
        existing["content"] = row.content


def _excerpt(content: str, query: str, *, window: int = 120) -> str:
    """A snippet around the first hit, found in Python.

    **Not `ts_headline`**: that re-parses the original text with a text-search
    configuration, and the lexemes this system indexes are not the ones the stock parser
    would produce (ADR 0038 §4). It would highlight the wrong thing, or nothing.
    """
    if len(content) <= window * 2:
        return content
    needle = None
    for term in lexemes(query):
        position = content.lower().find(term)
        if position >= 0:
            needle = position
            break
    if needle is None:
        return content[: window * 2] + "…"
    start = max(0, needle - window)
    end = min(len(content), needle + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"
