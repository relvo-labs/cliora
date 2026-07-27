"""node_metric_samples: persisted heartbeat resource history

Revision ID: 0009_node_metric_samples
Revises: 0008_audit_query_indexes
Create Date: 2026-07-25

P4-06. `node.heartbeat` has carried a `resources` sample since P1, but Central
only ever kept it in the connection registry's memory. That makes it impossible
to answer anything historical — "was this node healthy overnight?", "when did
memory start climbing?" — and a Central restart erases even the current values.

Every measurement column is nullable: the daemon collects each field best-effort
(`internal/systeminfo/resources.go`), and a field it could not read must land as
NULL. Storing 0 instead would make an unreadable disk look like an empty one, and
any fleet average over it would be quietly wrong.

The index matches the only query shapes there are: the newest sample per node
(Dashboard) and a node's samples over a range (runbook diagnosis). Retention is
by `sampled_at` via `app/retention.py`, which already knows about this table.

Downgrade drops the table; the samples are derived data, re-accumulated from
heartbeats within one interval.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_node_metric_samples"
down_revision: str | None = "0008_audit_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "node_metric_samples",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Uuid(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_usage", sa.Float(), nullable=True),
        sa.Column("memory_usage", sa.Float(), nullable=True),
        sa.Column("load_average", sa.Float(), nullable=True),
        sa.Column("disk_usage", sa.Float(), nullable=True),
        sa.Column("daemon_uptime", sa.Float(), nullable=True),
        sa.Column("active_sessions", sa.Integer(), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_node_metric_samples_node_sampled_at "
        "ON node_metric_samples (node_id, sampled_at DESC);"
    )
    # Retention prunes by time across every node, which the composite index above
    # cannot serve (its leading column is node_id).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_node_metric_samples_sampled_at "
        "ON node_metric_samples (sampled_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_node_metric_samples_sampled_at;")
    op.execute("DROP INDEX IF EXISTS ix_node_metric_samples_node_sampled_at;")
    op.drop_table("node_metric_samples")
