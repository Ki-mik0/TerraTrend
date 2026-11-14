"""Job queue table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_jobs"
down_revision = "004_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="jobs_status_known",
        ),
    )
    op.create_index("jobs_status", "jobs", ["status"])
    op.create_index("jobs_case", "jobs", ["case_id"])


def downgrade() -> None:
    op.drop_index("jobs_case", table_name="jobs")
    op.drop_index("jobs_status", table_name="jobs")
    op.drop_table("jobs")
