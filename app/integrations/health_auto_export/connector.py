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

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ActivityMetricDaily, Domain, HealthMetricDaily
from app.ingestion.base import Connector
from app.integrations.apple_health.connector import AppleHealthConnector
from app.integrations.health_auto_export.parser import (
    latest_export_file,
    parse_folder,
)
from app.integrations.health_auto_export.workouts import import_workouts_from_folder

log = get_logger(__name__)

_EXTRA_KEYS = (
    "mood",
    "mindful_minutes",
    "distance_km",
    "vo2max",
    "respiratory_rate",
    "active_energy_kcal",
)
_COLUMN_KEYS = ("sleep_minutes", "hrv_ms", "resting_hr", "weight_kg")
_ACTIVITY_COLUMN_MAP = {
    "steps": "steps",
    "exercise_minutes": "active_minutes",
}
_ACTIVITY_EXTRA_KEYS = ("active_energy_kcal",)


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
        written = 0
        for r in records:
            day = date.fromisoformat(r["day"])
            row = session.scalars(
                select(HealthMetricDaily).where(
                    HealthMetricDaily.user_id == user_id,
                    HealthMetricDaily.day == day,
                )
            ).first()
            if row is None:
                row = HealthMetricDaily(user_id=user_id, day=day)
                session.add(row)
            for col in _COLUMN_KEYS:
                if r.get(col) is not None:
                    setattr(row, col, r[col])
            if any(r.get(k) is not None for k in _EXTRA_KEYS):
                extra = dict(row.extra or {})
                for k in _EXTRA_KEYS:
                    if r.get(k) is not None:
                        extra[k] = r[k]
                row.extra = extra
            if any(r.get(k) is not None for k in (*_ACTIVITY_COLUMN_MAP, *_ACTIVITY_EXTRA_KEYS)):
                activity = session.scalars(
                    select(ActivityMetricDaily).where(
                        ActivityMetricDaily.user_id == user_id,
                        ActivityMetricDaily.day == day,
                    )
                ).first()
                if activity is None:
                    activity = ActivityMetricDaily(user_id=user_id, day=day)
                    session.add(activity)
                for src_key, column in _ACTIVITY_COLUMN_MAP.items():
                    if r.get(src_key) is not None:
                        setattr(activity, column, r[src_key])
                if any(r.get(k) is not None for k in _ACTIVITY_EXTRA_KEYS):
                    activity_extra = dict(activity.extra or {})
                    for key in _ACTIVITY_EXTRA_KEYS:
                        if r.get(key) is not None:
                            activity_extra[key] = r[key]
                    activity.extra = activity_extra
            written += 1
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
