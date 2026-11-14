"""Identity tables."""

from alembic import op
import sqlalchemy as sa

revision = "001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('guest', 'user', 'teacher', 'admin')", name="users_role_known"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
    )
    op.create_index("api_keys_active_user", "api_keys", ["user_id"], postgresql_where=sa.text("revoked = false"))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('issue_key', 'revoke_key', 'ai_review')", name="audit_action_known"),
    )
    op.create_index("audit_logs_actor", "audit_logs", ["actor_id"])
    op.create_table(
        "ai_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
    )
    op.create_table(
        "identity_counters",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("identity_counters")
    op.drop_table("ai_reviews")
    op.drop_index("audit_logs_actor", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("api_keys_active_user", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
