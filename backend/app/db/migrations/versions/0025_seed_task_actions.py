"""grant task.create, task.update and task.approve (Developer + Admin)

Revision ID: 0025_seed_task_actions
Revises: 0024_session_tokens
Create Date: 2026-08-09

TK-04 / FR-TASK-001, FR-TASK-004 (ADR 0028 sec 1, plan/17/03-…md §2). Three actions,
all held by exactly the same two roles — which is the part worth recording, because
it looks redundant and is not.

**Viewer holds none of them**, for the reason that has not changed since 0002: it is
the read-only role. It keeps `project.view`, which is what makes the board, the
roadmap and a task's detail readable.

**`task.approve` and `task.update` have deliberately identical holders.** Splitting
them separates nothing at the role layer; its whole effect is that
"an agent's credential cannot approve" becomes something that can be **written into a
token's scope** — and an action that does not exist cannot be excluded from a scope
(research/02/01 D13, ruling 3 of 2026-08-08). Without this paragraph the next reader
finds two actions with one holder set and merges them, and that merge silently opens
the path to an agent approving its own work.

Not folded into `project.manage` either: the audit trail has to distinguish "changed
a task's stage" from "unbound a project's workspace", and a filter over a merged
action could not.

Idempotent per action, matching 0016, 0019 and 0022: appended only when absent.
Downgrade removes each action from every role rather than only from the seeded ones,
so a grant widened by hand in between leaves no holder behind.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_seed_task_actions"
down_revision: str | None = "0024_session_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WRITERS = ["Admin", "Developer"]
_ALL_ROLES = ["Admin", "Developer", "Viewer"]

_ACTIONS = ("task.create", "task.update", "task.approve")


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
    for action in _ACTIONS:
        op.execute(_add_action(_WRITERS, action))


def downgrade() -> None:
    for action in _ACTIONS:
        op.execute(_remove_action(_ALL_ROLES, action))
