"""pg_trgm, and the two columns that decide whether a project has a memory at all

Revision ID: 0041_knowledge_extension
Revises: 0040_ticket_conversation
Create Date: 2026-08-22

`KN-02` / `FR-KNOW-010` (ADR 0038 §7). **One line of this migration is the only thing
in the whole V2-K1 phase that is not purely additive**, and that is why it is alone in
its own revision rather than sharing one with the six tables.

Three things follow from the separation, and each of them is the reason:

* **The error message points at the right line.** `CREATE EXTENSION` needs a superuser
  or an extension allowlist, and a deployment that lacks one stops here. Sharing a file
  with three hundred lines of `create_table` would produce "0042 failed" and a reader
  who has to find out why.
* **The downgrade order is enforced by the revision chain rather than by memory.**
  Dropping the extension requires that nothing depends on it, and `0042` is what builds
  the `gin_trgm_ops` index that would. `0042` down, then `0041` down; alembic will not
  let it happen the other way round.
* **This one can ship first.** Two columns and a contrib extension are safe to have in
  production before the tables that use them exist.

The preflight is not decoration. `IF NOT EXISTS` only helps when the extension is
*already installed*, which is not the failure anybody has; it does nothing about a role
without permission. So the availability of `pg_trgm` is checked first and the refusal
says what to do — this migration runs in two very different deployments (compose, where
the migration role is the image's superuser, and Railway, where it usually is not), and
`KN-02`'s exit criterion is that both were tried.

`knowledge_settings` is JSONB rather than a table for the reason ADR 0027 gives about
`projects.process_overrides`: it is read and written with the project and has no query
of its own. It deliberately holds **no retention override** — ADR 0038 §6 decided
knowledge has no clock of its own, and a column with no sweep behind it is worse than
no column, because someone will read it and believe it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_knowledge_extension"
down_revision: str | None = "0040_ticket_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    available = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'"))
        .scalar()
    )
    if not available:
        raise RuntimeError(
            "pg_trgm is not available on this PostgreSQL server. It is a contrib "
            "extension and ships with postgres:16-alpine; a managed database may need "
            "it enabled by the provider first. Install it, then re-run "
            "`alembic upgrade head`. Nothing has been changed."
        )
    # Separate from the check above so the failure modes stay distinguishable: "the
    # server does not have it" and "this role may not install it" need different
    # actions from whoever is reading the deployment log.
    try:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception as exc:  # noqa: BLE001 - re-raised with the action attached
        raise RuntimeError(
            "CREATE EXTENSION pg_trgm was refused. The migration role usually needs to "
            "be a superuser, or pg_trgm has to be on the provider's extension "
            "allowlist. Ask an administrator to run `CREATE EXTENSION pg_trgm;` once "
            "against this database, then re-run `alembic upgrade head`."
        ) from exc

    op.add_column(
        "projects",
        sa.Column(
            "knowledge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "knowledge_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "knowledge_settings")
    op.drop_column("projects", "knowledge_enabled")
    # **No CASCADE.** With it, this would take out somebody else's index that happens
    # to use `gin_trgm_ops`, which is not a thing a downgrade may do. Without it the
    # statement fails when a dependency remains — and failing is the correct outcome,
    # because the error names what is still using it.
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_trgm"))
