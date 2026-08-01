"""nodes.privileged_terminal + node_runtimes.sandbox_bypass: the node's execution posture

Revision ID: 0017_node_privileged_posture
Revises: 0016_seed_tunnel_actions
Create Date: 2026-08-01

PV-07 / ADR 0023. Two facts a node now reports about itself: its system terminal can
reach root through sudo, and a given runtime is launched with its sandbox and approval
prompts disabled. Both are report-only — nothing in the platform writes them except a
`node.register` / `node.runtime_status` announce from the machine itself.

Explicit columns rather than keys inside `nodes.metadata`, on the same judgement as
`update_status` (see models.py): "which of my nodes can reach root from a browser
terminal" is a fleet-level security question, so it has to be indexable. A key inside
JSONB is not something anyone will index, and this is the query a security review
starts from — hence the index on privileged_terminal.

`server_default=false` is the load-bearing default: a node that has not reported yet
reads as unprivileged. Absent must never mean privileged — the console would then
describe a posture nobody claimed. Existing rows are correct without a backfill,
because every daemon re-registers on its next connection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_node_privileged_posture"
down_revision: str | None = "0016_seed_tunnel_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "privileged_terminal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_nodes_privileged_terminal",
        "nodes",
        ["privileged_terminal"],
    )
    op.add_column(
        "node_runtimes",
        sa.Column(
            "sandbox_bypass",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("node_runtimes", "sandbox_bypass")
    op.drop_index("ix_nodes_privileged_terminal", table_name="nodes")
    op.drop_column("nodes", "privileged_terminal")
