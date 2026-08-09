"""projects, project_workspaces, activity_events; terminal_sessions.project_id

Revision ID: 0021_projects
Revises: 0020_node_file_upload
Create Date: 2026-08-08

PJ-02 (FR-PROJECT-001/002/004, ADR 0027, plan/16/02-…md). The V2 project layer's
whole data footprint: three new tables and one nullable column. No existing column
changes type, nullability or default.

Three things are deliberately *not* here, and each one is a decision rather than an
omission:

* **No `project_members` table.** V2.0 authorizes with the existing three roles plus
  `projects.owner_user_id`, exactly as node access already works. Project-level
  membership is a new table plus one authorization layer that would not change any
  column decided here, so building it now is only paying early (ADR 0027 sec 4).
* **No `default_node_id` / `default_runtime` on `projects`.** Nothing reads them in
  this phase; the New Session dialog prefills from the `is_primary` binding, which
  carries a path as well as a node and is therefore strictly more useful.
* **No retention on `activity_events`.** ADR 0024's W2 asks "who cleans this up".
  The answer here is nobody: it is product content, not diagnostics, and it lives
  as long as the project. That is the opposite of the answer `run_logs` gets in
  V2.2, and confusing the two is the easiest mistake in V2 (ADR 0027 sec 7).

`terminal_sessions.task_id` waits for V2.1's `0023`, when `tasks` exists and it can
be a real foreign key. Adding a bare UUID column now would only create a period in
which it points at nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_projects"
down_revision: str | None = "0020_node_file_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        # Stable for the lifetime of the project: V2.1 builds card references
        # (TASK-123) on it and V2.3 namespaces secrets by it, so a mutable slug
        # would strand both. `name` is the mutable one.
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        # RESTRICT, not CASCADE: someone leaving must not take a project and its
        # history with them. There is no delete-user endpoint today, so this
        # constraint blocks nobody now — it is a sentence for the day one is written.
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    # No index on `owner_user_id` on purpose. The unique constraint on `slug`
    # already carries one, and "projects I own" is a sequential scan over a table
    # whose rows are typed in by hand. Add one when a measurement asks for it.

    op.create_table(
        "project_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # CASCADE is a safety net, not the normal path: node removal is a *soft*
        # delete (ADR 0011), so this never fires in ordinary operation. The service
        # filters `nodes.deleted_at IS NULL` instead — the same choice, for the same
        # reason, that 0011_workspace_favorites.py records. A pleasant consequence:
        # re-enabling a node removed by mistake brings its bindings back.
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # String(4096) to match terminal_sessions.workspace and
        # workspace_favorites.path. Three stores of the same kind of value with
        # different types would eventually meet in a join.
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Makes binding idempotent: a second POST for the same triple returns the
        # existing row instead of a duplicate the user would have to unbind twice.
        sa.UniqueConstraint(
            "project_id", "node_id", "path", name="uq_project_workspaces_project_node_path"
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_workspaces_project "
        "ON project_workspaces (project_id);"
    )
    # At most one primary binding per project, enforced where concurrency cannot
    # defeat it. 0013_shell_session_parent uses the same device for "one live shell
    # per session"; the condition here is simpler, so unlike that one it needs no
    # test pinning it to a status list.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_project_workspaces_one_primary "
        "ON project_workspaces (project_id) WHERE is_primary;"
    )

    op.create_table(
        "activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # No foreign keys on the next three, matching audit_logs. `task_id` points at
        # a table V2.1 creates. The other two are deliberate: a timeline is history,
        # and a hard-deleted session must not blank or remove the row that says it
        # once ran.
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # `id DESC` is the tiebreaker, not decoration: keyset pagination over
    # `occurred_at` alone gives an unstable order for rows written in the same
    # millisecond, which drops or repeats entries across pages. The dashboard's
    # recent-activity query orders by (created_at DESC, id DESC) for this reason.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activity_events_project_occurred_at "
        "ON activity_events (project_id, occurred_at DESC, id DESC);"
    )

    # Nullable, and permanently so: an ad-hoc session is part of the product, not a
    # transitional state (ADR 0027 sec 3). Nothing is backfilled — every existing
    # session genuinely belongs to no project.
    op.add_column(
        "terminal_sessions",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_terminal_sessions_project_id",
        "terminal_sessions",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial: in a deployment with the flag off this column is entirely NULL, and a
    # partial index costs neither space nor write time there.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminal_sessions_project "
        "ON terminal_sessions (project_id) WHERE project_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_terminal_sessions_project;")
    op.drop_constraint("fk_terminal_sessions_project_id", "terminal_sessions", type_="foreignkey")
    op.drop_column("terminal_sessions", "project_id")

    op.execute("DROP INDEX IF EXISTS ix_activity_events_project_occurred_at;")
    op.drop_table("activity_events")

    op.execute("DROP INDEX IF EXISTS ux_project_workspaces_one_primary;")
    op.execute("DROP INDEX IF EXISTS ix_project_workspaces_project;")
    op.drop_table("project_workspaces")

    op.drop_table("projects")
