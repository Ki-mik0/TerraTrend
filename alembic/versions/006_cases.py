"""Case tables: the stored investigation and its id counter."""

from alembic import op
import sqlalchemy as sa

revision = "006_cases"
down_revision = "005_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variable_id", sa.String(64), nullable=False),
        sa.Column("region_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ephemeral", sa.Boolean(), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("verdict_code", sa.String(32), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("catalog_version", sa.String(32), nullable=False),
        sa.Column("datasets_version", sa.String(32), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="cases_status_known",
        ),
    )
    op.create_index("cases_owner", "cases", ["owner_id"])
    op.create_table(
        "case_counters",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("case_counters")
    op.drop_index("cases_owner", table_name="cases")
    op.drop_table("cases")
