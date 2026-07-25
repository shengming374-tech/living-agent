"""Add dual-layer memory metadata and recall provenance traces."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_dual_layer_memory"
down_revision: str | None = "0012_napcat_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("memory_candidates", "memory_nodes"):
        op.add_column(
            table_name,
            sa.Column("memory_layer", sa.String(length=40), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("entity_id", sa.String(length=255), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("memory_key", sa.String(length=255), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        )

    op.add_column(
        "utterance_sessions",
        sa.Column("memory_trace_id", sa.String(length=36), nullable=True),
    )

    op.create_table(
        "memory_recall_traces",
        sa.Column("trace_id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("response_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=40), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "support_mode",
            sa.String(length=40),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_recall_traces_conversation_created",
        "memory_recall_traces",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_memory_recall_traces_event_id",
        "memory_recall_traces",
        ["event_id"],
    )
    op.create_index(
        "ix_memory_recall_traces_response_id",
        "memory_recall_traces",
        ["response_id"],
    )

    op.create_table(
        "memory_recall_trace_items",
        sa.Column("row_id", sa.String(length=36), primary_key=True),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("memory_layer", sa.String(length=40), nullable=False),
        sa.Column("selection_reason", sa.String(length=120), nullable=False),
        sa.Column("lexical_score", sa.Float(), nullable=True),
        sa.Column("semantic_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("injected", sa.Boolean(), nullable=False),
        sa.Column("response_match", sa.Boolean(), nullable=True),
        sa.Column("source_overlap", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "trace_id",
            "memory_id",
            name="uq_memory_recall_trace_item",
        ),
    )
    op.create_index(
        "ix_memory_recall_trace_items_trace_selected",
        "memory_recall_trace_items",
        ["trace_id", "selected"],
    )
    op.create_index(
        "ix_memory_recall_trace_items_memory_id",
        "memory_recall_trace_items",
        ["memory_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_recall_trace_items_memory_id",
        table_name="memory_recall_trace_items",
    )
    op.drop_index(
        "ix_memory_recall_trace_items_trace_selected",
        table_name="memory_recall_trace_items",
    )
    op.drop_table("memory_recall_trace_items")

    op.drop_index(
        "ix_memory_recall_traces_response_id",
        table_name="memory_recall_traces",
    )
    op.drop_index(
        "ix_memory_recall_traces_event_id",
        table_name="memory_recall_traces",
    )
    op.drop_index(
        "ix_memory_recall_traces_conversation_created",
        table_name="memory_recall_traces",
    )
    op.drop_table("memory_recall_traces")

    op.drop_column("utterance_sessions", "memory_trace_id")

    for table_name in ("memory_nodes", "memory_candidates"):
        op.drop_column(table_name, "superseded_by_id")
        op.drop_column(table_name, "valid_until")
        op.drop_column(table_name, "memory_key")
        op.drop_column(table_name, "entity_id")
        op.drop_column(table_name, "memory_layer")
