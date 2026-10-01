"""Track manual retry rate limits.

Revision ID: 0005_retry_limits
Revises: 0004_summaries
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_retry_limits"
down_revision = "0004_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("manual_retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "processing_jobs", sa.Column("manual_retry_window_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "manual_retry_window_at")
    op.drop_column("processing_jobs", "manual_retry_count")
