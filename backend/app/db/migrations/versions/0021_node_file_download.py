"""nodes.file_download: whether this node hands workspace files back to a browser

Revision ID: 0021_node_file_download
Revises: 0020_node_file_upload
Create Date: 2026-09-16

FD-05 / ADR 0028. A third posture column beside `image_upload` and `file_upload`,
and the reason it is a third rather than a reuse is the direction: those two say
what may be written *into* this machine's workspaces, this one says what may be
read *out* of them. An operator who has thought about exfiltration has thought
about exactly this column, and a node that accepts a dropped screenshot has not
thereby agreed to send its source tree to a browser.

Report-only, like the three posture columns before it — nothing in the platform
writes this except a `node.register` announce from the machine itself. There is
deliberately no endpoint that sets it.

Indexed on the same judgement as 0017/0018/0020: "which of my nodes will send
files to a browser" is a fleet-level security question, and the answer has to be
a query rather than a scan.

`server_default=false` is load-bearing in the same way it was there: a node that
has not reported yet reads as *not* offering download, so the console hides the
control rather than showing one that fails. Absent is never "unknown". No
backfill — every daemon re-registers on its next connection, and until then
hiding the affordance is correct rather than degraded.

Note this migration adds no RBAC seed. Download reuses the existing `file.browse`
action (ADR 0028 §5), so unlike 0019 there is no role row to touch. The cost of
that reuse is that the action's *meaning* widens — a `file.browse` holder can now
take the exact bytes of a file the preview would only have shown as text, and of
one it would have refused to render at all — which is a release-note obligation
rather than a schema one, and it is the first paragraph of that release note.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_node_file_download"
down_revision: str | None = "0020_node_file_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "file_download",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_nodes_file_download", "nodes", ["file_download"])


def downgrade() -> None:
    op.drop_index("ix_nodes_file_download", table_name="nodes")
    op.drop_column("nodes", "file_download")
