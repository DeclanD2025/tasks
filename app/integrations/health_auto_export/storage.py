"""Shared persistence logic for Health Auto Export daily metrics.

Both the local folder connector and the HTTP payload ingest path need to
upsert the same ``HealthMetricDaily`` / ``ActivityMetricDaily`` rows from the
same parsed record shape. This module holds that logic in one place so the two
callers cannot drift apart.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActivityMetricDaily, HealthMetricDaily

_EXTRA_KEYS = (
    "mood",
    "mindful_minutes",
    "distance_km",
    "vo2max",
    "respiratory_rate",
    "active_energy_kcal",
    "bp_systolic",
    "bp_diastolic",
)
_COLUMN_KEYS = ("sleep_minutes", "hrv_ms", "resting_hr", "weight_kg")
_ACTIVITY_COLUMN_MAP = {"steps": "steps", "exercise_minutes": "active_minutes"}
_ACTIVITY_EXTRA_KEYS = ("active_energy_kcal",)


def upsert_metric_rows(session: Session, user_id: int, records: list[dict]) -> int:
    """Upsert parsed HAE metric records into daily tables.

    Args:
        session: SQLAlchemy session.
        user_id: ORION user to associate rows with.
        records: List of parsed daily record dicts from the HAE parser.

    Returns:
        Number of day rows processed.
    """
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
    return written
