"""Persist NapCat inbound message idempotency keys."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_napcat_idempotency"
down_revision: str | None = "0011_social_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "napcat_ingress_keys",
        sa.Column("idempotency_key", sa.String(length=64), primary_key=True),
        sa.Column("self_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_napcat_ingress_updated",
        "napcat_ingress_keys",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_napcat_ingress_updated", table_name="napcat_ingress_keys")
    op.drop_table("napcat_ingress_keys")
