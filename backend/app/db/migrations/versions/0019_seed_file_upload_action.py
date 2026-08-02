"""grant file.upload (Admin + Developer)

Revision ID: 0019_seed_file_upload_action
Revises: 0018_node_image_upload
Create Date: 2026-08-01

WF-06 / FR-FILE-009.AC-01 (ADR 0024 §6).

One action, and the reason it is its own action rather than a widening of an
existing one is the decision worth recording:

* Not folded into `file.browse`. All three roles hold that one, so widening it
  would hand Viewer the ability to write to a node — and "read-only viewer" is a
  promise the rest of the system makes in several other places (P2 read-only
  attach, ADR 0015's RBAC section). A role named Viewer that can write files is
  a lie the console would keep telling.
* Not folded into `terminal.operate`. That action means driving a terminal. If
  writing a file were the same permission, the audit trail could no longer
  distinguish "typed something" from "put a file on the machine", which is the
  one distinction an incident review of this feature would start from.

`file.upload` therefore goes to **Admin and Developer**: the roles that already
create sessions and drive them on the nodes they work on.

Idempotent per action, matching 0016: appended only if absent, so re-running the
migration or applying it over prior data changes nothing. Downgrade removes it
from every role rather than only the seeded two, so a grant widened by hand in
between leaves no holder behind.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_seed_file_upload_action"
down_revision: str | None = "0018_node_image_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_DEVELOPER = ["Admin", "Developer"]
_ALL_ROLES = ["Admin", "Developer", "Viewer"]

_FILE_UPLOAD = "file.upload"


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
    op.execute(_add_action(_ADMIN_DEVELOPER, _FILE_UPLOAD))


def downgrade() -> None:
    op.execute(_remove_action(_ALL_ROLES, _FILE_UPLOAD))
