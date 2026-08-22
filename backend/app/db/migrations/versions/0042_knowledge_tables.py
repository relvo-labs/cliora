"""six tables that remember what a project already decided

Revision ID: 0042_knowledge_tables
Revises: 0041_knowledge_extension
Create Date: 2026-08-22

`KN-02` / `FR-KNOW-001`…`-011` (ADR 0038). Entirely additive: six new tables, no
existing column changes type, nullability or default.

**There is no backfill here, and that is a design decision rather than an omission**
(ADR 0038 §7). `knowledge_enabled` defaults to false, so at the moment this runs no
project has a memory to fill. Enabling one is what starts ingestion, and the
reconciler's watermark queries — which exist anyway, because the event path can miss —
are what fill it. One filling routine is more correct than two, and a backfill written
here would be a second copy of logic that has to agree with the first forever.

Three shapes in here are worth explaining, because each looks like it could have been
simpler:

**`project_id` on `knowledge_chunks` and `context_packs` is denormalised on purpose.**
Both could be joined through `source_id` / `run_id`. The column buys a shorter proof:
every table can be asserted independently in an isolation test, and
`GATE-KN-PROJECT-SCOPED` can require a `project_id` predicate on every select — a gate
that is only *writable* because the column is on every table.

**`search_document` is `NOT NULL` although nothing in the database computes it.** It is
built in Python from one tokenizer (ADR 0038 §4; `to_tsvector` is `STABLE`, so
PostgreSQL refuses it in a generated column, and a trigger would split "how is the
index computed" across two languages). The constraint means any path that inserts a
chunk without going through `services/knowledge/` fails loudly. That is the intent.

**`uq_knowledge_jobs_pending` is a partial unique index, not a table constraint.** It
is what makes "this card was edited five times in one second" one pending job instead
of five, and it works because a job is an *entity key* rather than content (ADR 0038
§3.2): the worker re-reads the entity, so collapsing duplicates loses nothing.
PostgreSQL has no partial `UNIQUE` constraint, only a partial unique index, so the
`ON CONFLICT` in the enqueue path names the index's columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_knowledge_tables"
down_revision: str | None = "0041_knowledge_extension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `VARCHAR` plus a CHECK plus a closed set in the service layer, matching `tasks.stage`,
# `task_questions.state` and every other enumeration in this schema. The CHECK is here
# for the reason `ActivityService.record` refuses an unknown kind: a typo would
# otherwise create a row that no filter can ever find.
_SOURCE_TYPES = (
    "policy",
    "ticket",
    "conversation",
    "decision",
    "artifact",
    "verification",
    "repo_doc",
    "activity",
)
_AUTHORITIES = (
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
_RELATIONS = ("supersedes", "derived_from", "references", "verifies", "delivers", "blocks")
_JOB_STATES = ("pending", "running", "done", "failed", "dead")
_PIN_MODES = ("pin", "exclude")


def _in(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def upgrade() -> None:
    # ① sources — the identity is the four-column unique key, and everything else on
    #    the row is provenance for it.
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_external_id", sa.String(length=255), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        # 13 characters at the longest (`authoritative`). Checked rather than assumed.
        sa.Column("authority", sa.String(length=16), nullable=False),
        sa.Column(
            "visibility", sa.String(length=16), nullable=False, server_default=sa.text("'project'")
        ),
        sa.Column("checksum", sa.CHAR(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("authored_by_type", sa.String(length=16), nullable=True),
        sa.Column("authored_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # The comparison column for the idempotent upsert (ADR 0038 §3.3). Distinct from
        # `occurred_at`: a conversation message that happened yesterday can be ingested
        # today, and it is *this* that decides whether an arriving row is newer.
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Read by the Sources panel for five source families at once. Derived, and
        # stored anyway: `count(*)` over `knowledge_chunks` five times a page load is
        # five sequential scans of the biggest table in the schema.
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "supersedes_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Two different facts, both of which keep the row (ADR 0038 §6): `active=false`
        # is "not in default retrieval", `deleted_at` is "the original is gone". A
        # manifest that can say "this source has since been deleted" beats one holding a
        # dangling id.
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("source_type", _SOURCE_TYPES), name="source_type"),
        sa.CheckConstraint(_in("authority", _AUTHORITIES), name="authority"),
        sa.UniqueConstraint(
            "project_id",
            "source_type",
            "source_external_id",
            "source_version",
            name="uq_knowledge_sources_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_sources_project_active",
        "knowledge_sources",
        ["project_id", "source_type"],
        postgresql_where=sa.text("active AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_knowledge_sources_recent",
        "knowledge_sources",
        ["project_id", sa.text("ingested_at DESC")],
    )

    # ② chunks
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # An ordinal, not a content hash. A hash would make "a sentence was added at the
        # top" mean every chunk is new, and the whole GIN index gets rebuilt for a typo.
        sa.Column("chunk_key", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        # Reserved by D40 and always NULL in alpha.3. The column exists so that the day
        # a vector channel is added is a data migration and not a schema argument.
        sa.Column("embedding_ref", sa.String(length=128), nullable=True),
        sa.Column("search_document", postgresql.TSVECTOR(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id", "chunk_key", name="uq_knowledge_chunks_key"),
    )
    op.create_index(
        "ix_knowledge_chunks_fts",
        "knowledge_chunks",
        ["search_document"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_knowledge_chunks_trgm",
        "knowledge_chunks",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    # Neither GIN index contains `project_id`, so without this the isolation predicate
    # becomes a heap filter over whatever the GIN returned — twenty times the work when
    # one project holds five per cent of the rows.
    op.create_index(
        "ix_knowledge_chunks_live",
        "knowledge_chunks",
        ["project_id", "source_id"],
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    # ③ links — a table rather than JSONB because the graph boost queries it in both
    #    directions, and only one of those is served by the primary key.
    op.create_table(
        "knowledge_links",
        sa.Column(
            "from_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("relation", sa.String(length=24), primary_key=True),
        sa.Column(
            "to_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.CheckConstraint(_in("relation", _RELATIONS), name="relation"),
    )
    op.create_index("ix_knowledge_links_to", "knowledge_links", ["to_source_id", "relation"])

    # ④ jobs
    op.create_table(
        "knowledge_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        # Backoff. Absent from the upstream DDL; without it a failing job is retried as
        # fast as the loop spins.
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        # How a job that was `running` when Central was killed is recognised. The
        # recovery deliberately does not count an attempt: that was not a failed try,
        # it was a try with no conclusion.
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(_in("state", _JOB_STATES), name="state"),
        sa.CheckConstraint(_in("source_type", _SOURCE_TYPES), name="source_type"),
    )
    op.create_index(
        "uq_knowledge_jobs_pending",
        "knowledge_jobs",
        ["project_id", "source_type", "external_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index(
        "ix_knowledge_jobs_claimable",
        "knowledge_jobs",
        ["created_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    # Scraped every fifteen seconds for "how old is the oldest dead letter", which is
    # the one number that says whether anybody is reading the health panel.
    op.create_index(
        "ix_knowledge_jobs_dead",
        "knowledge_jobs",
        ["dead_lettered_at"],
        postgresql_where=sa.text("state = 'dead'"),
    )
    op.create_index(
        "ix_knowledge_jobs_running",
        "knowledge_jobs",
        ["started_at"],
        postgresql_where=sa.text("state = 'running'"),
    )

    # ⑤ pins
    op.create_table(
        "task_knowledge_pins",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mode", sa.String(length=8), nullable=False),
        # SET NULL, so a pin outlives the person who made it. A pin is the project's
        # decision about a card, not that person's preference.
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(_in("mode", _PIN_MODES), name="mode"),
    )

    # ⑥ context packs — CASCADE from the run (ADR 0038 §6): "what this turn read" is a
    #    diagnostic and shares the run's lifetime. The citation inside the agent's
    #    message is the durable record, and messages never expire.
    op.create_table(
        "context_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_seq", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Ids and metadata only, never content: a second copy of sensitive text would
        # sit outside every retention rule that governs the first (ADR 0038 §6).
        sa.Column("source_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("omitted_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    # **No unique key on (run_id, turn_seq).** Two fetches reading different content is
    # exactly the thing that has to stay visible, so each fetch is its own row.
    op.create_index("ix_context_packs_run", "context_packs", ["run_id", sa.text("built_at DESC")])
    op.create_index("ix_context_packs_task", "context_packs", ["task_id", sa.text("built_at DESC")])


def downgrade() -> None:
    op.drop_table("context_packs")
    op.drop_table("task_knowledge_pins")
    op.drop_table("knowledge_jobs")
    op.drop_table("knowledge_links")
    # Before `knowledge_sources`: the trigram index here is the dependency that would
    # make `0041`'s DROP EXTENSION fail.
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_sources")
