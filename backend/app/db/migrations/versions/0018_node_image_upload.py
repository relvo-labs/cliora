"""nodes.image_upload: whether this node accepts image drop into a workspace

Revision ID: 0018_node_image_upload
Revises: 0017_node_privileged_posture
Create Date: 2026-08-01

WF-07 / ADR 0024. One more fact a node reports about itself: the platform may write
an image into its session workspaces. Report-only, like `privileged_terminal` before
it — nothing in the platform sets this except a `node.register` announce from the
machine, because whether a workspace may be written to is the machine's answer.

An explicit column rather than a key in `nodes.metadata`, on the same judgement as
0017: "which of my nodes will accept a file from a browser" is a fleet-level security
question, and a key inside JSONB is not something anyone will index. Indexed for the
same reason the privileged-terminal column is.

`server_default=false` is load-bearing in the same way: a node that has not reported
yet reads as *not* accepting uploads, so the console hides the entry point rather than
offering a button that fails. Absent is never "unknown". No backfill is needed —
every daemon re-registers on its next connection, and until then hiding the affordance
is the correct behaviour rather than a degraded one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_node_image_upload"
down_revision: str | None = "0017_node_privileged_posture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "image_upload",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_nodes_image_upload", "nodes", ["image_upload"])


def downgrade() -> None:
    op.drop_index("ix_nodes_image_upload", table_name="nodes")
    op.drop_column("nodes", "image_upload")
