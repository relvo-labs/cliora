"""workspace_favorites: a user's saved workspace paths per node

Revision ID: 0011_workspace_favorites
Revises: 0010_node_update_state
Create Date: 2026-07-25

P4-13 (FR-WORKSPACE-005, PRD §12.8). The last data-plane addition of the MVP.

"Recently used workspaces" (FR-WORKSPACE-004) deliberately gets **no table**: it is
derivable from `terminal_sessions` (`user_id`, `node_id`, `workspace`, `created_at`),
which are already recorded. A second store for the same facts would only be able to
disagree with the first.

Both foreign keys cascade. A deleted user's favourites are meaningless, and a hard-
deleted node's paths refer to a machine that no longer exists. Note that node *removal*
is a soft delete (ADR 0011), so the cascade is a safety net rather than the normal path
— the service filters soft-deleted nodes out of the listing instead.

The unique constraint is what makes favouriting idempotent: a second POST for the same
`(user, node, path)` returns the existing row rather than creating a duplicate the user
would then have to delete twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_workspace_favorites"
down_revision: str | None = "0010_node_update_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_favorites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "node_id", sa.Uuid(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("path", sa.String(4096), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "node_id", "path", name="uq_workspace_favorites_user_node_path"),
    )
    # The only query shape there is: one user's favourites, newest first.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspace_favorites_user_created_at "
        "ON workspace_favorites (user_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workspace_favorites_user_created_at;")
    op.drop_table("workspace_favorites")
