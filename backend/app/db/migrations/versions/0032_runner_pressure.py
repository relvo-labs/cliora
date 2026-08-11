"""agent_runners: why a runner stopped polling, and how full its disk is

Revision ID: 0032_runner_pressure
Revises: 0031_node_agent_runner
Create Date: 2026-08-11

Exit condition 21, and the reason it needs storage at all.

A runner expresses "I have no capacity" by **not polling** (ADR 0029 sec 2). That is the
right protocol — it removes the scheduler — but it has one consequence: from Central,
a full runner, a runner out of disk and a runner whose machine is gone all look
identical, because all three are silence. The Agents page would then show "離線" for a
machine that is running fine and simply has nowhere to put a checkout, and the person
reading it would go looking for a network fault.

So the daemon reports the reason on the heartbeat, and it lands here. Four nullable
columns, no backfill: a node that has never sent one has never been blocked as far as we
know, and null is the honest way to say "no report" — a `0`/`""` default would read as a
measurement.

This is **not** an online indicator and must not become one. `agent_runners` still has
no `status` and no `last_seen_at`; online is computed from the connection registry
(ADR 0029 sec 1). What is stored here is the *reason for silence*, which the registry
cannot know.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_runner_pressure"
down_revision: str | None = "0031_node_agent_runner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runners", sa.Column("blocked_reason", sa.String(32), nullable=True))
    op.add_column("agent_runners", sa.Column("disk_used_bytes", sa.BigInteger(), nullable=True))
    op.add_column("agent_runners", sa.Column("disk_quota_bytes", sa.BigInteger(), nullable=True))
    op.add_column(
        "agent_runners", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    for column in ("reported_at", "disk_quota_bytes", "disk_used_bytes", "blocked_reason"):
        op.drop_column("agent_runners", column)
