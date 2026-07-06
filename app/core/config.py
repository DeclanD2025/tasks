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

    # Opt-in: store the database (and state) in iCloud Drive so it syncs across
    # your Macs. Set ORION_ICLOUD_SYNC=1. See `data_dir` for the caveat about
    # not running ORION on two Macs simultaneously.
    icloud_sync: bool = Field(default=False)

    # Optional unlock passphrase for the login screen. See core.security.
    unlock_passphrase: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def icloud_dir(self) -> Path | None:
        """The ORION folder inside iCloud Drive, if it's available on this Mac.

        iCloud Drive lives at ``~/Library/Mobile Documents/com~apple~CloudDocs``.
        Returns ``None`` (so callers fall back to local) when that path doesn't
        exist — e.g. iCloud Drive is disabled or we're not on macOS.
        """
        base = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        if not base.exists():
            return None
        return base / "ORION"

    @property
    def data_dir(self) -> Path:
        """Per-user writable directory for the database and other state.

        Defaults to the OS app-data dir. With ``ORION_ICLOUD_SYNC=1`` (and iCloud
        Drive available) this moves into iCloud Drive so all your Macs share one
        ORION. Caveat: SQLite file-sync is single-writer — don't run ORION on two
        Macs at the same time, or iCloud may create conflict copies.
        """
        if self.icloud_sync:
            icloud = self.icloud_dir
            if icloud is not None:
                icloud.mkdir(parents=True, exist_ok=True)
                return icloud
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


def migrate_db_to_icloud_if_needed() -> str | None:
    """When iCloud sync is on, move an existing local DB into iCloud once.

    Idempotent and safe:
      * does nothing unless ``ORION_ICLOUD_SYNC=1`` and iCloud Drive exists;
      * if iCloud already has a DB, leaves it (the cloud copy wins);
      * otherwise copies the local DB into iCloud so no data is lost on switch.

    Returns a short status string when it acts, else ``None``. Call this BEFORE
    the engine is created (i.e. before ``init_db``).
    """
    import shutil

    settings = get_settings()
    if not settings.icloud_sync:
        return None
    icloud = settings.icloud_dir
    if icloud is None:
        return None

    icloud.mkdir(parents=True, exist_ok=True)
    cloud_db = icloud / "orion.db"
    local_db = Path(_dirs.user_data_dir) / "orion.db"

    if cloud_db.exists():
        return None  # cloud copy already present — use it as-is
    if local_db.exists():
        shutil.copy2(local_db, cloud_db)
        # Carry over the SQLite sidecar files if present (WAL/SHM).
        for suffix in ("-wal", "-shm"):
            side = local_db.with_name(local_db.name + suffix)
            if side.exists():
                shutil.copy2(side, cloud_db.with_name(cloud_db.name + suffix))
        return f"migrated local DB into iCloud Drive: {cloud_db}"
    return None


def asset_path(*parts: str) -> Path:
    """Resolve a bundled asset path, working both from source and when frozen.

    PyInstaller unpacks bundled data under ``sys._MEIPASS``; from source we use
    the package directory.
    """
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "app" / Path(*parts)
    return Path(__file__).resolve().parent.parent / Path(*parts)
