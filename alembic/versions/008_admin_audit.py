"""Allow audit rows for cache warm-up, cache clear and catalog reload."""

from alembic import op

revision = "008_admin_audit"
down_revision = "007_catalog"
branch_labels = None
depends_on = None

_OLD = "action IN ('issue_key', 'revoke_key', 'ai_review')"
_NEW = "action IN ('issue_key', 'revoke_key', 'ai_review', 'warm_cache', 'clear_cache', 'reload_catalog')"


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("audit_action_known", type_="check")
        batch.create_check_constraint("audit_action_known", _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM audit_logs WHERE action IN ('warm_cache', 'clear_cache', 'reload_catalog')")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("audit_action_known", type_="check")
        batch.create_check_constraint("audit_action_known", _OLD)
