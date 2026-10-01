"""多智能体群聊 / Persistent multi-agent rooms."""

import sqlalchemy as sa
from alembic import op

revision = "0015_group_rooms"
down_revision = "0014_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_rooms",
        sa.Column("room_id", sa.String(36), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("group_rooms")
