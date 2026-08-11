"""nodes.agent_runner: whether this node's agentd can run agent work

Revision ID: 0031_node_agent_runner
Revises: 0030_seed_agent_actions
Create Date: 2026-08-11

AR-03 / FR-AGENT-001.AC-05 (ADR 0029 sec 7). One boolean, reported by the daemon at
registration exactly as `context_projection`, `image_upload` and `file_upload` already
are — the fourth instance of the same shape, on purpose.

**Default false, and nothing is backfilled.** Every node registered before this
migration genuinely cannot run agent work: it is running agentd 0.8.0 or older, where
the runner mode does not exist. It re-registers on its next connection and tells us
the truth then. The console shows those nodes as "needs 0.9.0" rather than failing.

Indexed for the same reason as the other three capability columns: "which nodes cannot
take agent work yet" is a fleet-level question an operator asks once per upgrade.

Separate from 0029 because the domains differ: 0029 creates the phase's own tables,
this alters a table that predates it. Rolling one back must not take the other with
it, and this downgrade must really drop the column — leaving an orphan on an existing
table is what makes the next phase's baseline diff permanently unexplainable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_node_agent_runner"
down_revision: str | None = "0030_seed_agent_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("agent_runner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_nodes_agent_runner ON nodes (agent_runner);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_agent_runner;")
    op.drop_column("nodes", "agent_runner")
