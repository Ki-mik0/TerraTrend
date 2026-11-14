"""Import point for every ORM table, so ``Base.metadata`` is complete for Alembic.

Stage B3 adds e.g. ``from earthtrend.api.infrastructure.cases import tables``.
"""

from __future__ import annotations

from earthtrend.api.infrastructure.shared.session import Base

metadata = Base.metadata

__all__ = ["Base", "metadata"]
