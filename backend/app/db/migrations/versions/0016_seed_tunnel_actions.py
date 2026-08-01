"""grant tunnel.view / tunnel.manage (Admin + Developer) and integration.manage (Admin)

Revision ID: 0016_seed_tunnel_actions
Revises: 0015_tunnel_integration
Create Date: 2026-08-01

PG-04 / FR-TUNNEL-002.AC-04, FR-TUNNEL-004.AC-01 (ADR 0022).

Three actions, and the split between them is the decision worth recording:

* `tunnel.view` and `tunnel.manage` go to **Admin and Developer**. Seeing a tunnel's URL is
  effectively being able to reach that preview, and a Developer already drives sessions on
  the nodes they work on. Viewer holds neither: a web application's read-only-ness is not
  something the platform can promise on the application's behalf, so "read-only user" and
  "can open the preview" do not compose.
* `integration.manage` goes to **Admin only**. It covers supplying the organisation's
  third-party credential and deciding that traffic may leave for a third party at all —
  the same boundary that already keeps `enrollment.manage` and `node.manage` Admin-only. A
  Developer may open tunnels; they may not decide whose service and whose account.

Idempotent per action: each is appended only if absent, so re-running the migration or
applying it over prior data changes nothing. Downgrade removes all three from every role,
not just the seeded ones, so a capability widened by hand in between leaves no holder
behind — the same reasoning as 0012.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_seed_tunnel_actions"
down_revision: str | None = "0015_tunnel_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_DEVELOPER = ["Admin", "Developer"]
_ADMIN_ONLY = ["Admin"]
_ALL_ROLES = ["Admin", "Developer", "Viewer"]

_TUNNEL_VIEW = "tunnel.view"
_TUNNEL_MANAGE = "tunnel.manage"
_INTEGRATION_MANAGE = "integration.manage"


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
    op.execute(_add_action(_ADMIN_DEVELOPER, _TUNNEL_VIEW))
    op.execute(_add_action(_ADMIN_DEVELOPER, _TUNNEL_MANAGE))
    op.execute(_add_action(_ADMIN_ONLY, _INTEGRATION_MANAGE))


def downgrade() -> None:
    for action in (_TUNNEL_VIEW, _TUNNEL_MANAGE, _INTEGRATION_MANAGE):
        op.execute(_remove_action(_ALL_ROLES, action))
