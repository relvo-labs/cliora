"""work views, four card columns, and the index the board always needed

Revision ID: 0043_work_views_and_rank
Revises: 0042_knowledge_tables
Create Date: 2026-08-23

`PX-22` / `FR-WORK-006`, `-008` (ADR 0042). One migration rather than two: unlike
`alpha.3`'s pair, there is no extension here with its own failure mode and ordering —
everything is additive DDL plus a backfill, and splitting it would only add an order to
remember.

**Four new columns on `tasks`, not five.** The upstream plan listed a fifth,
`attention_primary`, "to be created if `PX-24`'s measurement says materialise". ADR 0040
closed that question in the other direction: two of the eight attention levels are
decided by an in-process registry that ADR 0029 §1 forbids storing, so materialising is
not an option for them, and materialising six of eight is a column that is sometimes the
answer. It is not created here and it is not reserved — a reserved column is one somebody
eventually fills.

**`filter_json` is JSONB rather than a child table**, and the reason is worth stating
because every reader asks once:

> The filter is a value object, read and written whole. No query ever asks "which views
> use `priority=urgent`". A child table turns one read into a join and needs a schema
> change for every new filter dimension.

**`blocking_reason` has no CHECK constraint**, unlike almost every other enumeration in
this schema. Two of its values (`no_eligible_runner`, `assigned_runner_offline`) can only
be produced by the runtime phase of `derive_attention`, and the only writer that ever
emits them is this migration's one-off backfill — which, as §5.2 of the plan works out,
**cannot actually produce them either**. Day-to-day writes use the first two values and
`unknown`. A CHECK would turn "this column records what we derived at the time" into
"this column is an authoritative classification", and it is not one. The value set lives
in `services/work/projection.py` with a test.

**The rank backfill orders by `updated_at DESC, id DESC`** — word for word what
`board_cards()` orders by. That is the whole point: a person who upgrades must not find
their board reshuffled. There is a test asserting exactly that equivalence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_work_views_and_rank"
down_revision: str | None = "0042_knowledge_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    _create_work_views()
    _add_task_columns()
    _backfill_ranks()
    _backfill_blocked()
    _seed_default_views()


def _create_work_views() -> None:
    op.create_table(
        "work_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # NULL means a personal view that spans every project the owner can see. The
        # cross-project My Work page is the only thing that writes one.
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # NULL means the view belongs to the project rather than to a person.
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("layout", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "filter_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("group_by", sa.String(length=32), nullable=True),
        sa.Column("subgroup_by", sa.String(length=32), nullable=True),
        sa.Column(
            "order_by_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "visible_fields_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "density",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'comfortable'"),
        ),
        sa.Column(
            "show_subtasks", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("position", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Only a `project` view is ever soft-deleted (ADR 0042 §2): other people hold
        # links to it. A personal view is deleted outright, because nobody else has a
        # link and a graveyard of one person's abandoned views only grows.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # Removes "personal with no owner" and "project with an owner". Both would make
        # the permission check an `if` rather than a join, and the `if` gets a second
        # call site within a phase.
        sa.CheckConstraint(
            "(scope = 'personal' AND owner_user_id IS NOT NULL) OR "
            "(scope = 'project' AND owner_user_id IS NULL AND project_id IS NOT NULL)",
            name="ck_work_views_scope",
        ),
        # `roadmap` is admitted from the first migration although only `board` and
        # `list` are implemented. Same reasoning as `BoardDTO.has_more`: a value added
        # later forces every existing client to handle its absence, while one present
        # from the start is merely unwritten.
        sa.CheckConstraint(
            "layout IN ('board','list','roadmap')", name="ck_work_views_layout"
        ),
        sa.CheckConstraint(
            "density IN ('compact','comfortable')", name="ck_work_views_density"
        ),
    )
    # `COALESCE` to the zero uuid because PostgreSQL's UNIQUE does not compare NULLs —
    # without it, two personal cross-project views could share a name. Partial on
    # `deleted_at IS NULL` so a deleted view's name becomes reusable.
    op.execute(
        "CREATE UNIQUE INDEX uq_work_views_name ON work_views ("
        f"COALESCE(project_id, '{_ZERO_UUID}'::uuid), "
        f"COALESCE(owner_user_id, '{_ZERO_UUID}'::uuid), name) "
        "WHERE deleted_at IS NULL"
    )
    # One default per project. This is what forces "change the default" to be two
    # updates in one transaction, which is the pair the audit entry records — and it is
    # what stops a failed transaction leaving two behind for the UI to choose between.
    op.execute(
        "CREATE UNIQUE INDEX uq_work_views_default ON work_views (project_id) "
        "WHERE is_default AND scope = 'project'"
    )
    op.execute(
        "CREATE INDEX ix_work_views_owner ON work_views (owner_user_id) "
        "WHERE owner_user_id IS NOT NULL"
    )


def _add_task_columns() -> None:
    op.add_column("tasks", sa.Column("rank", sa.String(length=64), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("tasks", sa.Column("blocking_reason", sa.String(length=32), nullable=True))
    op.add_column("tasks", sa.Column("blocking_message", sa.Text(), nullable=True))

    op.execute("CREATE INDEX ix_tasks_project_rank ON tasks (project_id, rank)")
    op.execute(
        "CREATE INDEX ix_tasks_project_blocked ON tasks (project_id) WHERE is_blocked"
    )
    op.execute("CREATE INDEX ix_tasks_project_owner ON tasks (project_id, owner_user_id)")
    # **The only change in this phase that makes an existing query faster.** The V1
    # board is `ORDER BY updated_at DESC` and has never had an index behind it: `0023`
    # created `(project_id, stage)` and `(project_id, user_story_id)`, `0039` added one
    # for proposals, and this pair has never existed.
    op.execute(
        "CREATE INDEX ix_tasks_project_updated ON tasks (project_id, updated_at DESC)"
    )


def _backfill_ranks() -> None:
    """Give every existing card a rank, in the order the board already showed them.

    `ORDER BY updated_at DESC, id DESC` is word for word `board_cards()`'s ordering, and
    `rebalanced_ranks` preserves the order it is given. Together that is the property a
    person upgrading actually cares about: the board looks the same afterwards.
    """
    from app.services.work.ranking import rebalanced_ranks

    connection = op.get_bind()
    projects = [
        row[0] for row in connection.execute(sa.text("SELECT id FROM projects")).all()
    ]
    for project_id in projects:
        rows = connection.execute(
            sa.text(
                "SELECT id FROM tasks WHERE project_id = :project_id "
                "ORDER BY updated_at DESC, id DESC"
            ),
            {"project_id": project_id},
        ).all()
        if not rows:
            continue
        ranks = rebalanced_ranks(len(rows))
        for row, rank in zip(rows, ranks, strict=True):
            connection.execute(
                sa.text("UPDATE tasks SET rank = :rank WHERE id = :id"),
                {"rank": rank, "id": row[0]},
            )
    # Cards created between the ALTER and here cannot exist — one transaction — so any
    # NULL left now would be a bug rather than a race.
    op.execute("ALTER TABLE tasks ALTER COLUMN rank SET NOT NULL")


# The derivation order for `blocking_reason`, and the two entries that are **not** in it.
#
# The upstream plan listed seven steps; steps 3 and 4 ("the last dispatch failed
# eligibility" and "the assigned runner is offline") **cannot run here**. Both need
# `NodeConnectionRegistry`, and `alembic upgrade` is a process without one — there is no
# FastAPI application, and ADR 0029 §1 refuses to keep a stored copy of what it knows.
#
# Implementing them literally would not error; it would go *quiet*. The branch would
# never be true, its cards would fall through to `unknown`, the report would be longer
# than expected and nothing would say why. So they are absent, and the cards they would
# have claimed are honestly reported as `unknown`: the migration genuinely does not know.
_BLOCKED_DERIVATION = """
    UPDATE tasks SET
      is_blocked = true,
      blocking_reason = CASE
        WHEN EXISTS (
          SELECT 1 FROM task_dependencies d
          JOIN tasks blocker ON blocker.id = d.depends_on_task_id
          WHERE d.task_id = tasks.id AND blocker.stage <> 'done'
        ) THEN 'dependency'
        WHEN EXISTS (
          SELECT 1 FROM task_runs r
          WHERE r.task_id = tasks.id AND r.status = 'waiting_for_input'
        ) THEN 'human_input'
        WHEN (
          SELECT v.result FROM verification_reports v
          WHERE v.task_id = tasks.id
          ORDER BY v.reported_at DESC, v.id DESC LIMIT 1
        ) IN ('failed', 'partial') THEN 'verification_failed'
        -- **Some** gate approved but not the whole set: a review was under way and
        -- stopped, which is evidence. `gates = '{}'` is *not* — that is the default
        -- for every card ever created, so treating it as "a gate is unmet" would
        -- classify every blocked card in the deployment as `gate_unmet` and leave the
        -- ambiguous report empty. An empty report is not the same as a report with
        -- nothing in it worth reading.
        WHEN tasks.gates <> '{}'::jsonb THEN 'gate_unmet'
        ELSE 'unknown'
      END
    WHERE stage = 'blocked'
