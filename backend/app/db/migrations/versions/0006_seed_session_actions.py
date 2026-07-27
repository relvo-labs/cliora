"""expand role permissions with session.view and terminal.takeover

Revision ID: 0006_seed_session_actions
Revises: 0005_terminal_sessions
Create Date: 2026-07-24

Phase 2 RBAC expansion (ADR 0013). Adds the read-only session view (all roles,
so Viewers can attach read-only) and the writer-takeover action (Admin +
Developer). Idempotent: each action is appended only if absent, so re-running or
applying over prior data is safe. Downgrade removes exactly these additions.

session.create / terminal.operate / session.terminate were already seeded for
Admin + Developer in 0002; this migration only adds the two new keys.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_seed_session_actions"
down_revision: Union[str, None] = "0005_terminal_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_action(names: list[str], action: str) -> str:
    quoted = ", ".join(f"'{n}'" for n in names)
    return (
        "UPDATE roles SET permissions = jsonb_set(permissions, '{actions}', "
        f"(permissions->'actions') || '\"{action}\"'::jsonb) "
        f"WHERE name IN ({quoted}) "
        f"AND NOT ((permissions->'actions') ? '{action}');"
    )


def _remove_action(names: list[str], action: str) -> str:
    quoted = ", ".join(f"'{n}'" for n in names)
    return (
        "UPDATE roles SET permissions = jsonb_set(permissions, '{actions}', "
        "(SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) "
        "FROM jsonb_array_elements(permissions->'actions') e "
        f"WHERE e <> '\"{action}\"'::jsonb)) "
        f"WHERE name IN ({quoted});"
    )


def upgrade() -> None:
    op.execute(_add_action(["Admin", "Developer", "Viewer"], "session.view"))
    op.execute(_add_action(["Admin", "Developer"], "terminal.takeover"))


def downgrade() -> None:
    op.execute(_remove_action(["Admin", "Developer"], "terminal.takeover"))
    op.execute(_remove_action(["Admin", "Developer", "Viewer"], "session.view"))
