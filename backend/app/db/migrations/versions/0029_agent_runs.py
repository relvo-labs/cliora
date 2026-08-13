"""the agent runner layer: runners, repositories, runs, logs, messages, artifacts
and the run credential; plus two foreign keys 0023 deliberately left open

Revision ID: 0029_agent_runs
Revises: 0028_node_removal_sessions
Create Date: 2026-08-11

AR-03 (FR-AGENT-001, 003…013; ADR 0029/0030/0031; plan/18/02-…md). Eight new tables.
No existing column changes type, nullability or default — the only edits to existing
tables are two constraints, and both were promised in 0023's own docstring.

Five decisions are in the DDL rather than only in the plan, because each is the kind
of thing a later reader would tidy away:

* **`agent_runners` is unique on `node_id`, and `runtimes` is a set.** The upstream
  plan said a node could run several runners, one per runtime. On one WebSocket that
  immediately raises "which row is online", and the answer is always the node — so
  the column would be a fake indicator light (ADR 0029 sec 1). There is deliberately
  no `status` and no `last_seen_at` here either; both would be second copies of the
  node's own state, and a second copy is a copy that can go stale.
* **`project_repositories` stores the URL as three columns, not one string.**
  `runner.git.allowed_hosts` compares `host` exactly, and parsing a host out of a
  free-form string is how `https://github.com@evil.example/` gets accepted. Split
  this way, **userinfo is not representable at all** — which is the schema form of
  ADR 0031's rule against tokens in remote URLs.
* **`task_runs` has no `workspace_node_id` and no `workspace_path`.** This is the
  most important absent column in the phase. While it exists, somebody will join it
  to `project_workspaces`, and that join is the first step to the run directory and
  the user's allowed roots sharing an authorization model (ADR 0031 sec 6).
* **Artifact metadata and artifact bytes are two tables.** Listing ten artifacts must
  not be able to pull 100 MB into memory; splitting makes that mistake unavailable
  rather than merely discouraged (ADR 0030 Part B).
* **`run_logs` rows are aggregated segments, not chunks.** Central buffers 64 KiB or
  two seconds before writing, so `seq` skips — it is a sort key, not a counter, the
  same property `card_ref` has.

`project_agents` is **not** created. It arrives in V2.3 alongside `project_secrets`,
because binding a runner to a project is what authorises that runner to read the
project's secrets. Creating an authorization table that authorises nothing now would
cost V2.3's security review a real checkpoint: it would see "the table already
exists" instead of "this is a new authorization boundary" (plan/18/02-…md §2.2).

> **Note added 2026-08-13.** The paragraph above is left as written because a
> migration is a historical record, but its forecast did not hold: the 2026-08-12
> ruling **cancelled** `project_agents` rather than deferring it. The authorization
> boundary is permanently enrollment, pairing is tags plus an optional named runner,
> and the security review checks four compensating controls instead of a table
> (ADR 0032 §0). The decision not to create the table here was still the right one —
> only the reason has changed from "not yet" to "not at all".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_agent_runs"
down_revision: str | None = "0028_node_removal_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_STATUSES = (
    "queued",
    "claimed",
    "running",
    "waiting_for_input",
    "succeeded",
    "failed",
    "lost",
    "cancelled",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # --- agent_runners --------------------------------------------------------
    op.create_table(
        "agent_runners",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        # Only the runtimes this node reports as *runner capable* — a machine with
        # codex installed but no detectable non-interactive interface registers with
        # an empty set and never matches a card. That is deliberate: a failed
        # registration reads as "the machine is broken", while an empty set plus the
        # reason on the Agents page reads as what it is (ADR 0029 sec 7).
        sa.Column(
            "runtimes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        # Displayed and **not compared** in V2.2 — label matching is V2.3. Stored now
        # because the daemon already reports them and dropping the value would make
        # the console lie about what the node said.
        sa.Column(
            "labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="1"),
        # A second limit, because a `waiting_for_input` run holds no process and must
        # not occupy execution capacity (ADR 0029 sec 5). Without it, three runs
        # waiting on a human would take a node offline for work.
        sa.Column("max_waiting", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # A *posture report*, like `nodes.agent_runner` and the codex sandbox flag:
        # the daemon sets it from `len(workspace.allowed_roots) == 0`. The platform
        # has no technical isolation between a run and the node's allowed roots
        # (ADR 0031 sec 6); on a node with no allowed roots, "the run cannot read
        # one" is vacuously true. This column is what turns mixed use into a visible
        # ⚠ in the console instead of a sentence in a runbook nobody verifies.
        sa.Column("dedicated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("node_id", name="uq_agent_runners_node"),
    )

    # --- project_repositories -------------------------------------------------
    op.create_table(
        "project_repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheme", sa.String(length=8), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        # RESTRICT, like `projects.owner_user_id`: registering a repository is a
        # decision, and someone leaving must not take the record of who made it.
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "host", "path", name="uq_project_repositories_identity"),
        # CHECK rather than a PostgreSQL enum, matching `tasks.stage`: `ALTER TYPE` is
        # the one schema change that cannot be rolled back inside a transaction.
        sa.CheckConstraint("scheme IN ('https', 'ssh')", name="ck_project_repositories_scheme"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_repositories_project "
        "ON project_repositories (project_id);"
    )

    # --- task_runs ------------------------------------------------------------
    op.create_table(
        "task_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalised, and it cannot drift: `tasks.project_id` is immutable (there is
        # no move-card API). Three paths want it without joining `tasks` — the run
        # token's resource check, the artifact quota, and V2.3's eligibility query
        # once binding returns.
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Set by exactly one statement in the whole codebase: the atomic claim
        # (`UPDATE … WHERE id = … AND runner_id IS NULL`). `GATE-AR-SINGLE-CLAIM`
        # asserts that by scanning for a second write site.
        sa.Column(
            "runner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runners.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        # A **snapshot** of the card's assignment, not a live read of
        # `tasks.assigned_runner_id`. A re-queue must keep the original assignment
        # (ADR 0029 sec 3) while the card itself stays editable mid-run; editing the
        # card affects the *next* dispatch. This has its own test, because without one
        # "a re-queue keeps the assignment" fails silently the first time somebody
        # edits a card while its run is in flight.
        sa.Column(
            "assigned_runner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runners.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Snapshotted at dispatch for the same reason.
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(length=16), nullable=True),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        # Reported by the runner once the worktree exists (`run.progress`,
        # phase `checked_out`), so the Run detail page can answer "which version of
        # the code did this run actually execute".
        sa.Column("commit_sha", sa.CHAR(length=40), nullable=True),
        # Reported at completion. Also M12's data source in production.
        sa.Column("disk_bytes", sa.BigInteger(), nullable=True),
        sa.Column("runtime", sa.String(length=32), nullable=True),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True),
        # **Not the lease.** The lease answers "is the runner alive"; this answers
        # "is the child making progress", and the idle decision is taken on the daemon
        # side, where the event stream is. This column exists so the Run detail page
        # can say "last activity: 3 minutes ago" (ADR 0029 sec 4). Best-effort, like
        # `session_tokens.last_used_at`.
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        # Two counters, not one: exit condition 14 requires the truncated byte count
        # to be stated, and "bytes received" cannot answer "bytes dropped".
        sa.Column("log_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("log_truncated_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        # On `task_runs` rather than on `run_logs`: it is a property of the run (did it
        # succeed), so every log row of one run shares the answer. Storing it per row
        # would be the same value copied N times.
        sa.Column("logs_expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "seq", name="uq_task_runs_task_seq"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in RUN_STATUSES) + ")",
            name="ck_task_runs_status",
        ),
    )
    # Three indexes, one per real query, and no fourth — 0023's rule: a speculative
    # index is a write cost with no reader.
    #
    # The first two are partial because both paths run every second (poll and the
    # lease sweep) while the overwhelming majority of rows are in a terminal state.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_runs_queue ON task_runs (status, queued_at) "
        "WHERE status = 'queued';"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_runs_lease ON task_runs (lease_expires_at) "
        "WHERE status IN ('claimed', 'running', 'waiting_for_input');"
    )
    # No condition on this one: a card shows its whole run history.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_runs_task ON task_runs (task_id, seq DESC);"
    )

    # --- run_logs -------------------------------------------------------------
    op.create_table(
        "run_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # CASCADE is the safety net; the normal path is the retention sweep, which
        # deletes a run's rows as a group. Half a run's log is harder to explain than
        # none of it.
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        # JSONL event lines plus stderr, never terminal bytes — the chunker is
        # forbidden from splitting a JSON line, because half an event cannot be
        # rendered and "do not split a line" outranks "fill 32 KiB" (ADR 0030 Part A).
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_logs_run_seq"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_run_logs_run ON run_logs (run_id, seq);")

    # --- task_messages --------------------------------------------------------
    op.create_table(
        "task_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL rather than CASCADE: a run's record may be reclaimed on a retention
        # schedule, but **the conversation on a card is product content with no
        # retention** — the same rule `activity_events` follows.
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Two explicit author columns rather than one polymorphic id, for the reason
        # `activity_events.actor_kind` documents: `author_id IS NULL` already means
        # "the system", and giving that NULL a second meaning makes both unreadable.
        sa.Column("author_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "author_runner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runners.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        # `question` is distinguished from `message` so the board can render "waiting
        # for your reply" from the thread alone, without consulting run state for each
        # of several dozen cards.
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="message"),
        sa.Column("event_kind", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "author_kind IN ('user', 'agent', 'system')", name="ck_task_messages_author_kind"
        ),
        # "A user message always names a user" belongs in the schema, not in the
        # service that happens to write it today.
        sa.CheckConstraint(
            "(author_kind = 'user') = (author_user_id IS NOT NULL)",
            name="ck_task_messages_user_author",
        ),
    )
    # `id` as the third key so `cliora task messages --since <ts>` pages stably: two
    # messages in the same millisecond must not be able to swap order between pages.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_messages_task "
        "ON task_messages (task_id, created_at, id);"
    )

    # --- task_artifacts + task_artifact_blobs ---------------------------------
    op.create_table(
        "task_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalised so the project quota is `SUM(size) WHERE project_id = ?` over
        # its own index, with no join to `tasks`.
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        # **Server-determined**, never the uploader's declaration: extension plus
        # magic bytes, and anything outside a closed table is stored as
        # `application/octet-stream`. This cell is the primary stored-XSS entry point
        # (ADR 0030 Part B).
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        # Not for deduplication — attaching the same file twice is two artifacts, and
        # the timeline shows that as versions. It is for verification on download.
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("storage_ref", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_by_runner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runners.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Soft delete, because deletion needs `project.manage` **and a reason**, and a
        # hard delete would erase who deleted it and why — which is the whole point of
        # requiring a reason. The bytes, in contrast, are deleted for real (see the
        # blob table): otherwise "delete something" would not be a real answer to a
        # full quota. Metadata stays, content goes (ADR 0030 Part B).
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "uploaded_by_kind IN ('user', 'agent')", name="ck_task_artifacts_uploader_kind"
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_artifacts_task "
        "ON task_artifacts (task_id, created_at DESC) WHERE deleted_at IS NULL;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_artifacts_project "
        "ON task_artifacts (project_id) WHERE deleted_at IS NULL;"
    )
    op.create_table(
        "task_artifact_blobs",
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_artifacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bytes", postgresql.BYTEA(), nullable=False),
    )

    # --- run_tokens -----------------------------------------------------------
    op.create_table(
        "run_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # The whole reason this table exists rather than reusing `session_tokens`:
        # that table's `session_id` is NOT NULL against `terminal_sessions`, and exit
        # condition 12 forbids a run from having a session row (ADR 0029 sec 6).
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Stored rather than joined: every CLI call checks "does this card belong to
        # this run", and the run↔task relation is immutable.
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Same three properties as `session_tokens`: only the HMAC is stored (same
        # `CLIORA_TOKEN_PEPPER`, same construction), `scopes` is snapshotted at issue
        # time, and revoked rows are kept 90 days because the audit trail names a
        # token id and that name has to stay resolvable.
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        # There is deliberately **no `issued_by`**: a run is not opened by a person.
        # Who dispatched it is `task_runs.created_by`, one join away; copying it here
        # would give "who holds this token" a second, plausible, wrong answer.
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_run_tokens_hash"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_run_tokens_run ON run_tokens (run_id);")

    # --- the two foreign keys 0023 left open ----------------------------------
    # 0023 wrote: "No foreign key: `agent_runners` arrives in V2.2,
    # `project_repositories` in V2.3. Each phase adds its own constraint when the
    # table lands." Both tables land here — the 2026-08-10 ruling moved
    # `project_repositories` forward — so both constraints are added here.
    #
    # **Existing values must be cleared first, and none of them can be meaningful.**
    # Both columns have been settable through `PATCH /api/tasks/{id}` since V2.1 while
    # neither target table existed, so every non-null value is a UUID that resolves to
    # nothing. Nulling them is not data loss; leaving them would either fail this
    # migration or leave a dangling pointer that `POST /dispatch` dereferences.
    op.execute("UPDATE tasks SET assigned_runner_id = NULL WHERE assigned_runner_id IS NOT NULL;")
    op.execute("UPDATE tasks SET repository_id = NULL WHERE repository_id IS NOT NULL;")
    op.create_foreign_key(
        "fk_tasks_assigned_runner_id",
        "tasks",
        "agent_runners",
        ["assigned_runner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tasks_repository_id",
        "tasks",
        "project_repositories",
        ["repository_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_repository_id", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_assigned_runner_id", "tasks", type_="foreignkey")

    # Reverse foreign-key order, so nothing is dropped while something still points
    # at it.
    op.execute("DROP INDEX IF EXISTS ix_run_tokens_run;")
    op.drop_table("run_tokens")
    op.drop_table("task_artifact_blobs")
    op.execute("DROP INDEX IF EXISTS ix_task_artifacts_project;")
    op.execute("DROP INDEX IF EXISTS ix_task_artifacts_task;")
    op.drop_table("task_artifacts")
    op.execute("DROP INDEX IF EXISTS ix_task_messages_task;")
    op.drop_table("task_messages")
    op.execute("DROP INDEX IF EXISTS ix_run_logs_run;")
    op.drop_table("run_logs")
    op.execute("DROP INDEX IF EXISTS ix_task_runs_task;")
    op.execute("DROP INDEX IF EXISTS ix_task_runs_lease;")
    op.execute("DROP INDEX IF EXISTS ix_task_runs_queue;")
    op.drop_table("task_runs")
    op.execute("DROP INDEX IF EXISTS ix_project_repositories_project;")
    op.drop_table("project_repositories")
    op.drop_table("agent_runners")
