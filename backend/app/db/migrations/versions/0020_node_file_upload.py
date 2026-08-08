"""nodes.file_upload: whether this node accepts general file upload into a workspace

Revision ID: 0020_node_file_upload
Revises: 0019_seed_file_upload_action
Create Date: 2026-08-03

FU-05 / ADR 0026. A second posture column beside `image_upload`, not a widening of
it: "may the platform put screenshots in .cliora/" and "may it put arbitrary files
anywhere in my workspace" are different-sized grants, and a node owner is entitled
to answer them differently. A single column would force one answer on both.

Report-only, like `privileged_terminal` and `image_upload` before it — nothing in
the platform writes this except a `node.register` announce from the machine.

An explicit column rather than a key in `nodes.metadata`, and indexed, on the same
judgement as 0017 and 0018: "which of my nodes will accept an arbitrary file from a
browser" is a fleet-level security question, and a key inside JSONB is not something
anyone will index.

`server_default=false` is load-bearing in the same way: a node that has not reported
yet reads as *not* accepting uploads, so the console hides the entry point rather than
offering a control that fails. Absent is never "unknown". No backfill — every daemon
re-registers on its next connection, and until then hiding the affordance is correct
rather than degraded.

Note this migration adds no RBAC seed. General file upload reuses the existing
`file.upload` action (ADR 0026 §6), so unlike 0019 there is no role row to touch —
the cost of that reuse is that the action's *meaning* widens, which is a release-note
obligation rather than a schema one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_node_file_upload"
down_revision: str | None = "0019_seed_file_upload_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "file_upload",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_nodes_file_upload", "nodes", ["file_upload"])


def downgrade() -> None:
    op.drop_index("ix_nodes_file_upload", table_name="nodes")
    op.drop_column("nodes", "file_upload")
