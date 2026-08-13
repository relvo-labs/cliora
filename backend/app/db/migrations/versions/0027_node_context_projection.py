"""nodes.context_projection: whether this node's agentd can receive a context pack

Revision ID: 0027_node_context_projection
Revises: 0026_seed_process_definition
Create Date: 2026-08-09

TK-07 / FR-TASK-007.AC-05 (ADR 0028 sec 5). One nullable-by-default boolean, reported
by the daemon at registration exactly as `image_upload` and `file_upload` already are.

**Default false, and nothing is backfilled.** Every node registered before this
migration genuinely cannot receive a projection: it is running agentd 0.7.0 or older,
where the message type does not exist. It re-registers on its next connection and
tells us the truth then.

Indexed for the same reason the other two capability columns are: "which nodes cannot
receive task context yet" is a fleet-level question an operator asks once per upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_node_context_projection"
down_revision: str | None = "0026_seed_process_definition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "context_projection", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nodes_context_projection "
        "ON nodes (context_projection);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_context_projection;")
    op.drop_column("nodes", "context_projection")
