"""Add authenticated platform user profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_registered_users"
down_revision: str | None = "0004_persistent_psyche"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registered_users",
        sa.Column("user_id", sa.String(length=255), primary_key=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("last_conversation_id", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_registered_users_last_seen", "registered_users", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_registered_users_last_seen", table_name="registered_users")
    op.drop_table("registered_users")
