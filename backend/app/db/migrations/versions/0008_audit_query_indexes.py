"""audit_logs query indexes for the Admin audit viewer

Revision ID: 0008_audit_query_indexes
Revises: 0007_seed_file_browse
Create Date: 2026-07-25

P4-04. The audit trail has been written since P1 but never queried, so it only
carried the indexes the writer needed: `action`, `created_at` (0001) and `node_id`
(0004). The Admin viewer (P4-05) filters by actor and by action within a time
range, ordered newest-first with a `(created_at, id)` cursor — which on the
current indexes means a sequential scan over a table that only grows.

Added:

* `ix_audit_logs_user_id` — filtering by actor had no index at all.
* `ix_audit_logs_created_at_id` — the pagination cursor's exact ordering, so a
  page is an index range scan rather than a sort of the whole table.
* `ix_audit_logs_action_created_at` / `ix_audit_logs_user_created_at` — the two
  filter-plus-time-range shapes the viewer actually issues.

Index-only DDL: no data is read or written, and downgrade drops exactly these
four. `IF NOT EXISTS` / `IF EXISTS` keep it re-runnable over prior data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_audit_query_indexes"
down_revision: str | None = "0007_seed_file_browse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_audit_logs_user_id", "(user_id)"),
    ("ix_audit_logs_created_at_id", "(created_at DESC, id DESC)"),
    ("ix_audit_logs_action_created_at", "(action, created_at DESC)"),
    ("ix_audit_logs_user_created_at", "(user_id, created_at DESC)"),
)


def upgrade() -> None:
    for name, columns in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON audit_logs {columns};")


def downgrade() -> None:
    for name, _ in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name};")
