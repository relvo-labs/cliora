"""two verification-command stores, the PR delivery state, the forced-done record, and closing the acceptance-criteria result set

Revision ID: 0036_delivery_and_ac_results
Revises: 0035_delivery_and_verification
Create Date: 2026-08-14

Four groups of changes. **The fourth rewrites existing rows**, which is why it prints
what it changed and why this docstring says so before describing anything else.

**`acceptance_criteria[].result` was a free string.** Nothing validated it: the only
handling was `item.get('result') or '未驗'` when rendering the context pack. The Done
Gate's second condition — "every criterion has a result" — is meaningless against a
free string, because any text at all satisfies it. So the set is closed to four values
first, and the gate is built on top of that afterwards (ADR 0033 §5).

Existing values that are not one of the four become `not_verified`, row by row, and the
count is printed. **`downgrade()` does not restore them.** Keeping the old strings would
need a shadow table that exists permanently for a downgrade that will not happen; the
honest trade is to say so here, because `GATE-DV-MIGRATION-ROUNDTRIP` compares schema
and will not notice.

**`tasks.verification_commands` is a card's own list of checks (ADR 0033 §3b).** It is
deliberately **not** added to `EDITABLE_FIELDS`: it has its own endpoint requiring
`task.approve`, which `RUN_TOKEN_SCOPES` never contains. Reachable through `PATCH`, it
would let the agent being verified choose what verifies it — and every exit code would
stay real while becoming worthless.

**`task_runs.delivery_state` has no CHECK.** Unlike `verification_reports.result`, it is
an internal state machine rather than part of a contract, and its values will grow with
the delivery modes. `task_runs.result` set that precedent and also has none.

**`pushed_branch` is reported by the daemon, not derived by Central.** Central composes
the name and could compute it; only the node knows whether the push succeeded, and a
pull request may only be opened on a branch that exists.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_delivery_and_ac_results"
down_revision: str | None = "0035_delivery_and_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The closed set, and the value an unrecognised one becomes.
VALID_RESULTS = ("passed", "failed", "partial", "not_verified")
UNVERIFIED = "not_verified"


def upgrade() -> None:
    # ① the two verification-command stores, and the project's optional requirement
    op.add_column(
        "projects",
        sa.Column(
            "verification_commands",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "process_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "require_project_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "verification_commands",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # ② how the result left, as three columns rather than one overloaded string
    op.add_column("task_runs", sa.Column("delivery_state", sa.String(length=24), nullable=True))
    op.add_column("task_runs", sa.Column("pushed_branch", sa.String(length=255), nullable=True))
    op.add_column("task_runs", sa.Column("delivery_ref", sa.Text(), nullable=True))
    # The background worker's queue is "rows in this state", so it is indexed on it.
    # Partial, because the states it is not looking for are the overwhelming majority.
    op.create_index(
        "ix_task_runs_pending_delivery",
        "task_runs",
        ["delivery_state"],
        postgresql_where=sa.text("delivery_state = 'pending_pr'"),
    )

    # ③ the forced-done record, on the card as well as on the timeline
    #
    # On the card because ADR 0033 §5 requires it to be visible whenever the card is,
    # and a timeline entry scrolls away. Both, not either: one says "this card is in a
    # forced state", the other says "here is when that happened".
    op.add_column("tasks", sa.Column("force_done_reason", sa.Text(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "force_done_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks", sa.Column("force_done_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ④ close the acceptance-criteria result set — **this rewrites rows**
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, acceptance_criteria FROM tasks "
            "WHERE jsonb_array_length(COALESCE(acceptance_criteria, '[]'::jsonb)) > 0"
        )
    ).fetchall()
    changed_items = 0
    changed_tasks = 0
    for task_id, criteria in rows:
        updated = []
        touched = False
        for item in criteria or []:
            if not isinstance(item, dict):
                # Shape was never validated beyond "a list of objects"; anything else
                # is dropped rather than coerced, because there is no field to keep.
                touched = True
                changed_items += 1
                continue
            if item.get("result") not in VALID_RESULTS:
                item = {**item, "result": UNVERIFIED}
                touched = True
                changed_items += 1
            updated.append(item)
        if touched:
            changed_tasks += 1
            connection.execute(
                sa.text(
                    "UPDATE tasks SET acceptance_criteria = CAST(:value AS jsonb) WHERE id = :id"
                ),
                {"value": json.dumps(updated), "id": task_id},
            )
    # Printed rather than logged: a silent data rewrite is the hardest kind of change to
    # explain afterwards, and this one rewrites the grounds on which cards are called
    # done.
    print(
        f"0036: normalised {changed_items} acceptance-criteria result(s) "
        f"across {changed_tasks} task(s) to '{UNVERIFIED}'"
    )


def downgrade() -> None:
    # The acceptance-criteria normalisation is **not** reversed; see the docstring.
    op.drop_column("tasks", "force_done_at")
    op.drop_column("tasks", "force_done_by")
    op.drop_column("tasks", "force_done_reason")
    op.drop_index("ix_task_runs_pending_delivery", table_name="task_runs")
    op.drop_column("task_runs", "delivery_ref")
    op.drop_column("task_runs", "pushed_branch")
    op.drop_column("task_runs", "delivery_state")
    op.drop_column("tasks", "verification_commands")
    op.drop_column("projects", "require_project_verification")
    op.drop_column("projects", "process_overrides")
    op.drop_column("projects", "verification_commands")
