"""agent_runners.features: what a node's daemon can do that an older one cannot

Revision ID: 0038_runner_features
Revises: 0037_seed_delivery_actions
Create Date: 2026-08-14

One column, and its **default is the empty array** — the opposite polarity from
`run_untagged` and `accept_secrets`, which default to true.

That looks inconsistent in a schema dump and is the same rule underneath: *an absent
declaration means the behaviour before the upgrade*. Those two are refusal flags, so
"before the upgrade" is "does not refuse"; this is a support flag, so "before the
upgrade" is "cannot". A permissive default here would mean assuming a machine performs
a feature it has never heard of (ADR 0029 amendment C).

Read-only from the platform's side, like `labels`: it is a fact the node reports about
its own binary, and an editable copy would be a second source of truth that
`runner.register` overwrites on the next reconnect.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_runner_features"
down_revision: str | None = "0037_seed_delivery_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runners",
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runners", "features")
