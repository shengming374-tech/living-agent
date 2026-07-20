"""Add candidate-based versioned memory tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_memory_control"
down_revision: str | None = "0001_safe_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_candidates",
        sa.Column("candidate_id", sa.String(length=36), primary_key=True),
        sa.Column("proposer_id", sa.String(length=255), nullable=False),
        sa.Column("memory_type", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("source_trust", sa.String(length=40), nullable=False),
        sa.Column("factuality", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("scope", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("decision_reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "memory_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_type", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("source_trust", sa.String(length=40), nullable=False),
        sa.Column("factuality", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("scope", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_memory_nodes_scope_status", "memory_nodes", ["scope", "status"])
    op.create_index(
        "ix_memory_nodes_subject_type",
        "memory_nodes",
        ["subject", "memory_type"],
    )
    op.create_table(
        "memory_versions",
        sa.Column("row_id", sa.String(length=36), primary_key=True),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("memory_id", "version", name="uq_memory_version"),
    )
    op.create_index("ix_memory_versions_memory_id", "memory_versions", ["memory_id"])
    op.create_table(
        "memory_usages",
        sa.Column("usage_id", sa.String(length=36), primary_key=True),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("response_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_usages_memory_id", "memory_usages", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_usages_memory_id", table_name="memory_usages")
    op.drop_table("memory_usages")
    op.drop_index("ix_memory_versions_memory_id", table_name="memory_versions")
    op.drop_table("memory_versions")
    op.drop_index("ix_memory_nodes_subject_type", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_scope_status", table_name="memory_nodes")
    op.drop_table("memory_nodes")
    op.drop_table("memory_candidates")
