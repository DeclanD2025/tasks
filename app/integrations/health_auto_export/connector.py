"""Health Auto Export connector — auto-updating Apple Health via dropped files.

Health Auto Export (iOS) writes JSON exports on a schedule to a folder you
choose (typically iCloud Drive, which syncs to this Mac). ORION points at that
folder, reads the most recent export, and upserts the same HealthMetricDaily
rows every other module consumes — so Health, Fitness and the Stoic observatory
all light up, and refresh whenever a new file lands.

Folder resolution order:
  1. ``ORION_HAE_FOLDER`` env var
  2. ``<app data dir>/health_auto_export`` (where Settings stores a chosen path)

If no folder/file is present, reports unavailable and (in dev) falls back to the
same mock as the Apple Health connector so the demo still works.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Domain
from app.ingestion.base import Connector
from app.integrations.apple_health.connector import AppleHealthConnector
from app.integrations.health_auto_export.parser import (
    latest_export_file,
    parse_folder,
)
from app.integrations.health_auto_export.storage import upsert_metric_rows
from app.integrations.health_auto_export.workouts import import_workouts_from_folder

log = get_logger(__name__)


def _config_path() -> Path:
    return get_settings().data_dir / "health_auto_export" / "folder.txt"


class HealthAutoExportConnector(Connector):
    key = "health_auto_export"
    name = "Health Auto Export"
    domain = Domain.health
    is_mock = True  # flips to False once a real export is read

    def folder(self) -> Path | None:
        env = os.environ.get("ORION_HAE_FOLDER")
        if env and Path(env).expanduser().exists():
            return Path(env).expanduser()
        cfg = _config_path()
        if cfg.exists():
            stored = Path(cfg.read_text(encoding="utf-8").strip()).expanduser()
            if stored.exists():
                return stored
        default = get_settings().data_dir / "health_auto_export"
        return default if default.exists() else None

    def set_folder(self, path: str) -> None:
        cfg = _config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(str(path), encoding="utf-8")

    def latest_file(self) -> Path | None:
        folder = self.folder()
        return latest_export_file(folder) if folder else None

    @property
    def available(self) -> bool:
        return self.latest_file() is not None

    def connect(self) -> bool:
        return self.available

    def fetch_raw_data(self) -> list[dict]:
        folder = self.folder()
        if folder is not None:
            try:
                # Merge across category files (Health Metrics + State of Mind …).
                rows = parse_folder(folder)
                if rows:
                    self.is_mock = False
                    return rows
            except Exception as exc:  # malformed files shouldn't crash sync
                log.warning("Health Auto Export parse failed: %s", exc)
        self.is_mock = True
        if get_settings().is_production:
            return []
        # Dev fallback: reuse the Apple Health mock generator.
        return AppleHealthConnector()._fetch_mock()

    def store_normalised_data(self, session, user_id, source_id, records) -> int:
        written = upsert_metric_rows(session, user_id, records)
        folder = self.folder()
        if folder is not None:
            written += import_workouts_from_folder(folder, session, user_id)
        session.flush()
        return written

    def latest_day(self, user_id: int) -> date | None:
        """Most recent day we have HealthMetricDaily data for (freshness check)."""
        from app.db.database import session_scope

        with session_scope() as s:
            day = s.scalars(
                select(HealthMetricDaily.day)
                .where(HealthMetricDaily.user_id == user_id)
                .order_by(HealthMetricDaily.day.desc())
                .limit(1)
            ).first()
            return day
