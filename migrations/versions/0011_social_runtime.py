"""Persist social scheduling, focus, impressions, and attention cues."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_social_runtime"
down_revision: str | None = "0010_memory_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "utterance_sessions",
        sa.Column("attention_cue_id", sa.String(length=36), nullable=True),
    )
    op.create_table(
        "conversation_runtime_states",
        sa.Column("conversation_id", sa.String(length=255), primary_key=True),
        sa.Column("pending_event_ids", sa.JSON(), nullable=False),
        sa.Column("focus_salience", sa.Float(), nullable=False),
        sa.Column("is_focused", sa.Boolean(), nullable=False),
        sa.Column("forced_wakeup", sa.Boolean(), nullable=False),
        sa.Column("consecutive_idle_count", sa.Integer(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_external_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_agent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_conversation_runtime_focus",
        "conversation_runtime_states",
        ["is_focused", "focus_salience"],
    )
    op.create_index(
        "ix_conversation_runtime_updated",
        "conversation_runtime_states",
        ["updated_at"],
    )
    op.create_table(
        "session_impressions",
        sa.Column("impression_id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("unresolved_threads", sa.JSON(), nullable=False),
        sa.Column("emotional_tone", sa.String(length=80), nullable=False),
        sa.Column("participant_cues", sa.JSON(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_session_impressions_conversation_created",
        "session_impressions",
        ["conversation_id", "created_at"],
    )
    op.create_table(
        "attention_cues",
        sa.Column("cue_id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("cue_text", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("salience", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_attention_cues_conversation_created",
        "attention_cues",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_attention_cues_conversation_created", table_name="attention_cues")
    op.drop_table("attention_cues")
    op.drop_index(
        "ix_session_impressions_conversation_created",
        table_name="session_impressions",
    )
    op.drop_table("session_impressions")
    op.drop_index("ix_conversation_runtime_updated", table_name="conversation_runtime_states")
    op.drop_index("ix_conversation_runtime_focus", table_name="conversation_runtime_states")
    op.drop_table("conversation_runtime_states")
    op.drop_column("utterance_sessions", "attention_cue_id")
