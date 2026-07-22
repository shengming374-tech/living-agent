"""Add versioned memory embedding vectors."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_memory_embeddings"
down_revision: str | None = "0009_daily_life"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("memory_id", sa.String(length=36), primary_key=True),
        sa.Column("memory_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_embeddings_provider_model",
        "memory_embeddings",
        ["provider", "model"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_embeddings_provider_model",
        table_name="memory_embeddings",
    )
    op.drop_table("memory_embeddings")
