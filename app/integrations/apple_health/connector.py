"""Apple Health connector — REAL local source (export.xml).

Apple Health has no cloud API; data arrives as ``export.xml`` the user shares
from the Health app (Profile → Export All Health Data). This connector parses
that file locally and derives per-day HRV, resting HR, weight, sleep minutes and
mood (State of Mind valence, iOS 17+).

The export path is resolved from, in order:
  1. the configured setting ``ORION_APPLE_HEALTH_EXPORT``
  2. ``<app data dir>/apple_health/export.xml`` (where the Settings importer
     copies a chosen file)

If no export is present, the connector reports itself unavailable and falls back
to mock data in development (empty in production).
"""

from __future__ import annotations

import os
import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Domain, HealthMetricDaily
from app.ingestion.base import Connector
from app.integrations.apple_health.parser import parse_export

log = get_logger(__name__)

LOOKBACK_DAYS = 60


def _default_export_path() -> Path:
    return get_settings().data_dir / "apple_health" / "export.xml"


class AppleHealthConnector(Connector):
    key = "apple_health"
    name = "Apple Health"
    domain = Domain.health
    is_mock = True  # flips to False once a real export is parsed

    def export_path(self) -> Path | None:
        env = os.environ.get("ORION_APPLE_HEALTH_EXPORT")
        if env and Path(env).exists():
            return Path(env)
        default = _default_export_path()
        return default if default.exists() else None

    @property
    def available(self) -> bool:
        return self.export_path() is not None

    def connect(self) -> bool:
        return self.available

    def fetch_raw_data(self) -> list[dict]:
        path = self.export_path()
        if path is not None:
            try:
                rows = parse_export(path, lookback_days=LOOKBACK_DAYS)
                if rows:
                    self.is_mock = False
                    return rows
            except Exception as exc:  # malformed export shouldn't crash sync
                log.warning("Apple Health parse failed: %s", exc)
        self.is_mock = True
        if get_settings().is_production:
            return []
        return self._fetch_mock()

    # --- persistence: upsert HealthMetricDaily (mood -> extra) ------------- #
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
            for col in ("sleep_minutes", "hrv_ms", "resting_hr", "weight_kg"):
                if r.get(col) is not None:
                    setattr(row, col, r[col])
            if r.get("mood") is not None or r.get("mindful_minutes") is not None:
                extra = dict(row.extra or {})
                if r.get("mood") is not None:
                    extra["mood"] = r["mood"]
                if r.get("mindful_minutes") is not None:
                    extra["mindful_minutes"] = r["mindful_minutes"]
                row.extra = extra
            written += 1
        session.flush()
        return written

    def _fetch_mock(self) -> list[dict]:
        today = date.today()
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            out.append({
                "day": day.isoformat(),
                "sleep_minutes": random.randint(360, 510),
                "hrv_ms": round(random.uniform(38, 78), 1),
                "resting_hr": random.randint(48, 62),
                "weight_kg": round(random.uniform(78.0, 80.5), 1),
                "mood": round(random.uniform(-0.2, 0.6), 3),
                # Mock a Stoic-like practice cadence: most days a short session.
                "mindful_minutes": random.choice([0, 0, 8, 10, 12, 15]),
                "source": "apple_health_mock",
            })
        return out
