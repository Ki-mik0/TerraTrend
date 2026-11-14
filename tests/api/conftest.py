"""Fixtures for the api layer: an app on a temporary SQLite file and synthetic series."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from earthtrend.api.main import create_app
from earthtrend.api.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        db_url=f"sqlite+aiosqlite:///{(tmp_path / 'db' / 'app.db').as_posix()}",
        storage_root=tmp_path / "storage",
    )


@pytest.fixture
def app(settings: Settings) -> Litestar:
    del settings
    return create_app()


@pytest.fixture
def client(app: Litestar) -> Iterator[TestClient[Litestar]]:
    with TestClient(app=app) as c:
        yield c


@pytest.fixture
def make_series() -> Callable[..., dict[str, Any]]:
    return monthly_series


def monthly_series(
    years: int = 30, slope_per_decade: float = 0.4, noise: float = 0.3, seed: int = 1
) -> dict[str, Any]:
    """JSON body of a monthly 2 m temperature series with a seasonal cycle and a trend."""
    rng = np.random.default_rng(seed)
    n = years * 12
    t = np.arange(n) / 12.0
    values = (
        260.0
        + 10.0 * np.sin(2 * np.pi * (np.arange(n) % 12) / 12)
        + slope_per_decade * t / 10.0
        + rng.normal(0.0, noise, n)
    )
    dates = [date(1995 + i // 12, i % 12 + 1, 1).isoformat() for i in range(n)]
    return {
        "meta": {
            "variable_id": "merra2_t2m",
            "concept_id": "air_temperature_2m",
            "dataset_id": "M2TMNXSLV",
            "dataset_version": "5.12.4",
            "units": "K",
            "region_id": "ar6:ARC",
        },
        "dates": dates,
        "values": [round(float(v), 4) for v in values],
    }
