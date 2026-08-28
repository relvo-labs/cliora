"""the blocked cards move off the stage column, and a witness column so they can move back

Revision ID: 0045_stage_blocked_data
Revises: 0044_provider_ingestion
Create Date: 2026-08-28

`HD-06`, first half (ADR 0040's amendment, `plan/27` D123). **This revision is fully
reversible. `0046` is not, and that is the whole reason they are two files.**

`beta.1` decided (D49) that `stage='blocked'` would only be *projected*, not migrated:
`0043` added `is_blocked` and left the six stage values alone. The cost was written into
the model at the time and is quoted here because it is what this repays:

    "**not the whole truth about being blocked** until `beta.2`'s `HD-06`:
     `stage='blocked'` always projects onto blocked regardless of this column, because
     the platform's three legacy writers still set the stage and not this.
     **Anyone reading this column directly is wrong** about the cards the reaper touched."

A boolean that gives the wrong answer when read is a defect with a scheduled repair date.
This is the date.

**`legacy_blocked_at` is the whole of the reversibility argument.** Without it, `downgrade`
would have to guess which cards to send back to `stage='blocked'` — and guessing which
cards were blocked is the same class of mistake `0043` refused to make when it declined to
guess a previous stage. With it, `downgrade` is a `WHERE` clause.

The column is a **transition**, not a fixture: it is scheduled for removal after `rc`, and
that plan belongs in the release note rather than in a comment nobody re-reads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_stage_blocked_data"
down_revision: str | None = "0044_provider_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The derivation, five rules and not seven — **word for word `0043`'s**, deliberately.
#
# `plan/26/02` §5.2 removed two of the upstream plan's seven because they ask "is this node
# connected right now", and the answer lives in `NodeConnectionRegistry`: a dict inside the
# Central process. `alembic upgrade` runs in a different process that has no registry, and
# ADR 0029 §1 refuses to store a copy. Implementing them literally would not error — it
# would silently never fire, and every card that belonged to them would land on `unknown`,
# making the report longer for a reason nothing states.
#
# Using the same five as `0043` means a card blocked after `0043` gets the same answer a
# card blocked before it got. Two migrations with two derivations would be two answers to
# one question.
_DERIVE = """
UPDATE tasks SET
  is_blocked = true,
  legacy_blocked_at = now(),
  blocking_reason = CASE
    WHEN EXISTS (
      SELECT 1 FROM task_dependencies d
      JOIN tasks blocker ON blocker.id = d.depends_on_task_id
      WHERE d.task_id = tasks.id AND blocker.stage <> 'done'
    ) THEN 'dependency'
    WHEN EXISTS (
      SELECT 1 FROM task_runs r
      WHERE r.task_id = tasks.id AND r.status = 'waiting_for_input'
    ) THEN 'human_input'
    WHEN EXISTS (
      SELECT 1 FROM verification_reports v
      WHERE v.task_id = tasks.id AND v.result = 'failed'
    ) THEN 'verification_failed'
    WHEN EXISTS (
      SELECT 1 FROM jsonb_each(COALESCE(tasks.gates, '{}'::jsonb)) g
      WHERE g.value = 'false'::jsonb
    ) THEN 'gate_unmet'
    ELSE 'unknown'
  END,
  -- **The stage is derived, never guessed at random.** A card that was blocked was
  -- somewhere before it was blocked, and nothing records where. `ready` is the
  -- conservative answer — it is the lane a card re-enters the queue from — and
  -- `0043` chose it for the same reason. What makes it honest rather than a guess is
  -- that `legacy_blocked_at` marks every card this touched, so the choice is
  -- reversible and countable.
  stage = 'ready'
WHERE stage = 'blocked'
"""


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("legacy_blocked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text(_DERIVE))
    # Partial, because the only query that reads it is `downgrade`'s and it wants the
    # non-null rows. An index over 20,000 nulls to find 3,800 values is the wrong shape.
    op.execute(
        "CREATE INDEX ix_tasks_legacy_blocked ON tasks (id) WHERE legacy_blocked_at IS NOT NULL"
    )


def downgrade() -> None:
    """Exactly the cards `upgrade` moved, back to where they were.

    `is_blocked` is cleared for those rows and **only** those rows: a card blocked through
    the new path after this migration ran has no `legacy_blocked_at`, was never on the
    stage, and must not be put there by a downgrade that cannot tell the difference. That
    distinction is the column's entire purpose.
    """
    op.execute(
        sa.text(
            "UPDATE tasks SET stage = 'blocked', is_blocked = false, blocking_reason = NULL "
            "WHERE legacy_blocked_at IS NOT NULL"
        )
    )
    op.execute("DROP INDEX IF EXISTS ix_tasks_legacy_blocked")
    op.drop_column("tasks", "legacy_blocked_at")
