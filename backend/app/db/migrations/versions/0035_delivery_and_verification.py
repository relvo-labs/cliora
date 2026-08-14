"""execution_plans, verification_reports and evidence_items: what a card did and why it counts as done

Revision ID: 0035_delivery_and_verification
Revises: 0034_seed_secret_action
Create Date: 2026-08-14

Three tables in one revision because they are one answer read three ways: the plan is
what was going to happen, the report is what the checks said, the evidence is what was
observed. Splitting them across revisions would let a deployment sit in a state where a
card can be judged on two of the three (ADR 0033 §5).

**All three are append-only, and nothing here enforces it.** No `updated_at`, no
trigger, no rule. Append-only is their entire integrity property — they are the grounds
on which a card claims to be finished, and grounds that can be rewritten in place are
not grounds — so it is guarded where it can actually be checked: the repository layer
has no `update()` against them and `GATE-DV-APPEND-ONLY` scans for one. A trigger was
considered and would have been the wrong instrument: it fires on the statement, so the
first legitimate correction turns into a database error nobody can act on, and somebody
drops the trigger rather than reading it.

**`project_id` is redundant on all three and deliberate.** `task_id` determines it, but
the five cross-project metrics aggregate over these tables and every one of them would
otherwise join `tasks`. `task_artifacts` set this precedent in V2.2 for the same reason.

**Two CHECKs on `verification_reports`, none on `execution_plans.steps`.** `result` and
`source` are columns whose value sets are part of the contract — the Done Gate and three
metrics read them, and a wrong `source` renders an agent's self-report as a machine
fact, which is exactly what ADR 0033 §3b exists to prevent. `steps[].status` lives
inside a JSONB array, where the same constraint would be an expression nobody can read;
it is validated in the service layer, the way `acceptance_criteria` already is.

**`origin` is not a column here.** It rides inside `checks[]` and inside an evidence
payload, because it qualifies one check rather than a whole report: a single run can
produce project-declared and card-declared checks together (ADR 0033 §3b).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_delivery_and_verification"
down_revision: str | None = "0034_seed_secret_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES = "('agent_reported', 'platform_observed', 'machine_verified')"
_EVIDENCE_KINDS = (
    "('git_state', 'changed_files', 'diff_stat', 'command_result', "
    "'run_event', 'delivery', 'agent_finding', 'agent_limitation', 'agent_risk')"
)


def _actor_columns(prefix: str) -> list[sa.Column]:
    """Who wrote this row, in the three-column shape the rest of V2 already uses.

    A user id and a runner id rather than one polymorphic column, and a `_kind`
    discriminator beside them: `task_messages` and `task_artifacts` are shaped this way,
    and the reason is that a foreign key that sometimes points at `users` and sometimes
    at `agent_runners` is a foreign key to neither.
    """
    return [
        sa.Column(f"{prefix}_kind", sa.String(length=16), nullable=False),
        sa.Column(
            prefix,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            f"{prefix}_runner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runners.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # `SET NULL` rather than `CASCADE`: a run's logs expire and a run row may be
        # reaped, and losing the plan with it would delete the record of what somebody
        # intended to do because the diagnostic aged out.
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        # Required from seq 2 onward, and that rule is in the service layer: as a CHECK
        # it would surface the difference between a first plan and a revision as an
        # unreadable database error.
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_actor_columns("created_by"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("task_id", "seq", name="uq_execution_plans_task_seq"),
    )
    op.create_index(
        "ix_execution_plans_task", "execution_plans", ["task_id", sa.text("seq DESC")]
    )

    op.create_table(
        "verification_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=16), nullable=False),
        # `checks[]` items carry `origin` (project | card) beside `name`, `argv`,
        # `exit_code`, `duration_ms` and `output_tail`.
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # The report's own snapshot of the criteria, which may disagree with the card's
        # current values. That is not a defect: the report says what this run saw, the
        # card says what is true now, and merging them would let an old run's report
        # move the card's state backwards (ADR 0033 §5).
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "remaining_risks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("completion_summary", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        *_actor_columns("reported_by"),
        sa.Column(
            "reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "result IN ('not_started', 'running', 'passed', 'failed', 'partial')",
            name="ck_verification_reports_result",
        ),
        sa.CheckConstraint(f"source IN {_SOURCES}", name="ck_verification_reports_source"),
    )
    op.create_index(
        "ix_verification_reports_task",
        "verification_reports",
        ["task_id", sa.text("reported_at DESC")],
    )

    op.create_table(
        "evidence_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        *_actor_columns("written_by"),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"kind IN {_EVIDENCE_KINDS}", name="ck_evidence_items_kind"),
        sa.CheckConstraint(f"source IN {_SOURCES}", name="ck_evidence_items_source"),
    )
    op.create_index(
        "ix_evidence_items_task", "evidence_items", ["task_id", sa.text("collected_at DESC")]
    )
    op.create_index("ix_evidence_items_run", "evidence_items", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_items_run", table_name="evidence_items")
    op.drop_index("ix_evidence_items_task", table_name="evidence_items")
    op.drop_table("evidence_items")
    op.drop_index("ix_verification_reports_task", table_name="verification_reports")
    op.drop_table("verification_reports")
    op.drop_index("ix_execution_plans_task", table_name="execution_plans")
    op.drop_table("execution_plans")
