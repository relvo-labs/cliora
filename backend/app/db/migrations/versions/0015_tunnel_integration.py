"""tunnel_integration + node_tunnel_settings: the platform's port-forwarding settings

Revision ID: 0015_tunnel_integration
Revises: 0014_node_tunnels
Create Date: 2026-08-01

PG-04 / FR-TUNNEL-004 (ADR 0022). Two tables, one purpose: make "is port forwarding
available, with whose credential, and for which nodes" a platform decision that an
administrator makes in the UI rather than an environment variable someone edits on a host.

`tunnel_integration` is a **single row**, and that is enforced rather than assumed:
`singleton BOOLEAN UNIQUE CHECK (singleton)` admits exactly one. Code that reads "the
first row" would silently pick one of two if a second ever appeared, and the wrong
settings row is the kind of bug nobody finds by reading.

It is also the only place in this schema that holds a third-party credential, so it holds
ciphertext (AES-GCM), a per-write nonce, and an 8-hex fingerprint of the plaintext. The
fingerprint exists so a person can answer "is this the token I rotated last week" without
any interface returning a character of it. **There is no column that could hold the
plaintext**, which is the point: with the encryption key unset the application refuses to
store a credential at all rather than falling back to plain text.

`concurrent_budget` defaults to 8 and is fleet-wide — the number of tunnels the provider's
plan allows at once. It is checked as a global count, never folded into the per-node cap:
a budget of 8 with a per-node cap of 3 would otherwise permit 3xN tunnels across the fleet
and the provider answers that by displacing somebody else's tunnel.

`node_tunnel_settings.enabled` defaults to true. The platform-level switch is the real
gate, and an enrolled node already grants the platform a shell runtime (ADR 0021), so a
second per-machine opt-in would be form rather than substance. A node owner's veto lives
in the node's own config file, where the platform cannot reach it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_tunnel_integration"
down_revision: str | None = "0014_node_tunnels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tunnel_integration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("singleton", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="pinggy"),
        sa.Column("plan_tier", sa.String(length=16), nullable=False, server_default="free"),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("token_fingerprint", sa.String(length=16), nullable=True),
        sa.Column("concurrent_budget", sa.Integer(), nullable=False, server_default="8"),
        sa.Column(
            "default_protection", sa.String(length=16), nullable=False, server_default="basic"
        ),
        sa.Column("default_ttl_seconds", sa.Integer(), nullable=False, server_default="14400"),
        sa.Column("allowed_ports", postgresql.JSONB(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.UniqueConstraint("singleton", name="uq_tunnel_integration_singleton"),
        sa.CheckConstraint("singleton", name="ck_tunnel_integration_singleton"),
        sa.CheckConstraint("provider IN ('pinggy')", name="ck_tunnel_integration_provider"),
        sa.CheckConstraint("plan_tier IN ('free', 'pro')", name="ck_tunnel_integration_plan"),
        sa.CheckConstraint(
            "default_protection IN ('basic', 'ipallow', 'public')",
            name="ck_tunnel_integration_protection",
        ),
        sa.CheckConstraint(
            "concurrent_budget BETWEEN 1 AND 100", name="ck_tunnel_integration_budget"
        ),
        sa.CheckConstraint(
            "default_ttl_seconds BETWEEN 60 AND 86400", name="ck_tunnel_integration_ttl"
        ),
    )

    op.create_table(
        "node_tunnel_settings",
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allowed_ports", postgresql.JSONB(), nullable=True),
        sa.Column("max_tunnels", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.CheckConstraint(
            "max_tunnels IS NULL OR max_tunnels BETWEEN 1 AND 100",
            name="ck_node_tunnel_settings_max",
        ),
    )

    # No row is inserted. An absent row means "not configured", which the service layer
    # reports as disabled; seeding a disabled row here would make the first read look like
    # an administrator had already been through the settings page.


def downgrade() -> None:
    op.drop_table("node_tunnel_settings")
    op.drop_table("tunnel_integration")
