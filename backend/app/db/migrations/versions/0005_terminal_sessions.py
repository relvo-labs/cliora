"""terminal_sessions and session_connections

Revision ID: 0005_terminal_sessions
Revises: 0004_add_query_indexes
Create Date: 2026-07-24

Phase 2 session/terminal durable metadata (PRD §12.6, ADR 0013). Terminal bytes
are never stored — only lifecycle metadata and connection roles. All instant
columns are TIMESTAMP WITH TIME ZONE. Downgrade drops both tables in FK order.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_terminal_sessions"
down_revision: Union[str, None] = "0004_add_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "terminal_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("runtime", sa.String(length=16), nullable=False),
        sa.Column("workspace", sa.String(length=4096), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("columns", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_terminal_sessions"),
        # RESTRICT: nodes are soft-deleted (deleted_at), never hard-deleted, so
        # session history is retained for audit.
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_terminal_sessions_node_id_nodes"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_terminal_sessions_user_id_users"),
    )
    op.create_index("ix_terminal_sessions_node_id", "terminal_sessions", ["node_id"])
    op.create_index("ix_terminal_sessions_user_id", "terminal_sessions", ["user_id"])
    op.create_index("ix_terminal_sessions_status", "terminal_sessions", ["status"])

    op.create_table(
        "session_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_session_connections"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["terminal_sessions.id"],
            name="fk_session_connections_session_id_terminal_sessions", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_session_connections_user_id_users"),
    )
    op.create_index("ix_session_connections_session_id", "session_connections", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_session_connections_session_id", table_name="session_connections")
    op.drop_table("session_connections")
    op.drop_index("ix_terminal_sessions_status", table_name="terminal_sessions")
    op.drop_index("ix_terminal_sessions_user_id", table_name="terminal_sessions")
    op.drop_index("ix_terminal_sessions_node_id", table_name="terminal_sessions")
    op.drop_table("terminal_sessions")
