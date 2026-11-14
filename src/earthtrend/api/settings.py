"""Process settings, read from the environment and ``.env`` (see ``.env.example``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    db_url: str = "sqlite+aiosqlite:///data/app.db"
    storage_root: Path = Path("data/storage")
    catalog_dir: Path = Path("catalog")
    models_dir: Path = Path("models")
    # Synchronous analysis budget per request (Plan_Backend 4: compute path stays open).
    analytics_timeout_s: float = 30.0
    cors_origins: list[str] = ["http://localhost:5173"]
    log_json: bool = False

    @property
    def debug(self) -> bool:
        return self.env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
