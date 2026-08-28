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
    # **`"stage"`, not `"ck_tasks_stage"`.** The metadata naming convention expands a
    # check constraint's name to `ck_<table>_<name>`, and alembic applies that to `drop`
    # as well — passing the rendered name asks PostgreSQL for `ck_tasks_ck_tasks_stage`,
    # which does not exist. The live constraint is `ck_tasks_stage`, and the input that
    # produces that name here is `stage`. `0044` hit the identical trap an hour earlier
    # on `knowledge_sources`; two migrations in one phase is enough to call it a property
    # of this codebase rather than a slip.
    op.drop_constraint("stage", "tasks", type_="check")
    op.create_check_constraint("stage", "tasks", _in(_STAGES_AFTER))


def downgrade() -> None:
    """The value set comes back. **The data does not, and that is not a defect to fix.**

    Restoring which cards "would have been" on `stage='blocked'` would mean deriving it
    from `is_blocked`, which is exactly the conflation this migration removed: `is_blocked`
    is true for cards that were never on that stage. A downgrade that guessed would undo
    the distinction it is supposed to be preserving.
    """
    op.drop_constraint("stage", "tasks", type_="check")
    op.create_check_constraint("stage", "tasks", _in(_STAGES_BEFORE))
