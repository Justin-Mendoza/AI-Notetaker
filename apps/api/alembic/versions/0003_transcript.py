"""Create transcript segments and job cursor.

Revision ID: 0003_transcript
Revises: 0002_recordings_jobs
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_transcript"
down_revision = "0002_recordings_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("stage", sa.String(24), nullable=False, server_default="transcribing"),
    )
    op.add_column(
        "processing_jobs", sa.Column("cursor", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Uuid(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meeting_id", "sequence_no", name="uq_transcript_sequence"),
        sa.CheckConstraint("sequence_no >= 0", name="ck_segment_sequence"),
        sa.CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="ck_segment_range"),
    )


def downgrade() -> None:
    op.drop_table("transcript_segments")
    op.drop_column("processing_jobs", "cursor")
    op.drop_column("processing_jobs", "stage")
