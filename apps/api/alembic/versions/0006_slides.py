"""Optional class slide decks and topic references."""

import sqlalchemy as sa

from alembic import op

revision = "0006_slides"
down_revision = "0005_retry_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slide_decks",
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), primary_key=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("slide_decks")
