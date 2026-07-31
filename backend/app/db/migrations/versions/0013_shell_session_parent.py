"""terminal_sessions.parent_session_id: bind a shell session to its CLI session

Revision ID: 0013_shell_session_parent
Revises: 0012_seed_terminal_shell
Create Date: 2026-07-31

WT-07 / FR-SHELL-001.AC-04 + AC-08 (ADR 0021). A system-terminal session is not an
independent unit of work: it belongs to exactly one CLI session, dies with it, and is
hidden from the Sessions list because clicking it would open a workspace with no CLI.

Nullable and self-referential: a CLI session's column stays NULL, so no backfill is
needed and nothing about existing rows changes.

The partial unique index is the database-level half of "one terminal per workspace".
It is filtered on *live* statuses rather than being a plain unique constraint, because
closing a shell and opening another one is normal; two live ones at once is not.

The status list must equal `ACTIVE_STATES` in `app/repositories/sessions.py` (which is
the complement of `TERMINAL_STATES`), including `terminating`. Leaving `terminating`
out would let a second shell be inserted during the stop relay — exactly the window
where a user who clicked twice would produce two live shells on the node.
`test_shell_index_states_match_active_states` pins the two lists together.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_shell_session_parent"
down_revision: str | None = "0012_seed_terminal_shell"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "('starting', 'running', 'disconnected', 'terminating')"


def upgrade() -> None:
    op.add_column(
        "terminal_sessions",
        sa.Column(
            "parent_session_id",
            sa.Uuid(),
            sa.ForeignKey("terminal_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # "Every live child of this parent" — the lookup the terminate cascade and the
    # already-open check both make.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminal_sessions_parent "
        "ON terminal_sessions (parent_session_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_terminal_sessions_live_shell "
        "ON terminal_sessions (parent_session_id) "
        f"WHERE runtime = 'shell' AND status IN {_LIVE};"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_terminal_sessions_live_shell;")
    op.execute("DROP INDEX IF EXISTS ix_terminal_sessions_parent;")
    # Drop the parentage before the column so a downgrade over data with live shell
    # sessions leaves rows that are merely orphaned, not rows pointing at a column
    # that no longer exists.
    op.execute("UPDATE terminal_sessions SET parent_session_id = NULL;")
    op.drop_column("terminal_sessions", "parent_session_id")
