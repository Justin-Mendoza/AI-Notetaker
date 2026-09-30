"""Create meetings foundation.

Revision ID: 0001_meetings
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_meetings"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_policy_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('draft','uploading','queued','transcribing',"
            "'summarizing','ready','failed','deleted')",
            name="ck_meetings_status",
        ),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_meetings_duration"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_meetings_title"),
    )
    op.create_index("ix_meetings_owner_created", "meetings", ["owner_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_meetings_owner_created", table_name="meetings")
    op.drop_table("meetings")
