"""Completed-workout import for Health Auto Export JSON files."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workout

SOURCE = "health_auto_export"


def workout_export_files(folder: str | Path) -> list[Path]:
    """Return HAE yearly workout JSON exports in deterministic order."""
    root = Path(folder)
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("ORION WORKOUT DATA-*.json")
        if p.is_file() and p.stat().st_size > 0
    )


def load_workouts(folder: str | Path) -> list[dict[str, Any]]:
    workouts: list[dict[str, Any]] = []
    for path in workout_export_files(folder):
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        for row in (payload.get("data") or {}).get("workouts") or []:
            if isinstance(row, dict):
                row = dict(row)
                row["_source_file"] = path.name
                workouts.append(row)
    return workouts


def import_workouts_from_folder(
    folder: str | Path,
    session: Session,
    user_id: int,
) -> int:
    """Upsert completed HAE workouts into ORION's route/workout store."""
    written = 0
    for raw in load_workouts(folder):
        normalised = normalise_workout(raw)
        source_id = normalised.pop("source_id", None)
        if not source_id or normalised.get("started_at") is None:
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
    session.flush()
    return written


def normalise_workout(raw: dict[str, Any]) -> dict[str, Any]:
    title = str(raw.get("name") or "Workout")
    started_at = parse_datetime(raw.get("start"))
    ended_at = parse_datetime(raw.get("end"))
    duration = _seconds(raw.get("duration"))
    distance_m = _quantity_meters(raw.get("distance"))
    if distance_m is None:
        distance_m = _sample_distance_meters(raw.get("walkingAndRunningDistance"))
    geometry = route_geometry(raw.get("route") or [])

    return {
        "source_id": str(raw.get("id") or ""),
        "title": title[:160],
        "sport_type": sport_type(title),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration,
        "moving_time_seconds": duration,
        "distance_meters": distance_m,
        "average_heart_rate": _quantity(raw.get("avgHeartRate")) or _heart_rate_avg(raw),
        "max_heart_rate": _quantity(raw.get("maxHeartRate")) or _heart_rate_max(raw),
        "elevation_gain_meters": _quantity_meters(raw.get("elevationUp")),
        "route_geometry": geometry,
        "splits": distance_samples(raw.get("walkingAndRunningDistance") or []),
        "extra": {
            "source_file": raw.get("_source_file"),
            "is_indoor": raw.get("isIndoor"),
            "location": raw.get("location"),
            "active_energy_kj": _quantity(raw.get("activeEnergyBurned")),
            "total_energy_kj": _quantity(raw.get("totalEnergy")),
            "avg_speed": _quantity(raw.get("avgSpeed")),
            "max_speed": _quantity(raw.get("maxSpeed")),
            "temperature_c": _quantity(raw.get("temperature")),
            "humidity": _quantity(raw.get("humidity")),
            "hae_name": title,
        },
    }


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # .hae sidecar files use Apple absolute time; yearly JSON uses strings.
        return datetime.fromtimestamp(float(value) + 978307200)
    raw = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def sport_type(name: str) -> str:
    key = name.lower()
    if "walk" in key:
        return "walk"
    if "run" in key:
        return "run"
    if "cycl" in key:
        return "cycle"
    if "soccer" in key or "football" in key:
        return "football"
    return "other"


def route_geometry(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = 0.0
    prev: tuple[float, float] | None = None
    for point in points:
        lat = _float(point.get("latitude") if "latitude" in point else point.get("lat"))
        lng = _float(point.get("longitude") if "longitude" in point else point.get("lng"))
        if lat is None or lng is None:
            continue
        if prev is not None:
            total += _distance_m(prev[0], prev[1], lat, lng)
        prev = (lat, lng)
        out.append({
            "lat": lat,
            "lng": lng,
            "timestamp": point.get("timestamp") or point.get("date"),
            "altitude": _float(point.get("altitude")),
            "distance_from_start_meters": round(total, 2),
            "heart_rate": _float(point.get("heartRate") or point.get("heart_rate")),
            "speed_meters_per_second": _float(point.get("speed")),
        })
    return out


def distance_samples(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    cumulative = 0.0
    for point in points:
        meters = _quantity_meters(point)
        if meters is None:
            continue
        cumulative += meters
        samples.append({
            "timestamp": point.get("date") or point.get("timestamp"),
            "distance_meters": round(cumulative, 2),
        })
    return samples


def _quantity(value: Any) -> float | None:
    if isinstance(value, dict):
        return _float(value.get("qty"))
    return _float(value)


def _quantity_meters(value: Any) -> float | None:
    if not isinstance(value, dict):
        return _float(value)
    qty = _float(value.get("qty"))
    if qty is None:
        return None
    units = str(value.get("units") or "").lower()
    if units in {"km", "kilometer", "kilometre", "kilometers", "kilometres"}:
        return qty * 1000.0
    if units in {"mi", "mile", "miles"}:
        return qty * 1609.344
    return qty


def _sample_distance_meters(points: Any) -> float | None:
    if not isinstance(points, list):
        return None
    total = sum((_quantity_meters(p) or 0.0) for p in points if isinstance(p, dict))
    return total or None


def _heart_rate_avg(raw: dict[str, Any]) -> float | None:
    points = raw.get("heartRateData") or []
    values = [_float(p.get("Avg")) for p in points if isinstance(p, dict)]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _heart_rate_max(raw: dict[str, Any]) -> float | None:
    points = raw.get("heartRateData") or []
    values = [_float(p.get("Max")) for p in points if isinstance(p, dict)]
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _seconds(value: Any) -> int | None:
    val = _float(value)
    return int(round(val)) if val is not None else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
