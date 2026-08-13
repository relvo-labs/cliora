"""grant secret.manage (Admin)

Revision ID: 0034_seed_secret_action
Revises: 0033_project_secrets
Create Date: 2026-08-13

One action, Admin only, and the reason is the same one that put `enrollment.manage`
there: a credential the platform holds on a user's behalf, hands to a machine on
demand and can revoke is an organisation-level asset, not day-to-day work.

**It also guards repository registration from this phase on**, which is a tightening —
that endpoint used to require `project.manage`. Both are Admin-only, so no role loses
an ability; but a tightening that is not announced surfaces as a 403 in somebody's
automation, so it is in the release note as well as here. The reason for the move is
that a repository row stopped being "where the code is" and became "which credential
fetches it" (ADR 0032).

The grant is expressed as a JSONB append guarded by a `NOT (… ? action)` test, the same
shape every seed migration in this repository uses, so `alembic upgrade head` twice is
the same as once.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_seed_secret_action"
down_revision: str | None = "0033_project_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_ROLES = ["Admin", "Developer", "Viewer"]
_ADMIN = ["Admin"]

_GRANTS = (("secret.manage", _ADMIN),)


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
    for action, roles in _GRANTS:
        op.execute(_add_action(roles, action))


def downgrade() -> None:
    for action, _ in _GRANTS:
        op.execute(_remove_action(_ALL_ROLES, action))
