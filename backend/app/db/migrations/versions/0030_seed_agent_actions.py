"""grant agent.view (all roles), agent.manage (Admin), run.dispatch and run.cancel
(Developer + Admin)

Revision ID: 0030_seed_agent_actions
Revises: 0029_agent_runs
Create Date: 2026-08-11

AR-03 / FR-AGENT-001, FR-AGENT-003 (ADR 0029, plan/18/02-…md §6). Four actions, three
different holder sets — which is the part worth writing down, because each split
looks like it could be simplified and each one is load-bearing.

**`agent.view` goes to every role**, for the same reason as `node.view` and
`project.view`: a Viewer may see the shape of the fleet.

**`agent.manage` goes to Admin only, and the reason is in the future tense.** Today it
covers enable/disable, concurrency and labels — three things that do not look like
organisational decisions on their own. **From V2.3 it also covers binding a runner to
a project, and that binding is what authorises the runner to read the project's
secrets.** An action cannot be given to Developer now and taken back then, which is
the same argument the `project.manage` comment already makes.

> **Note added 2026-08-13.** The forecast in the paragraph above did not hold: the
> 2026-08-12 ruling cancelled `project_agents`, so `agent.manage` never grew that
> meaning. It stays Admin-only for a plainer reason — enabling a runner and setting
> its concurrency is the disposition of compute. It does **not** cover editing tags,
> which are declared by the node's own config (ADR 0029 amendment B5), and the
> secrets themselves are `secret.manage`, seeded separately in `0034`.

**`run.dispatch` is separate from `task.update`** because queueing work spends
compute: it clones a repository onto a machine and starts a process there. That is a
different order of magnitude from editing a field, and the audit trail has to be able
to tell them apart.

**V2.2 has no project↔agent binding at all**, so it is worth being explicit about what
these four actions do *not* bound: a runner on any enrolled node can claim any
project's card and pull any project's code. **The authorization boundary of this phase
is `enrollment.manage`, not `agent.manage`.** The same sentence appears in
`services/rbac.py` and on the Agents page — three places, because it is the kind of
design that gets reported as a bug when it is only written once.

Idempotent per action, matching 0016, 0019, 0022 and 0025: appended only when absent.
Downgrade removes each action from every role rather than only from the seeded ones,
so a grant widened by hand in between leaves no holder behind.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030_seed_agent_actions"
down_revision: str | None = "0029_agent_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_ROLES = ["Admin", "Developer", "Viewer"]
_WRITERS = ["Admin", "Developer"]
_ADMIN = ["Admin"]

_GRANTS = (
    ("agent.view", _ALL_ROLES),
    ("agent.manage", _ADMIN),
    ("run.dispatch", _WRITERS),
    ("run.cancel", _WRITERS),
)


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
