"""nodes: daemon update state columns

Revision ID: 0010_node_update_state
Revises: 0009_node_metric_samples
Create Date: 2026-07-25

P4-10. `nodes.daemon_version` records what a node *is* running; nothing recorded
what happened the last time it was asked to change. After a fleet upgrade the
operational question is "which nodes failed, and at which stage" — so this is
four explicit columns rather than keys inside the `metadata` JSONB: the failure
question must be an indexable query and a sortable column in the node list, not a
JSON path scan (ADR 0017).

`update_status` is indexed because that is the column the "show me the failures"
filter uses. The other three are read alongside a row that has already been
found, so they need no index of their own.

All four are nullable and start NULL, which reads as "never asked to update" —
distinct from `succeeded` (asked, and it worked). Existing rows therefore need no
backfill, and downgrade drops the columns without touching anything else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_node_update_state"
down_revision: str | None = "0009_node_metric_samples"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("update_status", sa.String(16)),
    ("update_target_version", sa.String(64)),
    ("update_last_result", sa.String(64)),
    ("update_updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column("nodes", sa.Column(name, column_type, nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_nodes_update_status ON nodes (update_status);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_update_status;")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("nodes", name)
