"""the card's kind, a specification's remaining sections, two run back-references, and document patch proposals

Revision ID: 0039_requirements_agent_driven
Revises: 0038_runner_features
Create Date: 2026-08-14

RQ-02 / `FR-SPEC-002`…`-007` (ADR 0034). **Nothing here rewrites an existing row**,
which is what makes the downgrade clean — unlike `0033` and `0036`, both of which
tightened data already in the table.

The three tables this phase is about (`requirements`, `feature_specs`,
`task_proposals`) were created in `0023`. V2.1 delivered the data model and the human
forms deliberately, so that V2.5 could point an agent at the same API rather than at a
parallel one (`version2.md` §17). This migration adds only what an *agent* driving that
API needs and a person did not.

**`tasks.card_kind` is not a tag** (ADR 0034 §5). Three refusals need a server-side
answer to "what kind of card is this": a clarification card may carry no secret, a
mockup card is refused while the tunnel integration is off, and a proposal may only be
submitted by a decomposition card. Deriving that answer from `required_labels` would
put dispatch routing and card identity in one free-text field, where a typo silently
downgrades a clarification card to an ordinary one — which is the exact case the secret
refusal exists to catch. Deriving it from `requirement_id` fails because accepting a
proposal creates implementation cards that carry one too.

**`feature_specs.sections` is one JSONB column, not nine text columns.** Monstrare's
specification template has twelve sections and this table had five fields; three of the
missing ones are load-bearing (`user_stories` is what a decomposition reads,
`screens` is the upstream of the `ui` gate, `verification_plan` is the upstream of
acceptance criteria). They are read and written with the row and have no independent
query, which is ADR 0027's rule for choosing JSONB — the same rule that decided
`task_proposals.tree`. The **keys** are validated in the service layer; the contents are
not, because a specification with empty sections is legal and what stops it is the
approval gate.

**Both `run_id` columns are `SET NULL`, never `CASCADE`**, matching
`task_messages.run_id` for the same reason: a run's record is reclaimed on a retention
schedule and a specification is not. A draft must not disappear because the run that
wrote it aged out.

Both are also **named, and marked `use_alter` on the model**, because each closes a loop
in the foreign-key graph (`feature_specs` → `task_runs` → `tasks` → `task_proposals` →
`feature_specs`). SQLAlchemy cannot sort a cycle for `create_all` and warns that this may
become an error; the name is what lets it emit the loop-closing edge separately. Nothing
about the migration changes — PostgreSQL was going to accept these either way — but the
metadata stops being unorderable, and the two names say which edges made it cyclic.

**`document_patch_proposals` is insert-only** apart from the decision columns, and it is
deliberately not `task_artifacts`: an artifact is inert data with no decision attached,
while a patch proposal exists to be accepted or rejected by a person, is listed by
"still pending", and would give the artifact table a state machine it was designed not
to have (ADR 0030, ADR 0034 §2).

`ix_tasks_proposal_item` repairs an existing cost rather than serving a new feature.
`RequirementService.accept` already reads every card of a proposal to stay idempotent
per item; at V2.1's scale that was free, and at a decomposition's forty cards it is the
first query anybody notices — as "the accept button spins", which nobody connects to
JSONB.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_requirements_agent_driven"
down_revision: str | None = "0038_runner_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `VARCHAR` plus a service-layer closed set, not a PostgreSQL ENUM — the same choice
# `tasks.stage`, `tasks.source` and `tasks.delivery` already made. Adding a value to an
# ENUM needs `ALTER TYPE`, whose transactional behaviour differs from `ALTER TABLE` and
# gives the migration rehearsal a second thing to verify.
DEFAULT_CARD_KIND = "implementation"


def upgrade() -> None:
    # ① the card's kind
    #
    # A server default rather than a nullable column, so every existing card has an
    # explicit kind the moment this runs. The four dispatch refusals read it, and a NULL
    # would make each of them handle "unknown" separately.
    op.add_column(
        "tasks",
        sa.Column(
            "card_kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_CARD_KIND}'"),
        ),
    )

    # ② the specification sections Monstrare's template has and this table did not
    op.add_column(
        "feature_specs",
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ③ which run wrote this specification version / this proposal
    #
    # Nullable in both cases: a person writing a specification has no run, and V2.1's
    # path is unchanged.
    op.add_column(
        "feature_specs",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_runs.id", ondelete="SET NULL", name="fk_feature_specs_run_id"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "task_proposals",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_runs.id", ondelete="SET NULL", name="fk_task_proposals_run_id"
            ),
            nullable=True,
        ),
    )

    # ④ document patch proposals — the platform renders and records, never applies
    op.create_table(
        "document_patch_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable: a patch proposal may come from an implementation run that noticed a
        # document was wrong, with no requirement behind it.
        sa.Column(
            "requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Numbered per project rather than per requirement, because a proposal may have
        # no requirement and still needs a name a person can say out loud.
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("target_path", sa.String(length=512), nullable=False),
        # TEXT, not JSONB: the platform does not parse a diff. Parsing it is half the
        # distance to applying it.
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "related_task_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "open_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("project_id", "seq", name="uq_document_patch_proposals_project_seq"),
    )
    # Partial: "pending" is the only status that gets listed, and every other row is
    # read one at a time by id.
    op.create_index(
        "ix_document_patch_proposals_pending",
        "document_patch_proposals",
        ["project_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ⑤ the idempotency lookup `accept()` already performs
    op.create_index(
        "ix_tasks_proposal_item",
        "tasks",
        [sa.text("(links ->> 'proposal_item_id')")],
        postgresql_where=sa.text("proposal_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_proposal_item", table_name="tasks")
    op.drop_index("ix_document_patch_proposals_pending", table_name="document_patch_proposals")
    op.drop_table("document_patch_proposals")
    op.drop_column("task_proposals", "run_id")
    op.drop_column("feature_specs", "run_id")
    op.drop_column("feature_specs", "sections")
    op.drop_column("tasks", "card_kind")
