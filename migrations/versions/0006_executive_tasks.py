"""Add persistent executive task runs and confirmed reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_executive_tasks"
down_revision: str | None = "0005_registered_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_runs",
        sa.Column("task_id", sa.String(length=36), primary_key=True),
        sa.Column("requester_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("task_contract", sa.JSON(), nullable=False),
        sa.Column("execution_plan", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("step_results", sa.JSON(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("taint_labels", sa.JSON(), nullable=False),
        sa.Column("pending_step_id", sa.String(length=36), nullable=True),
        sa.Column("activity_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_task_runs_status_updated", "task_runs", ["status", "updated_at"])
    op.create_index(
        "ix_task_runs_conversation_updated",
        "task_runs",
        ["conversation_id", "updated_at"],
    )
    op.create_table(
        "task_reports",
        sa.Column("report_id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_task_reports_task_id"),
    )
    op.create_index("ix_task_reports_created_at", "task_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_task_reports_created_at", table_name="task_reports")
    op.drop_table("task_reports")
    op.drop_index("ix_task_runs_conversation_updated", table_name="task_runs")
    op.drop_index("ix_task_runs_status_updated", table_name="task_runs")
    op.drop_table("task_runs")
