"""Add private daily-life, sleep, dream, and self-change records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_daily_life"
down_revision: str | None = "0008_openclaw_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "private_projects",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "daily_plans",
        sa.Column("plan_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("intention", sa.Text(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ux_daily_plans_date", "daily_plans", ["plan_date"], unique=True)
    op.create_table(
        "life_activity_logs",
        sa.Column("activity_id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("plan_id", sa.String(length=36), nullable=True),
        sa.Column("plan_item_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_life_activity_started", "life_activity_logs", ["started_at"])
    op.create_index("ix_life_activity_plan_item", "life_activity_logs", ["plan_item_id"])
    op.create_table(
        "diary_entries",
        sa.Column("diary_id", sa.String(length=36), primary_key=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mood_summary", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("generated_by", sa.String(length=80), nullable=False),
        sa.Column("source_activity_ids", sa.JSON(), nullable=False),
        sa.Column("source_memory_ids", sa.JSON(), nullable=False),
        sa.Column("dream_record_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ux_diary_entries_date", "diary_entries", ["entry_date"], unique=True)
    op.create_table(
        "sleep_cycles",
        sa.Column("cycle_id", sa.String(length=36), primary_key=True),
        sa.Column("cycle_date", sa.Date(), nullable=False),
        sa.Column("trigger", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("diary_id", sa.String(length=36), nullable=True),
        sa.Column("dream_id", sa.String(length=36), nullable=True),
        sa.Column("reality_memory_ids", sa.JSON(), nullable=False),
        sa.Column("candidate_review_ids", sa.JSON(), nullable=False),
        sa.Column("duplicate_memory_clusters", sa.JSON(), nullable=False),
        sa.Column("thought_record_ids", sa.JSON(), nullable=False),
        sa.Column("activity_ids", sa.JSON(), nullable=False),
        sa.Column("automatic_memory_writes", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ux_sleep_cycles_date", "sleep_cycles", ["cycle_date"], unique=True)
    op.create_table(
        "dream_records",
        sa.Column("dream_id", sa.String(length=36), primary_key=True),
        sa.Column("cycle_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("dream_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("seed_activity_ids", sa.JSON(), nullable=False),
        sa.Column("seed_memory_ids", sa.JSON(), nullable=False),
        sa.Column("factuality", sa.String(length=40), nullable=False),
        sa.Column("reality_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dream_records_date", "dream_records", ["dream_date"])
    op.create_table(
        "self_change_proposals",
        sa.Column("proposal_id", sa.String(length=36), primary_key=True),
        sa.Column("proposer_id", sa.String(length=80), nullable=False),
        sa.Column("target_kind", sa.String(length=40), nullable=False),
        sa.Column("target_path", sa.String(length=200), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_diary_ids", sa.JSON(), nullable=False),
        sa.Column("source_dream_ids", sa.JSON(), nullable=False),
        sa.Column("stage_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("test_results", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("deployed_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_self_change_proposals_created", "self_change_proposals", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_self_change_proposals_created", table_name="self_change_proposals")
    op.drop_table("self_change_proposals")
    op.drop_index("ix_dream_records_date", table_name="dream_records")
    op.drop_table("dream_records")
    op.drop_index("ux_sleep_cycles_date", table_name="sleep_cycles")
    op.drop_table("sleep_cycles")
    op.drop_index("ux_diary_entries_date", table_name="diary_entries")
    op.drop_table("diary_entries")
    op.drop_index("ix_life_activity_plan_item", table_name="life_activity_logs")
    op.drop_index("ix_life_activity_started", table_name="life_activity_logs")
    op.drop_table("life_activity_logs")
    op.drop_index("ux_daily_plans_date", table_name="daily_plans")
    op.drop_table("daily_plans")
    op.drop_table("private_projects")
