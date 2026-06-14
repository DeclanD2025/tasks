"""Application configuration.

ORION is local-first. Configuration is loaded from environment variables
(optionally via a `.env` file) with sensible defaults so the app launches
with zero setup. All on-disk state lives under a per-user app-data directory
resolved by ``platformdirs`` (e.g. ``~/Library/Application Support/ORION`` on
macOS).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_dirs = PlatformDirs(appname="ORION", appauthor="ORION")


class Settings(BaseSettings):
    """Typed application settings, sourced from env / .env with defaults."""

    model_config = SettingsConfigDict(
        env_prefix="ORION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # Empty => use the default local SQLite file (see `database_url` property).
    database_url: str = Field(default="")

    # Optional unlock passphrase for the login screen. See core.security.
    unlock_passphrase: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def data_dir(self) -> Path:
        """Per-user writable directory for the database and other state."""
        path = Path(_dirs.user_data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_dir(self) -> Path:
        path = Path(_dirs.user_log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "orion.db"

    @property
    def resolved_database_url(self) -> str:
        """Effective SQLAlchemy URL.

        Defaults to a local SQLite file. Set ``ORION_DATABASE_URL`` to point at
        PostgreSQL later without touching application code.
        """
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.sqlite_path}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
