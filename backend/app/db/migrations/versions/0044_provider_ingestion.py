"""two source types that Cliora did not cause, and the four columns that poll for them

Revision ID: 0044_provider_ingestion
Revises: 0043_work_views_and_rank
Create Date: 2026-08-28

`HD-01` / `FR-PROV-001`…`-004` (ADR 0043). Entirely additive and fully reversible.

**No new table.** A pull request and a published version are `knowledge_sources` rows,
their text lives in `knowledge_chunks`, and their work lives in `knowledge_jobs`. A table
of their own would have needed its own cascade rules, its own isolation suite and its own
retention answer — three questions ADR 0038 answered once, and answering them twice is how
two subsystems end up disagreeing about what deleting a project means.

**The `source_type` CHECK is on two tables, and missing the second one is the trap this
migration exists to not fall into.** `0042` put an identical constraint on
`knowledge_sources` and on `knowledge_jobs`. Extending only the first produces a system
that stores a provider source happily and then refuses to enqueue the job that would
refresh it — at 3 a.m., in a worker, with a constraint violation naming a table nobody was
thinking about. `plan/27/11` §2 listed it as one of three predicted silent traps before
any of this was written.

**Downgrade deletes rows, and says so.** `0044` down removes every source whose type is
one of the two new values, because the CHECK cannot be narrowed while a row violates it.
The rows are recoverable — one reconcile pass rebuilds them from the provider — which is
the property that makes this deletion acceptable and is worth stating rather than assuming.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_provider_ingestion"
down_revision: str | None = "0043_work_views_and_rank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The eight `0042` shipped with, plus the two whose trigger is somebody else's server.
_SOURCE_TYPES_BEFORE = (
    "policy",
    "ticket",
    "conversation",
    "decision",
    "artifact",
    "verification",
    "repo_doc",
    "activity",
)
_ADDED = ("pull_request", "release")
_SOURCE_TYPES_AFTER = _SOURCE_TYPES_BEFORE + _ADDED

# Both tables. Named as a pair so that a future third type cannot be added to one of them:
# the loop below is the whole of the change, and there is no place to put a single table.
_TABLES_WITH_SOURCE_TYPE = ("knowledge_sources", "knowledge_jobs")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    for table in _TABLES_WITH_SOURCE_TYPE:
        # **The bare name here is correct, and `0046` is where the same reasoning went
        # wrong** — worth stating together because the two look identical and are not.
        #
        # `0042` created these with `name="source_type"`, which the naming convention
        # expanded to `ck_<table>_source_type`. Passing `"source_type"` to `drop` applies
        # the same expansion and names the same thing. `0023` created the *stage* check
        # with `name="ck_tasks_stage"` — already prefixed — so the same expansion there
        # produces `ck_tasks_ck_tasks_stage`, and the bare-name form misses it.
        #
        # The rule is not "always pass the bare name". It is "pass whatever the creating
        # migration passed", and the only way to know that is to read it. `0046` uses raw
        # SQL with `IF EXISTS` rather than trusting either reading.
        op.drop_constraint("source_type", table, type_="check")
        op.create_check_constraint("source_type", table, _in("source_type", _SOURCE_TYPES_AFTER))

    # Per project, not per deployment. D52's argument about knowledge applies unchanged:
    # the cost and the risk of talking to somebody else's API are properties of a project,
    # and a deployment-wide switch cannot say "this project, not that one".
    op.add_column(
        "projects",
        sa.Column(
            "provider_sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # The reconcile cursor. Also the rate ceiling's only input: how many times this moved
    # in the last hour *is* how many rounds were spent on this repository, so no counter
    # table is needed (`knowledge/repo.py:255` makes the same argument for repo syncs).
    op.add_column(
        "project_repositories",
        sa.Column("provider_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    # **A stored copy of a transient fact, which this schema usually refuses** (ADR 0029 §1
    # declines to store a runner's online state for exactly that reason). The distinction
    # is re-derivability: a runner's liveness can be asked again at any moment, and a poll
    # that failed four minutes ago cannot. Without this column a revoked token presents as
    # "no new pull requests" — on screen, indistinguishable from a quiet repository.
    op.add_column(
        "project_repositories",
        sa.Column("provider_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "project_repositories",
        sa.Column(
            "provider_sync_failures",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    # Rows first, then the constraint: PostgreSQL validates a new CHECK against existing
    # rows, so narrowing the domain while a `pull_request` row exists fails — and fails
    # after the four columns have already been dropped if the order is reversed.
    #
    # Chunks go with their sources through `ondelete="CASCADE"`; jobs are deleted here
    # because a pending job naming a type the CHECK no longer admits is a row the worker
    # would claim and then be unable to process.
    op.execute(
        sa.text(
            "DELETE FROM knowledge_sources WHERE source_type IN ('pull_request', 'release')"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM knowledge_jobs WHERE source_type IN ('pull_request', 'release')"
        )
    )

    op.drop_column("project_repositories", "provider_sync_failures")
    op.drop_column("project_repositories", "provider_sync_error")
    op.drop_column("project_repositories", "provider_synced_at")
    op.drop_column("projects", "provider_sync_enabled")

    for table in _TABLES_WITH_SOURCE_TYPE:
        op.drop_constraint("source_type", table, type_="check")
        op.create_check_constraint(
            "source_type", table, _in("source_type", _SOURCE_TYPES_BEFORE)
        )
