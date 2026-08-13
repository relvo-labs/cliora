"""the task layer: process definitions, epics, user stories, tasks, dependencies,
requirements, specs and proposals; plus three additive columns

Revision ID: 0023_task_board
Revises: 0022_seed_project_actions
Create Date: 2026-08-09

TK-02 (FR-TASK-001…006, ADR 0028, plan/17/02-…md). Eight new tables and three new
columns on tables that already exist. No existing column changes type, nullability
or default.

Four decisions are visible in the DDL rather than only in the plan, because each of
them is the kind of thing that gets "simplified" later by someone who did not know
why it was written this way:

* **`projects.next_card_seq`** is a counter taken with one `UPDATE … RETURNING`,
  which takes the row lock. `count(*) + 1` collides when two browser tabs create a
  card at the same moment, and `card_ref` goes on to name a branch (V2.3) and a pull
  request (V2.4) — a reference that collided once is discovered three phases later.
  Epics, stories and tasks share the counter, so **numbers skip**; the reference is
  an identifier, not a count, and three counters would mean three things to lock.
* **`activity_events.actor_kind`** exists because `actor_user_id IS NULL` already
  means "the system did this", and `services/activity.py::redact_actors` produces
  the same NULL for a user event a reader may not see. Adding a third meaning
  ("an agent did this") to the same NULL would make all three unreadable.
* **`tasks.gates` stores `{approved_by, approved_at}` per gate, not a boolean.**
  "An agent's output is not an approval" then has a place to live in the data: that
  cell always holds a human's user id (ADR 0028 sec 1).
* **`assigned_runner_id` and `repository_id` carry no foreign key yet.** Their
  targets arrive in V2.2 and V2.3. `activity_events.task_id` set this precedent in
  0021 for the same reason; each phase adds its own constraint when the table lands.

`acceptance_criteria`, `readiness` and `links` are JSONB rather than tables, by the
rule ADR 0027 already used: something read and written with its parent, with no
independent query, is a column. A table would turn "edit one acceptance criterion"
into a multi-row upsert plus orphan cleanup.

`task_sessions` from the upstream plan is **not** created. "Which sessions did this
card have" is one indexed lookup on `terminal_sessions.task_id`; a session cannot
belong to two cards, so the join table has no semantics to carry.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_task_board"
down_revision: str | None = "0022_seed_project_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGES = ("backlog", "blocked", "ready", "implementing", "verify", "done")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # --- process definitions -------------------------------------------------
    # One global row in V2.1 (`key = 'default'`), not overridable per project
    # (ADR 0028 sec 1). `key` exists anyway because V2.4's minimal override needs it,
    # and adding it later would mean revisiting every read site.
    op.create_table(
        "process_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        # A *content* version, not a serial: it becomes the directory name under
        # `.cliora/process/<version>/`, so it has to change when the content changes
        # and stay put when it does not (plan/17/05-…md §4.2).
        sa.Column("version", sa.String(length=32), nullable=False),
        # Provenance. The lanes, the readiness items and the gates are Monstrare's
        # (MIT); internalising them does not make them ours.
        sa.Column("source", sa.String(length=64), nullable=False, server_default="monstrare"),
        sa.Column("lanes", postgresql.JSONB(), nullable=False),
        sa.Column("readiness", postgresql.JSONB(), nullable=False),
        sa.Column("gates", postgresql.JSONB(), nullable=False),
        sa.Column(
            "templates", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("key", name="uq_process_definitions_key"),
    )

    # --- epics / user stories ------------------------------------------------
    op.create_table(
        "epics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_ref", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "card_ref", name="uq_epics_project_card_ref"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_epics_project ON epics (project_id);")

    op.create_table(
        "user_stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL, not CASCADE: an archived or mistakenly removed epic drops its
        # stories into the unclassified bucket rather than taking them with it. The
        # bucket is Monstrare's semantics and the reason it exists (D4).
        sa.Column(
            "epic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("epics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("card_ref", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "card_ref", name="uq_user_stories_project_card_ref"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_stories_project ON user_stories (project_id);")

    # --- requirements / specs / proposals (TK-05, the manual flow) ------------
    # These land in the same migration as the board rather than in one of their own,
    # because a task carries a foreign key back to them: splitting would mean adding
    # the constraint in a second revision for no gain.
    op.create_table(
        "requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_ref", sa.String(length=32), nullable=False),
        # The whole intake surface: one vague sentence. Deliberately not a set of
        # fields — asking for ten of them up front is what stops the flow being used
        # at all (ADR 0028, research/02/09 sec 4.5b).
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="intake"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "card_ref", name="uq_requirements_project_card_ref"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_requirements_project ON requirements (project_id);")

    op.create_table(
        "feature_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # A version row: INSERT only, never UPDATE. Comparing version N with N-1 is
        # the point of the review screen, and a spec that was quietly edited is the
        # thing most worth being able to see.
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("non_goals", sa.Text(), nullable=True),
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # `[{id, question, answer, resolved_as}]`. An unresolved entry refuses
        # approval at the API, not just in the UI (FR-TASK-005.AC-03).
        sa.Column(
            "open_questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Present from day one even though V2.1 only ever writes 'user': V2.5 writes
        # 'agent' through the same API, and "who wrote this spec" is a question worth
        # being able to answer before then.
        sa.Column("authored_by_kind", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column(
            "authored_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("requirement_id", "seq", name="uq_feature_specs_requirement_seq"),
    )

    op.create_table(
        "task_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feature_specs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        # The three-level tree as proposed. Not real cards: "an agent's output is not
        # an approval" applies to decomposition too, so acceptance is what creates
        # rows in `tasks` (ADR 0028, D28).
        sa.Column("tree", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("requirement_id", "seq", name="uq_task_proposals_requirement_seq"),
    )

    # --- tasks ---------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "epic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("epics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_story_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_stories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("card_ref", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("non_goals", sa.Text(), nullable=True),
        # CHECK rather than a PostgreSQL enum, matching `terminal_sessions.status`:
        # V2.4 may enable or disable lanes, and `ALTER TYPE` is the one schema change
        # that cannot be rolled back inside a transaction.
        sa.Column("stage", sa.String(length=16), nullable=False, server_default="backlog"),
        sa.Column("risk", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # No foreign key: `agent_runners` arrives in V2.2, `project_repositories` in
        # V2.3. Each phase adds its own constraint (see the module docstring).
        sa.Column("assigned_runner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "required_labels",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "readiness", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # `{gate_key: {approved_by, approved_at}}` — never a boolean (ADR 0028 sec 1).
        sa.Column(
            "gates", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "links", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # Optimistic lock. An integer works here precisely because the platform is
        # the only writer — the file-backed design this replaced needed a content
        # hash for the same job (research/02/01 D6).
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        # --- execution settings: declared in V2.1, inert until V2.3/V2.4 ---------
        sa.Column("source", sa.String(length=16), nullable=False, server_default="repo"),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_branch", sa.String(length=255), nullable=True),
        sa.Column("delivery", sa.String(length=16), nullable=False, server_default="pull_request"),
        sa.Column("target_branch", sa.String(length=255), nullable=True),
        sa.Column("existing_pr_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "required_secrets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # --- provenance ---------------------------------------------------------
        sa.Column(
            "requirement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "card_ref", name="uq_tasks_project_card_ref"),
        sa.CheckConstraint(
            "stage IN (" + ", ".join(f"'{stage}'" for stage in STAGES) + ")",
            name="ck_tasks_stage",
        ),
        sa.CheckConstraint("source IN ('none', 'repo', 'existing_branch')", name="ck_tasks_source"),
        sa.CheckConstraint(
            "delivery IN ('none', 'artifact', 'branch', 'pull_request', 'existing_pr')",
            name="ck_tasks_delivery",
        ),
    )
    # Two indexes, for the two query shapes this phase has: the board groups by
    # stage, the roadmap groups by story. There is no third, because there is no
    # third query — one added speculatively is a write cost with no reader.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_project_stage "
        "ON tasks (project_id, stage, updated_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_project_story ON tasks (project_id, user_story_id);"
    )

    op.create_table(
        "task_dependencies",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # The one-node cycle, caught by the database rather than by a service that
        # could be bypassed. Longer cycles need a graph walk and live in the service
        # (plan/17/03-…md §3.4) — a trigger would put the refusal too far from the
        # caller for the error to name the path.
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_self"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_dependencies_depends_on "
        "ON task_dependencies (depends_on_task_id);"
    )

    # --- additive columns on existing tables ---------------------------------
    # Promised by 0021's docstring: "`terminal_sessions.task_id` waits for V2.1's
    # 0023, when `tasks` exists and it can be a real foreign key."
    op.add_column(
        "terminal_sessions",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_terminal_sessions_task_id",
        "terminal_sessions",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminal_sessions_task "
        "ON terminal_sessions (task_id) WHERE task_id IS NOT NULL;"
    )

    op.add_column(
        "projects",
        sa.Column("next_card_seq", sa.Integer(), nullable=False, server_default="1"),
    )

    # 'user' as the default is not a placeholder: every row written before this
    # migration really was a person's action, so nothing needs backfilling.
    op.add_column(
        "activity_events",
        sa.Column("actor_kind", sa.String(length=16), nullable=False, server_default="user"),
    )


def downgrade() -> None:
    op.drop_column("activity_events", "actor_kind")
    op.drop_column("projects", "next_card_seq")

    op.execute("DROP INDEX IF EXISTS ix_terminal_sessions_task;")
    op.drop_constraint("fk_terminal_sessions_task_id", "terminal_sessions", type_="foreignkey")
    op.drop_column("terminal_sessions", "task_id")

    op.execute("DROP INDEX IF EXISTS ix_task_dependencies_depends_on;")
    op.drop_table("task_dependencies")
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_story;")
    op.execute("DROP INDEX IF EXISTS ix_tasks_project_stage;")
    op.drop_table("tasks")
    op.drop_table("task_proposals")
    op.drop_table("feature_specs")
    op.execute("DROP INDEX IF EXISTS ix_requirements_project;")
    op.drop_table("requirements")
    op.execute("DROP INDEX IF EXISTS ix_user_stories_project;")
    op.drop_table("user_stories")
    op.execute("DROP INDEX IF EXISTS ix_epics_project;")
    op.drop_table("epics")
    op.drop_table("process_definitions")
