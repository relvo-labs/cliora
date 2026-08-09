"""close active sessions left behind by soft-deleted nodes

Revision ID: 0028_node_removal_sessions
Revises: 0027_node_context_projection
Create Date: 2026-08-09

Older Central versions revoked a removed node's credential and severed its socket
without ending its active session rows. Those rows can never receive another daemon
status update, yet keep appearing as running and keep their session credential alive.

This is an operational correction, not a schema change. Downgrade is intentionally a
no-op: resurrecting sessions on a node whose identity was permanently revoked would
manufacture a state that cannot be true.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_node_removal_sessions"
down_revision: str | None = "0027_node_context_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE terminal_sessions AS session
        SET status = 'failed',
            ended_at = COALESCE(session.ended_at, CURRENT_TIMESTAMP),
            error_message = 'NODE_REMOVED'
        FROM nodes AS node
        WHERE session.node_id = node.id
          AND node.deleted_at IS NOT NULL
          AND session.status IN ('starting', 'running', 'disconnected', 'terminating')
        """
    )
    op.execute(
        """
        UPDATE session_tokens AS token
        SET revoked_at = COALESCE(token.revoked_at, CURRENT_TIMESTAMP)
        FROM terminal_sessions AS session, nodes AS node
        WHERE token.session_id = session.id
          AND session.node_id = node.id
          AND node.deleted_at IS NOT NULL
          AND token.revoked_at IS NULL
        """
    )


def downgrade() -> None:
    pass
