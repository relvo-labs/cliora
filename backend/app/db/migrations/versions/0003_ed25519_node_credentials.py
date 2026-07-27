"""replace shared node secrets with Ed25519 public keys"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
revision: str = "0003_ed25519_node_credentials"
down_revision: Union[str, None] = "0002_seed_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.alter_column("node_credentials", "secret_hash", existing_type=sa.String(128), nullable=True)
    op.add_column("node_credentials", sa.Column("public_key", sa.String(128), nullable=True))
    op.execute("UPDATE node_credentials SET revoked_at = now() WHERE revoked_at IS NULL")

def downgrade() -> None:
    op.execute("DELETE FROM node_credentials WHERE secret_hash IS NULL")
    op.drop_column("node_credentials", "public_key")
    op.alter_column("node_credentials", "secret_hash", existing_type=sa.String(128), nullable=False)
