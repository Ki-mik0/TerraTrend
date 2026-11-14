"""Baseline: empty schema (stage B1). Tables arrive with their zones from stage B3.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-14

"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
