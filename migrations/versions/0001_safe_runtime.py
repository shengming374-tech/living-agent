"""Create trusted event and append-only audit tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_safe_runtime"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_identity", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("trust_level", sa.String(length=40), nullable=False),
        sa.Column("authority_level", sa.String(length=40), nullable=False),
        sa.Column("taint_labels", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_trusted_events_conversation_created",
        "trusted_events",
        ["conversation_id", "created_at"],
    )
    op.create_table(
        "audit_records",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_audit_records_created_at",
        "audit_records",
        ["created_at"],
    )
    op.create_index(
        "ix_audit_records_action_created",
        "audit_records",
        ["action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_records_action_created", table_name="audit_records")
    op.drop_index("ix_audit_records_created_at", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_trusted_events_conversation_created", table_name="trusted_events")
    op.drop_table("trusted_events")
