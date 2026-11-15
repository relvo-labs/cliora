"""Durable login lockout for known/unknown usernames and Admin unlock action.

Revision ID: 0023_login_lockout
Revises: 0022_node_binary_preview

Downgrade discards protection counters (including unknown usernames) and removes
only user.unlock grants; users, credentials and other grants are preserved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_login_lockout"
down_revision: str | None = "0022_node_binary_preview"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_lockouts",
        sa.Column("username_key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_login_lockouts_last_activity_at", "login_lockouts", ["last_activity_at"])
    op.execute("""
        UPDATE roles SET permissions = jsonb_set(permissions, '{actions}',
            (permissions->'actions') || '"user.unlock"'::jsonb)
        WHERE name = 'Admin' AND NOT ((permissions->'actions') ? 'user.unlock')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles SET permissions = jsonb_set(permissions, '{actions}',
            (permissions->'actions') - 'user.unlock')
        WHERE (permissions->'actions') ? 'user.unlock'
    """)
    # DROP TABLE also removes its activity index.
    op.drop_table("login_lockouts")
