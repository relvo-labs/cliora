"""grant process.manage and task.force_done (Admin)

Revision ID: 0037_seed_delivery_actions
Revises: 0036_delivery_and_ac_results
Create Date: 2026-08-14

Two actions, both Admin only, and neither is a reuse of something that already exists —
which is the decision worth recording here, because both had an obvious candidate to
fold into.

**`process.manage` is not `project.manage`.** A project's settings describe one
project; the process definition is the vocabulary every project's board and every
cross-project metric is expressed in. Overriding it changes what "ready" and "done"
mean for a whole project, and that is an organisation-level judgement (ADR 0033 §5).

**`task.force_done` is not `task.approve`.** Approving one review gate and skipping the
completion criteria wholesale are not the same authority, even though the same people
hold both today. Folding them together would also make the forced-done exit reachable
by anything that can already approve a gate, and the whole point of this exit is that
every use of it is visible and countable.

⚠️ **`task.approve` gains a second job in this phase and gains no new holder.** From
V2.4 it also authorises declaring a verification command on a card, because
`RUN_TOKEN_SCOPES` deliberately excludes it — an agent may not choose what verifies it
(ADR 0033 §3b). That needs no migration: the action already exists with the right
holders, and this note is here so a reader of the seed history knows the widening was
intentional rather than overlooked.

Idempotent in the same shape every seed migration here uses, so `alembic upgrade head`
twice is the same as once.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037_seed_delivery_actions"
down_revision: str | None = "0036_delivery_and_ac_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_ROLES = ["Admin", "Developer", "Viewer"]
_ADMIN = ["Admin"]

_GRANTS = (("process.manage", _ADMIN), ("task.force_done", _ADMIN))


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
