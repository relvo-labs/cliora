"""node_tunnels: port-forwarding tunnels delivered through a third-party provider

Revision ID: 0014_node_tunnels
Revises: 0013_shell_session_parent
Create Date: 2026-08-01

PG-04 / FR-TUNNEL-001 (ADR 0022). One row per tunnel the platform has opened on a node.
The tunnel itself is an `ssh -R` child process on the node and the traffic never reaches
Central, so what is durable here is only the platform's view of it.

Three shapes in this table are deliberate:

* **No `status` column.** State is derived from `closed_at`, `expires_at`,
  `state_error_code` and whether the node is connected. A stored status would be a second
  answer to a question that already has one, and it would be the stale one.
* **`CHECK (port BETWEEN 1024 AND 65535)`.** The floor is enforced in four places (API,
  this constraint, the wire schema, the daemon) because the failure this prevents is
  publishing a system service — `sshd` on 22, a database on 5432 — to the internet.
* **A partial unique index on (node_id, port), filtered on live rows.** Two live tunnels on
  the same port would give a user two URLs for one service, where closing one leaves the
  other working and no way to reason about it. Filtered rather than plain, because closing
  a tunnel and opening it again is normal.

Closed rows are kept: they carry who opened and closed a tunnel, which is the audit
question this table can answer that the audit log alone cannot join.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_node_tunnels"
down_revision: str | None = "0013_shell_session_parent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "node_tunnels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="pinggy"),
        sa.Column("protection", sa.String(length=16), nullable=False),
        sa.Column("basic_auth_user", sa.String(length=64), nullable=True),
        sa.Column("basic_auth_hash", sa.Text(), nullable=True),
        sa.Column("allowed_ips", postgresql.JSONB(), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("rewrite_host", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("url_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url_change_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upstream_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "closed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.CheckConstraint("port BETWEEN 1024 AND 65535", name="ck_node_tunnels_port_range"),
        sa.CheckConstraint(
            "protection IN ('basic', 'ipallow', 'public')",
            name="ck_node_tunnels_protection",
        ),
    )
    op.create_index("ix_node_tunnels_node", "node_tunnels", ["node_id"])
    op.create_index("ix_node_tunnels_created_by", "node_tunnels", ["created_by"])
    op.create_index(
        "uq_node_tunnels_live_port",
        "node_tunnels",
        ["node_id", "port"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    # Port-forwarding prerequisites as last reported by the daemon. Defaults are the
    # pessimistic answers: an existing node has reported nothing yet, so it is not ready,
    # and `tunnel_reported_at IS NULL` is how the UI distinguishes "not ready" from
    # "we have not heard".
    op.add_column(
        "nodes",
        sa.Column("tunnel_veto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "nodes",
        sa.Column(
            "tunnel_prereq_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("nodes", sa.Column("tunnel_prereq_detail", postgresql.JSONB(), nullable=True))
    op.add_column(
        "nodes", sa.Column("tunnel_local_allowed_ports", postgresql.JSONB(), nullable=True)
    )
    op.add_column("nodes", sa.Column("tunnel_local_max", sa.Integer(), nullable=True))
    op.add_column(
        "nodes", sa.Column("tunnel_reported_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    for column in (
        "tunnel_reported_at",
        "tunnel_local_max",
        "tunnel_local_allowed_ports",
        "tunnel_prereq_detail",
        "tunnel_prereq_ok",
        "tunnel_veto",
    ):
        op.drop_column("nodes", column)
    op.drop_index("uq_node_tunnels_live_port", table_name="node_tunnels")
    op.drop_index("ix_node_tunnels_created_by", table_name="node_tunnels")
    op.drop_index("ix_node_tunnels_node", table_name="node_tunnels")
    op.drop_table("node_tunnels")
