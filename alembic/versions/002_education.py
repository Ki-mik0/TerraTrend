"""Education tables."""

from alembic import op
import sqlalchemy as sa

revision = "002_education"
down_revision = "001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("teacher_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("share_token", sa.String(64), nullable=True, unique=True),
    )
    op.create_index("ix_assignments_teacher_id", "assignments", ["teacher_id"])
    op.create_table(
        "assignment_students",
        sa.Column(
            "assignment_id", sa.String(64), sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("student_id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_assignment_students_student_id", "assignment_students", ["student_id"])
    op.create_table(
        "assignment_cases",
        sa.Column(
            "assignment_id", sa.String(64), sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_assignment_cases_case_id", "assignment_cases", ["case_id"])
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "assignment_id", sa.String(64), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("student_id", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("demo_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_submissions_assignment_id", "submissions", ["assignment_id"])
    op.create_table(
        "badges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("unique_reason", sa.String(64), nullable=False),
        sa.UniqueConstraint("user_id", "code", "unique_reason", name="badges_once"),
    )
    op.create_index("ix_badges_user_id", "badges", ["user_id"])
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"])
    op.create_table(
        "demo_progress",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("demo_id", sa.String(64), primary_key=True),
        sa.Column("steps", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("demo_progress")
    op.drop_index("ix_quiz_attempts_user_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_index("ix_badges_user_id", table_name="badges")
    op.drop_table("badges")
    op.drop_index("ix_submissions_assignment_id", table_name="submissions")
    op.drop_table("submissions")
    op.drop_index("ix_assignment_cases_case_id", table_name="assignment_cases")
    op.drop_table("assignment_cases")
    op.drop_index("ix_assignment_students_student_id", table_name="assignment_students")
    op.drop_table("assignment_students")
    op.drop_index("ix_assignments_teacher_id", table_name="assignments")
    op.drop_table("assignments")
