"""Persist interruptible utterance Sessions and delivery progress."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_utterance_sessions"
down_revision: str | None = "0006_executive_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "utterance_sessions",
        sa.Column("session_id", sa.String(length=36), primary_key=True),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=500), nullable=False),
        sa.Column("source_event_id", sa.String(length=36), nullable=False),
        sa.Column("intention", sa.Text(), nullable=False),
        sa.Column("units", sa.JSON(), nullable=False),
        sa.Column("recalled_memory_ids", sa.JSON(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("started_count", sa.Integer(), nullable=False),
        sa.Column("interruption_policy", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("replaced_session_id", sa.String(length=36), nullable=True),
        sa.Column("interruption_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_utterance_sessions_scope_state",
        "utterance_sessions",
        ["platform", "conversation_id", "state"],
    )
    op.create_index(
        "ix_utterance_sessions_conversation_updated",
        "utterance_sessions",
        ["conversation_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_utterance_sessions_conversation_updated",
        table_name="utterance_sessions",
    )
    op.drop_index("ix_utterance_sessions_scope_state", table_name="utterance_sessions")
    op.drop_table("utterance_sessions")
