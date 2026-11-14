"""Assistant exchanges: question, plan, answer, cases and citations of each conversation turn."""

from alembic import op
import sqlalchemy as sa

revision = "003_assistant"
down_revision = "002_education"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_exchanges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("case_ids", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('running', 'answered', 'failed')", name="assistant_status_known"),
        sa.CheckConstraint("mode IN ('investigate', 'teach')", name="assistant_mode_known"),
    )
    op.create_index("assistant_exchanges_owner_created", "assistant_exchanges", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_index("assistant_exchanges_owner_created", table_name="assistant_exchanges")
    op.drop_table("assistant_exchanges")
