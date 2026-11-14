"""Journal tables: notes, saved cases, and the note id counter."""

from alembic import op
import sqlalchemy as sa

revision = "004_journal"
down_revision = "003_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("author_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('note', 'hypothesis')", name="notes_kind_known"),
    )
    op.create_index("notes_author", "notes", ["author_id"])
    op.create_table(
        "saved_cases",
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("case_id", sa.String(64), primary_key=True),
    )
    op.create_table(
        "journal_counters",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("journal_counters")
    op.drop_table("saved_cases")
    op.drop_index("notes_author", table_name="notes")
    op.drop_table("notes")
