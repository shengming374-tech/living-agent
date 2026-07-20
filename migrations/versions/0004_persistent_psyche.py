"""Add persistent psyche state, thoughts, topics, and activities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_persistent_psyche"
down_revision: str | None = "0003_managed_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "psyche_states",
        sa.Column("state_id", sa.String(length=36), primary_key=True),
        sa.Column("valence", sa.Float(), nullable=False),
        sa.Column("arousal", sa.Float(), nullable=False),
        sa.Column("current_focus", sa.String(length=500), nullable=True),
        sa.Column("focus_salience", sa.Float(), nullable=False),
        sa.Column("unresolved_topic_ids", sa.JSON(), nullable=False),
        sa.Column("current_activity_id", sa.String(length=36), nullable=True),
        sa.Column("last_decay_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "thought_records",
        sa.Column("thought_id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("speakability", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_thought_records_created_at", "thought_records", ["created_at"])
    op.create_table(
        "psyche_topics",
        sa.Column("topic_id", sa.String(length=36), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "activity_records",
        sa.Column("activity_id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_activity_records_started_at", "activity_records", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_activity_records_started_at", table_name="activity_records")
    op.drop_table("activity_records")
    op.drop_table("psyche_topics")
    op.drop_index("ix_thought_records_created_at", table_name="thought_records")
    op.drop_table("thought_records")
    op.drop_table("psyche_states")
