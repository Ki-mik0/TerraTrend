"""Catalog tables: drawn regions, CMR passports, and potential feedback."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007_catalog"
down_revision = "006_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_regions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=False),
        sa.Column("area_km2", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("geometry", postgresql.JSONB(), nullable=True),
        sa.Column("ring", postgresql.JSONB(), nullable=True),
    )
    op.create_index("custom_regions_kind", "custom_regions", ["kind"])
    op.create_table(
        "catalog_passports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_uk", sa.String(200), nullable=False),
        sa.Column("kid_description", sa.Text(), nullable=False),
        sa.Column("units", sa.String(32), nullable=False),
        sa.Column("theme", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("witnesses", postgresql.JSONB(), nullable=False),
        sa.Column("doi", sa.String(128), nullable=False),
        sa.CheckConstraint("level IN ('curated', 'cmr')", name="catalog_passports_level"),
    )
    op.create_index("catalog_passports_level_idx", "catalog_passports", ["level"])
    op.create_table(
        "potential_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("region_id", sa.String(64), nullable=False),
        sa.Column("variable_id", sa.String(64), nullable=False),
        sa.Column("predicted_sign", sa.Integer(), nullable=False),
        sa.Column("p_significant", sa.Float(), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("actual_code", sa.String(32), nullable=False),
    )
    op.create_table(
        "cmr_queries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("query", sa.String(200), nullable=False),
        sa.Column("passport_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_index("cmr_queries_query", "cmr_queries", ["query"], unique=True)


def downgrade() -> None:
    op.drop_index("cmr_queries_query", table_name="cmr_queries")
    op.drop_table("cmr_queries")
    op.drop_table("potential_feedback")
    op.drop_index("catalog_passports_level_idx", table_name="catalog_passports")
    op.drop_table("catalog_passports")
    op.drop_index("custom_regions_kind", table_name="custom_regions")
    op.drop_table("custom_regions")
