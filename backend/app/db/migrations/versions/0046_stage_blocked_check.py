"""`blocked` stops being a stage — the first irreversible migration in the V2 series

Revision ID: 0046_stage_blocked_check
Revises: 0045_stage_blocked_data
Create Date: 2026-08-28

`HD-06`, second half (`plan/27` D123). One `ALTER`, and it is separate from `0045` because
**the two have different reversibility and a reader must be able to stop between them.**

    0045   moves the data       fully reversible — `legacy_blocked_at` is the witness
    0046   narrows the domain   the value set comes back; the data does not

## What "not reversible" means here, precisely

`downgrade` restores `'blocked'` to `ck_tasks_stage`, so the schema is identical
afterwards. What cannot be restored is the knowledge of which cards would have been on
that stage: a card blocked *after* this migration went through `is_blocked` and has no
`legacy_blocked_at`, because that column was only filled once, by `0045`, for the rows it
moved. Downgrading leaves those cards `is_blocked = true` with a `stage` of their own —
correct, and invisible to a six-lane board.

**Which is why `HD-07` had to come first.** With `/board` deleted there is no screen that
renders six lanes, so a downgraded deployment shows those cards in their real stage with a
blocked badge. Had the old board still existed, the same downgrade would have hidden them:
`stage='ready'` and no `blocked` column to notice. The dependency between these two tickets
is a real consequence, not an ordering convenience.

## Why the CHECK is narrowed at all

Leaving `'blocked'` in the domain after the data has moved would leave a value that
nothing writes and everything must still handle — the definition of a trap. `LANE_ORDER`,
the read model's projection and every future `WHERE stage = ...` would keep a branch for a
case that cannot occur, and the first person to write a new one would reasonably conclude
the case is live.

`GATE-HD-NO-LEGACY-BLOCKED` scans **all of `backend/app`** for a writer, rather than the
one file `GATE-DV-SINGLE-DONE-PATH` scans. That gate watched `runs.py` for `'done'` and
consequently never saw `run_reaper.py` set `'blocked'` — twice, for three phases.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_stage_blocked_check"
down_revision: str | None = "0045_stage_blocked_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES_AFTER = ("backlog", "ready", "implementing", "verify", "done")
_STAGES_BEFORE = ("backlog", "blocked", "ready", "implementing", "verify", "done")


def _in(values: Sequence[str]) -> str:
    return "stage IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    # A last sweep before narrowing. `0045` moved everything that existed then; a
    # deployment that ran `0045`, served traffic for a week and then ran `0046` may have
    # acquired more from the legacy writers in between. Without this the `ALTER` fails on
    # a constraint violation naming a table and no reason — the least useful moment for a
    # migration to be terse.
    op.execute(
        sa.text(
            "UPDATE tasks SET stage = 'ready', is_blocked = true, "
            "blocking_reason = COALESCE(blocking_reason, 'unknown'), "
            "legacy_blocked_at = COALESCE(legacy_blocked_at, now()) "
            "WHERE stage = 'blocked'"
        )
    )
    # **Dropped by whichever name exists, in raw SQL, and that is not defensiveness.**
    #
    # `0023` created this constraint inside a `create_table` with `name="ck_tasks_stage"`,
    # and the metadata naming convention `ck_%(table_name)s_%(constraint_name)s` expanded
    # it — so on every database built by the migration chain the live name is
    # **`ck_tasks_ck_tasks_stage`**. An `op.drop_constraint(...)` here re-applies the same
    # convention to whatever string it is given, which means neither `"stage"` nor
    # `"ck_tasks_stage"` names the thing reliably:
    #
    #     drop_constraint("stage")           → ck_tasks_stage            (does not exist)
    #     drop_constraint("ck_tasks_stage")  → ck_tasks_ck_tasks_stage   (exists)
    #
    # The first version of this migration used the second form, was "corrected" to the
    # first after it failed on a database that had **already run an earlier attempt** —
    # and that database had the un-doubled name precisely *because* of that attempt. The
    # migration therefore worked only where it had already run. `HD-08`'s rehearsal, which
    # builds the chain from empty, is what found it; nothing in the test suite could,
    # because the suite's database was migrated incrementally too.
    #
    # Raw SQL with both names and `IF EXISTS` ends the ambiguity: the statement says what
    # it drops, and no convention is applied to it on the way.
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_ck_tasks_stage")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_stage")
    # Recreated with the undoubled name, also explicitly. From here the constraint has one
    # name on every deployment, which is what `test_stage_sunset.py` reads.
    op.execute(f"ALTER TABLE tasks ADD CONSTRAINT ck_tasks_stage CHECK ({_in(_STAGES_AFTER)})")


def downgrade() -> None:
    """The value set comes back. **The data does not, and that is not a defect to fix.**

    Restoring which cards "would have been" on `stage='blocked'` would mean deriving it
    from `is_blocked`, which is exactly the conflation this migration removed: `is_blocked`
    is true for cards that were never on that stage. A downgrade that guessed would undo
    the distinction it is supposed to be preserving.
    """
    # Same two names, same reason. A downgraded database keeps the undoubled name rather
    # than being restored to `0023`'s doubled one: the name is not what `0023` promised —
    # the *value set* is — and re-doubling it would leave a database that no later
    # migration can find by either spelling.
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_ck_tasks_stage")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_stage")
    op.execute(f"ALTER TABLE tasks ADD CONSTRAINT ck_tasks_stage CHECK ({_in(_STAGES_BEFORE)})")
