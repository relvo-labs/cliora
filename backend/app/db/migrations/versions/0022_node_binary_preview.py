"""nodes.binary_preview and nodes.last_registration_at (read-only binary preview)

Revision ID: 0022_node_binary_preview
Revises: 0021_node_file_download
Create Date: 2026-09-27

BP-04 / ADR 0029 §9. Two report-only columns, neither a wire or contract change.

`binary_preview` is for display and fleet queries ("which of my nodes show images and
PDFs to Viewers"). It is indexed on the same judgement as 0017, 0018 and 0020, and
`server_default=false` means a node that has not re-registered reads as *not*
previewing. It is deliberately NOT the gate: a preview request is gated on the live
connection's registration, held in the connection registry, so a daemon that
reconnects downgraded is refused at once rather than after the next write.

`last_registration_at` is set only when Central accepts a node.register. It exists
for the Central rollback drill: `daemon_version` is unchanged by a restart and
`last_seen_at` moves on every heartbeat, so neither proves that a registration was
accepted. Nullable, no backfill — NULL is the honest value until the next register.

**Numbering.** PR #71 merged first, so this migration revises 0021.

`downgrade()` removes everything `upgrade()` adds — index, then both columns — and
loses no user data: both columns are reports the next register rewrites
(test_migration_0022_roundtrip).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_node_binary_preview"
down_revision: str | None = "0021_node_file_download"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("binary_preview", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_nodes_binary_preview", "nodes", ["binary_preview"])
    op.add_column(
        "nodes",
        sa.Column("last_registration_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "last_registration_at")
    op.drop_index("ix_nodes_binary_preview", table_name="nodes")
    op.drop_column("nodes", "binary_preview")
