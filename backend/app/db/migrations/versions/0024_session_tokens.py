"""session_tokens: the credential an agent inside a session may hold

Revision ID: 0024_session_tokens
Revises: 0023_task_board
Create Date: 2026-08-09

TK-06 / FR-TASK-008 (ADR 0028 sec 3, plan/17/04-…md). One table, and every column
on it is answering a question the security review asks (`docs/security-review-v21.md`).

**Only the HMAC is stored**, keyed by the existing `CLIORA_TOKEN_PEPPER` — the same
construction enrollment tokens and node secrets already use (ADR 0008), not a new
one. Verification hashes the presented value and looks it up, so the unique index on
`token_hash` is also the lookup index; there is no path that reads a plaintext token
back, because none is kept.

`scopes` is **snapshotted at issue time** rather than read from a live setting. A
credential is a fixed grant: if the scope list were consulted per request, changing a
constant would silently re-authorise every token already in the wild.

`revoked_at` rows are kept for 90 days after revocation because the audit trail names
a `token_id` and that name has to stay resolvable. That is a third answer to ADR
0024's W2 question in this phase alone — `activity_events` has no retention at all,
the projected files have 30 days — which is why plan/17 writes the three of them down
in one table rather than each next to its own code (ADR 0028 sec 6).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_session_tokens"
down_revision: str | None = "0023_task_board"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # CASCADE, unlike most of this schema: a token is not history. When the
        # session row goes, the credential that only ever meant "this session" has
        # nothing left to authorise.
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("terminal_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        # RESTRICT for the same reason `projects.owner_user_id` uses it: someone
        # leaving must not take the record of what their session's agent did.
        sa.Column(
            "issued_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Best-effort and deliberately not on the request's critical path: it feeds
        # the "last used" line in the console, and a write per API call to keep it
        # exact would cost more than the line is worth.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_session_tokens_hash"),
    )
    # Revocation is per session and happens inside the session state machine, so it
    # is a lookup by `session_id` rather than by id.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_session_tokens_session ON session_tokens (session_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_session_tokens_session;")
    op.drop_table("session_tokens")
