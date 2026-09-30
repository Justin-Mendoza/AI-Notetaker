"""Create recordings and processing jobs.

Revision ID: 0002_recordings_jobs
Revises: 0001_meetings
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_recordings_jobs"
down_revision = "0001_meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("upload_key", sa.Uuid()))
    op.create_table(
        "recordings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Uuid(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("object_key", sa.String(300), unique=True, nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("upload_idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 100000000", name="ck_recordings_size"),
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Uuid(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','running','failed','completed')", name="ck_jobs_status"
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_jobs_attempts"),
    )
    op.create_index("ix_jobs_status_run_after", "processing_jobs", ["status", "run_after"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_run_after", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_table("recordings")
    op.drop_column("meetings", "upload_key")
