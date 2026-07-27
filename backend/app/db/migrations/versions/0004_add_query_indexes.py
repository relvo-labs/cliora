"""add node and audit query indexes

Revision ID: 0004_add_query_indexes
Revises: 0003_ed25519_node_credentials
Create Date: 2026-07-24

Adds the query indexes the node list/detail and audit lookups rely on
(01-data-layer.md §P1-04): nodes by name and last-known status, and
audit_logs by node_id. Downgrade drops them.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004_add_query_indexes"
down_revision: Union[str, None] = "0003_ed25519_node_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_nodes_name", "nodes", ["name"])
    op.create_index("ix_nodes_status", "nodes", ["status"])
    op.create_index("ix_audit_logs_node_id", "audit_logs", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_node_id", table_name="audit_logs")
    op.drop_index("ix_nodes_status", table_name="nodes")
    op.drop_index("ix_nodes_name", table_name="nodes")
