"""project_secrets, the project's name allowlist, two node declarations, and a repository's credential

Revision ID: 0033_project_secrets
Revises: 0032_runner_pressure
Create Date: 2026-08-13

Four changes in one revision, because they are each other's premises: a repository's
`credential_secret_id` is a foreign key into the new table, and a card's
`required_secrets` only means anything once a project has an allowlist to check it
against (ADR 0032).

**Four ciphertext columns, not two.** AES-GCM needs a fresh nonce per write and it has
to be stored beside its ciphertext; the envelope has two layers, so it has two nonces.
Prefixing the nonce onto the ciphertext is the usual way to save the columns and is not
done here: this is a table a security review reads column by column, and the shape of
the encryption should be legible from `\\d` rather than from a comment.

**The unique key is partial.** `(project_id, name) WHERE deleted_at IS NULL` — after a
soft delete, the same name has to be creatable again, because "delete it and make a new
one" is the commonest recovery there is, and hitting a unique violation on it produces
a 409 nobody can act on.

**No `value` column, no fingerprint, no length.** A fingerprint answers "is this the one
I rotated last week" and `rotated_at` answers it without disclosing anything; a length
is a side channel, since a 93-character value is almost certainly a fine-grained PAT.

**`auth_kind` has three values, not the two the design named.** `ambient` is what every
repository registered under V2.2 is actually using — the node's own git credentials —
and after the 2026-08-13 ruling it is also the default going forward. Back-filling those
rows as `pat` with a null credential would be writing down a row that is not true.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_project_secrets"
down_revision: str | None = "0032_runner_pressure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        # The envelope. `value_encrypted` is under the per-row data key; `dek_wrapped`
        # is that data key under the master key. Rotating the master key rewrites the
        # second and leaves the first byte-for-byte identical, which is what makes
        # rotation something other than a full-table re-encryption.
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("value_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        # Present from the first row rather than "added later": without it, the first
        # rotation has no way to tell which key opens which row.
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            # SET NULL, not CASCADE: somebody leaving must not delete a project's
            # credentials.
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        # Written at the claim, not at the end of the run: a run may never end, and
        # "this machine was handed this secret" is already a fact by then.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('env', 'git_pat', 'git_ssh_key', 'provider_token')",
            name="ck_project_secrets_kind",
        ),
    )
    op.create_index(
        "uq_project_secrets_name",
        "project_secrets",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_project_secrets_project",
        "project_secrets",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # The allowlist is intent ("which names may a card ask for"), which is why it is not
    # derived from the rows that happen to exist. Deriving it would make deleting one
    # secret silently un-dispatchable a batch of cards, with nothing on screen relating
    # the two.
    op.add_column(
        "projects",
        sa.Column(
            "allowed_secret_names",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Two node-side declarations. Both default true, and both defaults are the
    # permissive direction — for the same reason: a default has to equal the behaviour
    # before the upgrade. A 0.9.0 runner claims anything today and secrets do not exist
    # yet, so `true`/`true` is the no-change value. Tightening is an operator's action,
    # never a side effect of upgrading — the same discipline that keeps
    # `runner.enabled` defaulting to false.
    op.add_column(
        "agent_runners",
        sa.Column("run_untagged", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "agent_runners",
        sa.Column("accept_secrets", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # A repository row stops being "where the code is" and becomes "which credential
    # fetches it".
    op.add_column(
        "project_repositories",
        sa.Column("auth_kind", sa.String(length=16), nullable=False, server_default="ambient"),
    )
    op.add_column(
        "project_repositories",
        sa.Column(
            "credential_secret_id",
            postgresql.UUID(as_uuid=True),
            # RESTRICT rather than SET NULL: a hard delete of a credential a repository
            # is using should be a refusal that names the repository, not a silent
            # downgrade to ambient. (The API's delete is a soft delete and has its own
            # check; this guards the direct-SQL and future hard-delete paths.)
            sa.ForeignKey("project_secrets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "project_repositories",
        sa.Column(
            "provider_token_secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_secrets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_project_repositories_auth_kind",
        "project_repositories",
        "auth_kind IN ('ambient', 'pat', 'ssh')",
    )
    # A row saying `pat` with no credential is one that fails three minutes into a run.
    op.create_check_constraint(
        "ck_project_repositories_credential",
        "project_repositories",
        "(auth_kind = 'ambient' AND credential_secret_id IS NULL)"
        " OR (auth_kind IN ('pat', 'ssh') AND credential_secret_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_project_repositories_credential", "project_repositories", type_="check"
    )
    op.drop_constraint("ck_project_repositories_auth_kind", "project_repositories", type_="check")
    for column in ("provider_token_secret_id", "credential_secret_id", "auth_kind"):
        op.drop_column("project_repositories", column)
    op.drop_column("agent_runners", "accept_secrets")
    op.drop_column("agent_runners", "run_untagged")
    op.drop_column("projects", "allowed_secret_names")
    op.drop_index("ix_project_secrets_project", table_name="project_secrets")
    op.drop_index("uq_project_secrets_name", table_name="project_secrets")
    op.drop_table("project_secrets")
