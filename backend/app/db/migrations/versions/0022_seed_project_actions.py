"""grant project.view (all roles) and project.manage (Admin)

Revision ID: 0022_seed_project_actions
Revises: 0021_projects
Create Date: 2026-08-08

PJ-03 / FR-PROJECT-001 (ADR 0027 sec 4). Two actions, and the split between them is
the decision worth recording:

* **`project.view` goes to all three roles**, like `node.view`: a Viewer may look at
  the shape of the fleet, and a project is a name for part of that shape. It carries
  one obligation, enforced in `services/activity.py`: the project timeline is
  readable with this action, so actor identity is stripped from it for anyone
  without `audit.view`. Otherwise a read granted to every role would quietly become
  the actor feed that `services/dashboard.py::project_for` exists to prevent.
* **`project.manage` is Admin only**, with enrollment and node management rather
  than with the session-shaped Developer actions. Deciding which projects exist —
  and which machines and directories they cover — is an organisation-level call.
  From V2.3 a binding means more again: binding a runner to a project authorises it
  to draw that project's secrets. An action that starts in Developer hands and is
  narrowed later takes a privilege away from people who already have it, which is a
  worse migration than granting it to Admin now.

`project.manage` is deliberately **not** a widening of `node.manage`, even though
both are Admin-only today. The audit trail has to distinguish "removed a node" from
"unbound a project's workspace", and a filter on a merged action could not.

Idempotent per action, matching 0016 and 0019: appended only if absent, so
re-running this or applying it over prior data changes nothing. Downgrade removes
each action from every role rather than only the seeded ones, so a grant widened by
hand in between leaves no holder behind.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_seed_project_actions"
down_revision: str | None = "0021_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_ONLY = ["Admin"]
_ALL_ROLES = ["Admin", "Developer", "Viewer"]

_PROJECT_VIEW = "project.view"
_PROJECT_MANAGE = "project.manage"


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
    op.execute(_add_action(_ALL_ROLES, _PROJECT_VIEW))
    op.execute(_add_action(_ADMIN_ONLY, _PROJECT_MANAGE))


def downgrade() -> None:
    op.execute(_remove_action(_ALL_ROLES, _PROJECT_MANAGE))
    op.execute(_remove_action(_ALL_ROLES, _PROJECT_VIEW))
