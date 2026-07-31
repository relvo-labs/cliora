"""grant terminal.shell to Admin and Developer for the system terminal

Revision ID: 0012_seed_terminal_shell
Revises: 0011_workspace_favorites
Create Date: 2026-07-31

Scope change recorded in ADR 0021 (`SCOPE-011` narrowed, FR-SHELL-001 added).
`terminal.shell` gates opening an interactive shell on a node.

Granted to Admin and Developer, **not Viewer**. The action layer alone is not the
boundary here: `authz.may_open_shell` additionally requires ownership of the CLI
session, and no user — Admin included — may attach to somebody else's shell.

Idempotent: the action is appended only if absent, so re-running or applying over
prior data is safe. Downgrade removes exactly this addition, which is also the
supported way to revoke the capability fleet-wide.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_seed_terminal_shell"
down_revision: str | None = "0011_workspace_favorites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ["Admin", "Developer"]
_ACTION = "terminal.shell"


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
    # Every role, not just the two seeded: a downgrade must leave no holder
    # behind if the action was widened by hand in between.
    op.execute(_remove_action(["Admin", "Developer", "Viewer"], _ACTION))
