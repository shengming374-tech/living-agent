"""Add staged and deployed persona/prompt artifact history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_managed_artifacts"
down_revision: str | None = "0002_memory_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_versions",
        sa.Column("row_id", sa.String(length=36), primary_key=True),
        sa.Column("artifact_kind", sa.String(length=40), nullable=False),
        sa.Column("artifact_path", sa.String(length=512), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "artifact_kind",
            "artifact_path",
            "version",
            name="uq_artifact_version",
        ),
    )
    op.create_index(
        "ix_artifact_versions_kind_path",
        "artifact_versions",
        ["artifact_kind", "artifact_path"],
    )
    op.create_table(
        "artifact_stages",
        sa.Column("stage_id", sa.String(length=36), primary_key=True),
        sa.Column("artifact_kind", sa.String(length=40), nullable=False),
        sa.Column("artifact_path", sa.String(length=512), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("test_results", sa.JSON(), nullable=False),
        sa.Column("tested", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_artifact_stages_kind_path",
        "artifact_stages",
        ["artifact_kind", "artifact_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_stages_kind_path", table_name="artifact_stages")
    op.drop_table("artifact_stages")
    op.drop_index("ix_artifact_versions_kind_path", table_name="artifact_versions")
    op.drop_table("artifact_versions")
