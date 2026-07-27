"""grant file.browse to all roles for the P3 read-only file relay

Revision ID: 0007_seed_file_browse
Revises: 0006_seed_session_actions
Create Date: 2026-07-25

Phase 3 RBAC expansion (ADR 0015). Adds the single read-only file action
`file.browse` — covering directory listing, filename search, and file preview —
to Admin, Developer, and Viewer (Viewer read-only), consistent with P2's
read-only viewer attach. There is no separate preview action. Idempotent: the
action is appended only if absent, so re-running or applying over prior data is
safe. Downgrade removes exactly this addition.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_seed_file_browse"
down_revision: str | None = "0006_seed_session_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ["Admin", "Developer", "Viewer"]
_ACTION = "file.browse"


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
    op.execute(_add_action(_ROLES, _ACTION))


def downgrade() -> None:
    op.execute(_remove_action(_ROLES, _ACTION))