"""


def _backfill_blocked() -> None:
    """`stage='blocked'` becomes `is_blocked` with a derived reason, or `unknown`.

    `blocking_message` stays NULL throughout. **The previous stage is not guessed** —
    and the fact that such a card stays in `ready` is itself reported, because it is a
    guess even though it is the conservative one.
    """
    op.execute(_BLOCKED_DERIVATION)
    # A finished card is not blocked. Nothing above can produce this, but a card that
    # was `blocked` and is now `done` can exist in data written before `0043`, and the
    # read model's projection would disagree with the column.
    op.execute("UPDATE tasks SET is_blocked = false, blocking_reason = NULL WHERE stage = 'done'")


def _seed_default_views() -> None:
    """Five project views for every existing project, through the same function
    `ProjectService.create()` will call for new ones.

    One function, because "the default views only exist on projects created after the
    upgrade" is a split nobody notices until a customer does.
    """
    from app.services.work.views import seed_statements

    connection = op.get_bind()
    for statement, params in seed_statements(project_id=None):
        connection.execute(statement, params)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_updated")
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_owner")
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_blocked")
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_rank")
    op.drop_column("tasks", "blocking_message")
    op.drop_column("tasks", "blocking_reason")
    op.drop_column("tasks", "is_blocked")
    op.drop_column("tasks", "rank")
    # **Reversible, not lossless.** Saved views are product data, and after `plan/26`
    # D117 removed the version flag this is the only rollback path there is. The
    # rollback drill exports `work_views` to JSON first; the drill report says so.
    op.drop_table("work_views")
