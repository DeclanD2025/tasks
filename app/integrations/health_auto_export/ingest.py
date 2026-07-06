"""Apply a Health Auto Export payload pushed or uploaded over the web.

Two entry paths share this module:
  * ``POST /api/ingest/hae`` — the HAE iOS app's "REST API" automation pushes
    its JSON export directly to a deployed ORION, so the cloud copy stays
    fresh without a Mac in the loop.
  * The Data Vault upload form — a dragged-in HAE export file.

Both funnel into :func:`apply_payload`, which reuses the folder connector's
parsing and upsert rules exactly (same aliases, same reductions), so a metric
means the same thing no matter how it arrived.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import ActivityMetricDaily, DataSource, Domain, HealthMetricDaily, Workout
from app.integrations.health_auto_export.parser import parse_payload
from app.integrations.health_auto_export.workouts import SOURCE, normalise_workout

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
_ACTIVITY_COLUMN_MAP = {"steps": "steps", "exercise_minutes": "active_minutes"}
_ACTIVITY_EXTRA_KEYS = ("active_energy_kcal",)


def _upsert_metric_rows(session: Session, user_id: int, records: list[dict]) -> int:
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


def _upsert_workouts(session: Session, user_id: int, workouts: list[dict]) -> tuple[int, int]:
    written, rejected = 0, 0
    for raw in workouts:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        normalised = normalise_workout(raw)
        source_id = normalised.pop("source_id", None)
        if not source_id or normalised.get("started_at") is None:
            rejected += 1
            continue
        row = session.scalars(
            select(Workout).where(
                Workout.user_id == user_id,
                Workout.source == SOURCE,
                Workout.source_id == source_id,
            )
        ).first()
        if row is None:
            row = Workout(user_id=user_id, source=SOURCE, source_id=source_id)
            session.add(row)
        for key, value in normalised.items():
            setattr(row, key, value)
        written += 1
    return written, rejected


def _touch_source(session: Session, user_id: int) -> None:
    src = session.scalars(
        select(DataSource).where(
            DataSource.user_id == user_id, DataSource.key == "health_auto_export"
        )
    ).first()
    if src is None:
        src = DataSource(
            user_id=user_id,
            key="health_auto_export",
            name="Health Auto Export",
            domain=Domain.health,
        )
        session.add(src)
    src.status = "connected"
    src.last_synced_at = datetime.now()


def apply_payload(session: Session, user_id: int, payload: dict) -> dict:
    """Upsert one HAE JSON payload; returns an import report, never raises.

    Report keys: ok, days, workouts, rejected, error.
    """
    if not isinstance(payload, dict):
        return {"ok": False, "days": 0, "workouts": 0, "rejected": 0,
                "error": "Payload is not a JSON object."}
    try:
        metric_rows = parse_payload(payload)
        days = _upsert_metric_rows(session, user_id, metric_rows)
        raw_workouts = (payload.get("data") or {}).get("workouts") or []
        workouts, rejected = _upsert_workouts(session, user_id, raw_workouts)
        if days or workouts:
            _touch_source(session, user_id)
        session.flush()
        return {"ok": True, "days": days, "workouts": workouts, "rejected": rejected, "error": ""}
    except Exception as exc:  # noqa: BLE001 — report, don't 500 a data push
        log.warning("HAE ingest failed: %s", exc)
        return {"ok": False, "days": 0, "workouts": 0, "rejected": 0, "error": str(exc)[:300]}
