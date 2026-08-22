"""The idempotent write: one source, its chunks, and the tombstone (ADR 0038 §3.3).

Every handler in `sources.py` reads and returns; **nothing but this module writes**. One
copy of the upsert means one place where the concurrency argument has to be right, and
that argument is the whole of the module:

    INSERT … ON CONFLICT (project, type, external_id, version)
    DO UPDATE SET … WHERE excluded.source_updated_at > knowledge_sources.source_updated_at

rather than "read the row, decide, then write". The read-then-write shape double-writes
when two workers handle one resource at once, which is not hypothetical here: claiming
uses `SKIP LOCKED`, so two replicas hold two jobs, and two jobs pointing at one card is
ordinary traffic.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import KnowledgeChunk, KnowledgeLink, KnowledgeSource
from app.services.knowledge.chunking import Chunk
from app.services.knowledge.chunking import chunk as split_into_chunks
from app.services.knowledge.tokenize import document

#: Authority levels, highest trust first. The order is meaningful — `search.py` reads
#: it for the rerank weight — and the two with no writer in `alpha.3` (`reviewed`,
#: which arrives with provider sync) are present anyway, because merging levels later
#: is a migration while splitting one later is a judgement about rows written before
#: the distinction existed (ADR 0038 §2, D85).
AUTHORITIES: tuple[str, ...] = (
    "authoritative",
    "accepted",
    "canonical",
    "verified",
    "reviewed",
    "generated",
    "discussion",
    "diagnostic",
    "superseded",
    "retracted",
)

#: `setweight`'s second argument is PostgreSQL's `"char"`, a distinct one-byte type with
#: no `varchar` overload — and a bound parameter arrives as `varchar`, which fails with
#: "function setweight(tsvector, character varying) does not exist". A `literal_column`
#: emits the letter untyped and lets the server resolve it.
_WEIGHT_TITLE: sa.ColumnElement[str] = sa.literal_column("'A'")
_WEIGHT_BODY: sa.ColumnElement[str] = sa.literal_column("'B'")

#: Excluded from default retrieval entirely rather than down-weighted. A weight of zero
#: is still a row that gets scored, still takes a candidate slot, and still turns up
#: after some future join.
HISTORICAL_AUTHORITIES: frozenset[str] = frozenset({"superseded", "retracted"})

SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "policy",
        "ticket",
        "conversation",
        "decision",
        "artifact",
        "verification",
        "repo_doc",
        "activity",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractedSource:
    """One version of one fact, as a handler produces it.

    `source_updated_at` is **not** `occurred_at`: a message written yesterday can be
    ingested today, and it is the former that decides whether an arriving row is newer
    than the stored one. Handlers that have only one meaningful timestamp pass it as
    both, and that is correct rather than lazy — for an immutable source the two really
    are the same instant.
    """

    external_id: str
    version: str
    authority: str
    title: str
    text: str
    occurred_at: datetime
    source_updated_at: datetime
    uri: str | None = None
    authored_by_type: str | None = None
    authored_by_id: uuid.UUID | None = None
    links: tuple[tuple[str, str], ...] = ()
    # Overrides the derived checksum. Set only by `repo_doc`, where the file's own
    # sha256 **is** the identity the client negotiated with: the manifest compares this
    # column against the digest the agent computed, so deriving a different one here
    # would make every sync re-upload everything and nothing would say why.
    checksum: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UpsertResult:
    source_id: uuid.UUID
    inserted: bool
    superseded: int
    chunks: int


def _checksum(source: ExtractedSource) -> str:
    if source.checksum is not None:
        return source.checksum
    return hashlib.sha256(f"{source.title}\x00{source.text}".encode()).hexdigest()


class KnowledgeStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, project_id: uuid.UUID, source_type: str, source: ExtractedSource
    ) -> UpsertResult:
        assert source_type in SOURCE_TYPES, source_type
        assert source.authority in AUTHORITIES, source.authority
        chunks = split_into_chunks(source.text)
        now = now_utc()

        stmt = pg_insert(KnowledgeSource).values(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type=source_type,
            source_external_id=source.external_id,
            source_version=source.version,
            source_uri=source.uri,
            authority=source.authority,
            checksum=_checksum(source),
            title=source.title[:500],
            authored_by_type=source.authored_by_type,
            authored_by_id=source.authored_by_id,
            occurred_at=source.occurred_at,
            source_updated_at=source.source_updated_at,
            ingested_at=now,
            chunk_count=len(chunks),
            active=True,
        )
        upsert: Any = stmt.on_conflict_do_update(
            constraint="uq_knowledge_sources_identity",
            set_={
                "authority": stmt.excluded.authority,
                "title": stmt.excluded.title,
                "source_uri": stmt.excluded.source_uri,
                "checksum": stmt.excluded.checksum,
                "source_updated_at": stmt.excluded.source_updated_at,
                "occurred_at": stmt.excluded.occurred_at,
                "ingested_at": stmt.excluded.ingested_at,
                "chunk_count": stmt.excluded.chunk_count,
                "active": sa.true(),
                "deleted_at": sa.null(),
            },
            where=KnowledgeSource.source_updated_at < stmt.excluded.source_updated_at,
            # `xmax = 0` is PostgreSQL's way of saying "this row was inserted, not
            # updated" — the system column is zero only for a fresh tuple. It is a
            # `literal_column` with an explicit label rather than raw text so the result
            # has a name to read it by; `RETURNING` mixing an ORM attribute with a bare
            # text fragment produces a row the label cannot address.
        ).returning(KnowledgeSource.id, sa.literal_column("xmax = 0").label("inserted"))
        row = (await self._session.execute(upsert)).mappings().first()

        if row is None:
            # **Not a failure.** When the `WHERE` is false the statement updates nothing
            # and `RETURNING` is empty — the shape of an out-of-order delivery, which is
            # the case this comparison exists to handle. The row is already there and
            # already newer, so the work is done; look up the id and stop.
            existing = (
                await self._session.execute(
                    sa.select(KnowledgeSource.id, KnowledgeSource.chunk_count).where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.source_type == source_type,
                        KnowledgeSource.source_external_id == source.external_id,
                        KnowledgeSource.source_version == source.version,
                    )
                )
            ).first()
            assert existing is not None, "conflict fired but the conflicting row is gone"
            return UpsertResult(
                source_id=existing.id, inserted=False, superseded=0, chunks=existing.chunk_count
            )

        source_id = row["id"]
        await self._write_chunks(
            project_id=project_id,
            source_id=source_id,
            chunks=chunks,
            title=source.title,
            now=now,
        )
        superseded = await self._supersede_older(
            project_id=project_id,
            source_type=source_type,
            external_id=source.external_id,
            keep_id=source_id,
            keep_updated_at=source.source_updated_at,
        )
        await self._write_links(project_id, source_id, source.links)
        return UpsertResult(
            source_id=source_id,
            inserted=bool(row["inserted"]),
            superseded=superseded,
            chunks=len(chunks),
        )

    async def _write_chunks(
        self,
        *,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        chunks: list[Chunk],
        title: str,
        now: datetime,
    ) -> None:
        for piece in chunks:
            stmt = pg_insert(KnowledgeChunk).values(
                id=uuid.uuid4(),
                source_id=source_id,
                project_id=project_id,
                chunk_key=piece.key,
                content=piece.content,
                content_hash=piece.content_hash,
                token_count=piece.token_count,
                # **Title at weight A, body at weight B** (ADR 0038 §4). Not decoration:
                # a card called "租約過期時要怎麼處理" whose body never repeats the phrase
                # is exactly the document somebody searching that phrase wants, and
                # without this it is unfindable. `KN-13`'s measurement caught the
                # omission — two of eight fixed queries returned nothing — which is what
                # a measurement is for.
                #
                # Repeated on every chunk of a source rather than only the first. The
                # alternative makes a hit's rank depend on which chunk matched, and a
                # long document's later chunks would rank below its early ones for no
                # reason a reader could see.
                search_document=(
                    sa.func.setweight(
                        sa.func.to_tsvector("simple", document(title)), _WEIGHT_TITLE
                    ).op("||")(
                        sa.func.setweight(
                            sa.func.to_tsvector("simple", document(piece.content)),
                            _WEIGHT_BODY,
                        )
                    )
                ),
                valid_from=now,
                valid_to=None,
            )
            # The hash comparison is not an optimisation for its own sake: a card whose
            # `stage` moved has identical chunk text, and re-running the GIN insert for
            # every such move is the difference between an index that keeps up and one
            # that does not.
            await self._session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_knowledge_chunks_key",
                    set_={
                        "content": stmt.excluded.content,
                        "content_hash": stmt.excluded.content_hash,
                        "token_count": stmt.excluded.token_count,
                        "search_document": stmt.excluded.search_document,
                        "valid_from": stmt.excluded.valid_from,
                        "valid_to": sa.null(),
                    },
                    where=KnowledgeChunk.content_hash != stmt.excluded.content_hash,
                )
            )
        # A source that got shorter leaves chunks behind. They are **closed, not
        # deleted**: a manifest may cite one, and "this part is no longer current" is a
        # better answer than a dangling id.
        await self._session.execute(
            sa.update(KnowledgeChunk)
            .where(
                KnowledgeChunk.source_id == source_id,
                KnowledgeChunk.chunk_key.notin_([piece.key for piece in chunks] or [""]),
                KnowledgeChunk.valid_to.is_(None),
            )
            .values(valid_to=now)
        )

    async def _supersede_older(
        self,
        *,
        project_id: uuid.UUID,
        source_type: str,
        external_id: str,
        keep_id: uuid.UUID,
        keep_updated_at: datetime,
    ) -> int:
        """Mark every earlier version of the same thing as superseded.

        Compares `source_updated_at` rather than `source_version`, and that is the
        decision worth writing down: versions come in three shapes (a counter, a content
        address, a timestamp) and only one of them is ordered. A commit SHA has no
        greater-than.
        """
        table = KnowledgeSource.__table__
        older = (
            (
                await self._session.execute(
                    sa.select(table.c.id)
                    .where(
                        table.c.project_id == project_id,
                        table.c.source_type == source_type,
                        table.c.source_external_id == external_id,
                        table.c.id != keep_id,
                        table.c.source_updated_at < keep_updated_at,
                        table.c.authority.notin_(sorted(HISTORICAL_AUTHORITIES)),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if not older:
            return 0
        await self._session.execute(
            sa.update(KnowledgeSource)
            .where(KnowledgeSource.id.in_(older))
            .values(authority="superseded", active=False)
        )
        # **Their chunks stay open**, and the distinction is load-bearing. `valid_to`
        # answers "is this chunk still the current text *of its source*", which a
        # superseded version's chunk still is — it is an accurate record of what that
        # version said. Closing them here would make `include_history=true` return
        # nothing, which is the one query superseded rows exist for. "Is this source
        # still current" is a different question and `active` answers it.
        await self._session.execute(
            pg_insert(KnowledgeLink)
            .values(
                [
                    {"from_source_id": keep_id, "relation": "supersedes", "to_source_id": old}
                    for old in older
                ]
            )
            .on_conflict_do_nothing()
        )
        return len(older)

    async def _write_links(
        self, project_id: uuid.UUID, source_id: uuid.UUID, links: tuple[tuple[str, str], ...]
    ) -> None:
        if not links:
            return
        for relation, external_id in links:
            target = (
                await self._session.execute(
                    sa.select(KnowledgeSource.id)
                    .where(
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.source_external_id == external_id,
                        KnowledgeSource.active.is_(True),
                    )
                    .order_by(KnowledgeSource.source_updated_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            # A link to something not ingested yet is dropped rather than queued. The
            # reconciler will re-run this source once the other side exists, and a
            # pending-link table would be a second thing to keep consistent for a boost
            # that is worth 0.25 of a score.
            if target is None or target == source_id:
                continue
            await self._session.execute(
                pg_insert(KnowledgeLink)
                .values(from_source_id=source_id, relation=relation, to_source_id=target)
                .on_conflict_do_nothing()
            )

    async def tombstone(
        self, *, project_id: uuid.UUID, source_type: str, external_ids: list[str]
    ) -> int:
        """The original is gone: stop returning it, keep the row.

        Distinct from `active=false`, which means "not in default retrieval" for reasons
        that can be undone (the project switch, an exclusion, a supersede). A tombstone
        says the thing it described no longer exists, and a manifest citing it should be
        able to say exactly that instead of holding a dangling id.
        """
        if not external_ids:
            return 0
        now = now_utc()
        table = KnowledgeSource.__table__
        ids = (
            (
                await self._session.execute(
                    sa.select(table.c.id).where(
                        table.c.project_id == project_id,
                        table.c.source_type == source_type,
                        table.c.source_external_id.in_(external_ids),
                        table.c.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            return 0
        await self._session.execute(
            sa.update(KnowledgeSource)
            .where(KnowledgeSource.id.in_(ids))
            .values(active=False, deleted_at=now)
        )
        await self._session.execute(
            sa.update(KnowledgeChunk)
            .where(KnowledgeChunk.source_id.in_(ids), KnowledgeChunk.valid_to.is_(None))
            .values(valid_to=now)
        )
        return len(ids)
