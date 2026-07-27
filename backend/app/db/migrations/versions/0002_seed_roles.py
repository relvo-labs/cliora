"""seed Admin/Developer/Viewer roles

Revision ID: 0002_seed_roles
Revises: 0001_initial
Create Date: 2026-07-24

Seeds the three stable roles and their permission matrix (PRD §8.1) via a
versioned migration — never at application startup (ADR 0009). Action keys are
the stable authorization vocabulary consumed by the RBAC service.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_seed_roles"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_IDS = {
    "Admin": "00000000-0000-4000-8000-0000000000a1",
    "Developer": "00000000-0000-4000-8000-0000000000a2",
    "Viewer": "00000000-0000-4000-8000-0000000000a3",
}

# Stable authorization action keys (superset spanning P1-P4). P1 enforces the
# control-plane subset; later phases enforce the session/file/audit actions.
_DEV = ["node.view", "session.create", "terminal.operate", "session.terminate", "file.browse"]
_ADMIN = _DEV + ["enrollment.manage", "node.manage", "audit.view"]
_VIEWER = ["node.view", "file.browse"]

PERMISSIONS = {"Admin": _ADMIN, "Developer": _DEV, "Viewer": _VIEWER}


def upgrade() -> None:
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("permissions", postgresql.JSONB()),
    )
    op.bulk_insert(
        roles,
        [
            {"id": ROLE_IDS[name], "name": name, "permissions": {"actions": actions}}
            for name, actions in PERMISSIONS.items()
        ],
    )


def downgrade() -> None:
    # These stable roles may already be referenced by durable users. Deleting
    # them here makes ``downgrade base`` fail on users.role_id. Keep them at
    # revision 0001; downgrading 0001 then drops the complete P1 schema.
    pass
