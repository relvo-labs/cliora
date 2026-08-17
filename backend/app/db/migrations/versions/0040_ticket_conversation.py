"""a message sequence, a question's life, a consumer's cursor, and a run that has a parent

Revision ID: 0040_ticket_conversation
Revises: 0039_requirements_agent_driven
Create Date: 2026-08-16

`CV-03` / `FR-CONV-001`…`-010` (ADR 0035, 0036, 0037, 0041). **Additive: no existing
column's value is rewritten**, which is what makes the downgrade clean — unlike `0033`
and `0036`, both of which tightened data already in the table.

The phase this belongs to is the one that stops a conversation from depending on an
operating-system process staying alive. Three of the four things added here exist for
that: a sequence a cursor can trust, a question that is a row rather than a pattern
over messages, and a run that knows which run it continues.

**Two things this migration deliberately does not do.**

It does not rewrite `task_messages.kind`. V2.5 wrote `message` and `event`; V2-C1
writes `comment` and `system`, and the two old spellings are mapped on read at the one
place the DTO is assembled (ADR 0035 §8). A whole-table `UPDATE` on a table `audit_logs`
references, in order to change a display string, is a worse trade than two lines — and
it would contradict `GATE-CV-APPEND-ONLY`, which says this table has no update path
while the migration performed one.

It does not add an expiry to messages. A run log expires and an artifact does not; a
message is the third case and it is the one that never does (ADR 0041 §1). The exit
criterion "delete every `run_log` row for a card and the conversation survives" is
that sentence in executable form, and a retention column would contradict it.

**Backfill order matters and the reason is subtle.** `conversation_seq` is filled in
`(created_at, id)` order, which is the order `MessageService.list_for` already reads
in. The second key is not decoration: two messages sharing a `created_at` are exactly
the case that made `--since` pagination lose or repeat a row, so the backfill has to
break that tie the same way every reader already does.

Historical questions are reconstructed with the **V2.5 predicate** — any later message
whose `author_kind` is `user` closes a question — rather than the new one. A card must
not change its mind about which questions are answered because it was upgraded
(`plan/23` D61). One user message may close two historical questions, so
`answered_message_id` carries no unique constraint.

**Four of the seven foreign keys close loops** and are therefore named and marked
`use_alter` on the model, the same treatment `0039` gave the specification cycle:
`task_messages` → `task_questions` → `task_messages`, and `task_runs` → `task_runs`
twice over. SQLAlchemy cannot sort a cycle for `create_all`; PostgreSQL never cared.

`uq_task_runs_continuation` is the one constraint here that should never fire. Its
job is that a code path which reaches continuation without going through the question
CAS fails loudly, because that bug has no other symptom — the system keeps working and
somebody's agent answers twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_ticket_conversation"
down_revision: str | None = "0039_requirements_agent_driven"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `VARCHAR` plus a CHECK plus a service-layer closed set, not a PostgreSQL ENUM — the
# same choice `tasks.stage`, `tasks.card_kind` and `verification_reports.result` made.
_QUESTION_STATES = ("open", "answered", "cancelled", "expired")


def upgrade() -> None:
    # ① the card's message counter and the two projections the board reads
    op.add_column(
        "tasks",
        sa.Column(
            "conversation_seq", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "open_question_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column("tasks", sa.Column("waiting_for_actor", sa.String(length=16), nullable=True))

    # ② the message columns. `conversation_seq` arrives nullable and is tightened after
    #    the backfill; everything else is nullable for good.
    op.add_column("task_messages", sa.Column("conversation_seq", sa.Integer(), nullable=True))
    op.add_column(
        "task_messages",
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_messages.id",
                ondelete="SET NULL",
                name="fk_task_messages_reply_to_message_id",
            ),
            nullable=True,
        ),
    )
    # The FK for `question_id` is added at the end, once `task_questions` exists.
    op.add_column(
        "task_messages", sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "task_messages", sa.Column("idempotency_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "task_messages",
        sa.Column(
            "turn_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_runs.id", ondelete="SET NULL", name="fk_task_messages_turn_run_id"
            ),
            nullable=True,
        ),
    )

    # ③ the run columns. `resumed_question_id`'s FK also waits for `task_questions`.
    op.add_column(
        "task_runs",
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL", name="fk_task_runs_parent_run_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "task_runs",
        sa.Column(
            "root_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL", name="fk_task_runs_root_run_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "task_runs", sa.Column("resumed_question_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "task_runs",
        sa.Column("turn_seq", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("task_runs", sa.Column("input_from_seq", sa.Integer(), nullable=True))
    op.add_column("task_runs", sa.Column("input_to_seq", sa.Integer(), nullable=True))

    # ④ a question's life
    op.create_table(
        "task_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE", name="fk_task_questions_task_id"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL", name="fk_task_questions_run_id"),
            nullable=True,
        ),
        sa.Column(
            "asked_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_messages.id",
                ondelete="CASCADE",
                name="fk_task_questions_asked_message_id",
            ),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "answered_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "task_messages.id",
                ondelete="SET NULL",
                name="fk_task_questions_answered_message_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('%s')" % "','".join(_QUESTION_STATES),
            name="state",
        ),
    )
    # Two partial indexes. A card's lifetime may hold dozens of questions and at most
    # one of them is open at a time, so a full index would index rows nothing reads.
    op.create_index(
        "ix_task_questions_open",
        "task_questions",
        ["task_id"],
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index(
        "ix_task_questions_expiry",
        "task_questions",
        ["created_at"],
        postgresql_where=sa.text("state = 'open'"),
    )

    # ⑤ a consumer's cursor
    op.create_table(
        "conversation_consumers",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE", name="fk_conversation_consumers_task_id"),
            primary_key=True,
        ),
        sa.Column("consumer_type", sa.String(length=16), primary_key=True),
        # No foreign key, on purpose — see the model docstring.
        sa.Column("consumer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "last_delivered_seq", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_acked_seq", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "last_acked_seq <= last_delivered_seq", name="order"
        ),
    )

    # ⑥ the two loop-closing foreign keys, now that both ends exist
    op.create_foreign_key(
        "fk_task_messages_question_id",
        "task_messages",
        "task_questions",
        ["question_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_task_runs_resumed_question_id",
        "task_runs",
        "task_questions",
        ["resumed_question_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ⑦ backfill: sequence numbers, then the card counters
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY created_at, id) AS seq
            FROM task_messages
        )
        UPDATE task_messages m
        SET conversation_seq = ordered.seq
        FROM ordered
        WHERE m.id = ordered.id
        """
    )
    op.execute(
        """
        UPDATE tasks t
        SET conversation_seq = COALESCE(
            (SELECT MAX(conversation_seq) FROM task_messages WHERE task_id = t.id), 0)
        """
    )

    # ⑧ backfill: historical questions, using V2.5's own predicate
    op.execute(
        """
        INSERT INTO task_questions (
            id, task_id, run_id, asked_message_id, state,
            answered_message_id, created_at, answered_at)
        SELECT gen_random_uuid(), q.task_id, q.run_id, q.id,
               CASE WHEN a.id IS NULL THEN 'open' ELSE 'answered' END,
               a.id, q.created_at, a.created_at
        FROM task_messages q
        LEFT JOIN LATERAL (
            SELECT m.id, m.created_at
            FROM task_messages m
            WHERE m.task_id = q.task_id
              AND m.author_kind = 'user'
              AND (m.created_at, m.id) > (q.created_at, q.id)
            ORDER BY m.created_at, m.id
            LIMIT 1
        ) a ON TRUE
        WHERE q.kind = 'question'
        """
    )
    op.execute(
        """
        UPDATE task_messages m
        SET question_id = q.id
        FROM task_questions q
        WHERE q.answered_message_id = m.id
        """
    )
    op.execute(
        """
        UPDATE tasks t SET
            open_question_count = COALESCE((
                SELECT COUNT(*) FROM task_questions
                WHERE task_id = t.id AND state = 'open'), 0),
            waiting_for_actor = CASE
                WHEN EXISTS (SELECT 1 FROM task_questions
                             WHERE task_id = t.id AND state = 'open')
                THEN 'human' ELSE NULL END
        """
    )

    # ⑨ every existing run is its own root
    op.execute("UPDATE task_runs SET root_run_id = id")

    # ⑩ constraints and indexes, after the data is in shape
    op.alter_column("task_messages", "conversation_seq", nullable=False)
    op.create_index(
        "uq_task_messages_seq", "task_messages", ["task_id", "conversation_seq"], unique=True
    )
    op.create_index(
        "uq_task_messages_idem",
        "task_messages",
        ["task_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    # Descending, because the commonest read is "the last fifty"; the cursor's
    # `conversation_seq > ?` walks the same tree at the same cost either way.
    op.create_index(
        "ix_task_messages_task_seq",
        "task_messages",
        ["task_id", sa.text("conversation_seq DESC")],
    )
    op.create_index(
        "ix_task_runs_parent",
        "task_runs",
        ["parent_run_id"],
        postgresql_where=sa.text("parent_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_task_runs_continuation",
        "task_runs",
        ["parent_run_id", "resumed_question_id"],
        unique=True,
        postgresql_where=sa.text("parent_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_task_runs_continuation", table_name="task_runs")
    op.drop_index("ix_task_runs_parent", table_name="task_runs")
    op.drop_index("ix_task_messages_task_seq", table_name="task_messages")
    op.drop_index("uq_task_messages_idem", table_name="task_messages")
    op.drop_index("uq_task_messages_seq", table_name="task_messages")

    op.drop_constraint("fk_task_runs_resumed_question_id", "task_runs", type_="foreignkey")
    op.drop_constraint("fk_task_messages_question_id", "task_messages", type_="foreignkey")

    op.drop_table("conversation_consumers")
    op.drop_index("ix_task_questions_expiry", table_name="task_questions")
    op.drop_index("ix_task_questions_open", table_name="task_questions")
    op.drop_table("task_questions")

    for column in (
        "input_to_seq",
        "input_from_seq",
        "turn_seq",
        "resumed_question_id",
        "root_run_id",
        "parent_run_id",
    ):
        op.drop_column("task_runs", column)
    for column in (
        "turn_run_id",
        "idempotency_key",
        "question_id",
        "reply_to_message_id",
        "conversation_seq",
    ):
        op.drop_column("task_messages", column)
    for column in ("waiting_for_actor", "open_question_count", "conversation_seq"):
        op.drop_column("tasks", column)
