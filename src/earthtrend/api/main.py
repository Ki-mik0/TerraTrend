"""Process entry point: ``uvicorn earthtrend.api.main:app`` (``make api``)."""

from __future__ import annotations

from earthtrend.api.api.app import create_app

app = create_app()
