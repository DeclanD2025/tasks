"""Route Intelligence service for completed workouts.

The planner stays in ``fitness_service``. This module owns completed workouts,
route definitions, route attempts, matching foundations, and deterministic
route-performance read models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, select

from app.db.database import session_scope
from app.db.models import FitnessRoute, RouteAttempt, RouteSegment, Workout, utcnow


SPORT_TYPES = ("run", "walk", "cycle", "football", "other")


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lng: float
    timestamp: str | None = None
    altitude: float | None = None
    distance_from_start_meters: float | None = None
    heart_rate: float | None = None
    speed_meters_per_second: float | None = None
    pace_seconds_per_km: float | None = None


@dataclass(frozen=True)
class WorkoutReadout:
    id: int
    title: str
    sport_type: str
    started_at: datetime
    duration_seconds: int | None
    distance_meters: float | None
    average_heart_rate: float | None
    max_heart_rate: float | None
    elevation_gain_meters: float | None
    route_geometry: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RouteAttemptReadout:
    id: int
    route_id: int
    workout_id: int
    attempt_date: date
    duration_seconds: int | None
    moving_time_seconds: int | None
    distance_meters: float | None
    average_pace_seconds_per_km: float | None
    average_heart_rate: float | None
    max_heart_rate: float | None
    elevation_gain_meters: float | None
    route_match_confidence: float | None
    manually_tagged: bool
    notes: str
    workout_title: str = ""
    route_geometry: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RouteSegmentReadout:
    id: int
    route_id: int
    name: str
    start_distance_meters: float
    end_distance_meters: float
    description: str = ""


@dataclass(frozen=True)
class RouteStats:
    attempts: int = 0
    best_time_seconds: int | None = None
    latest_time_seconds: int | None = None
    average_time_seconds: int | None = None
    fastest_pace_seconds_per_km: float | None = None
    latest_pace_seconds_per_km: float | None = None
    lowest_average_heart_rate: float | None = None
    latest_vs_pb_seconds: int | None = None
    best_attempt_id: int | None = None
    latest_attempt_id: int | None = None


@dataclass(frozen=True)
class RouteReadout:
    id: int
    name: str
    sport_type: str
    description: str
    distance_meters: float | None
    estimated_duration_seconds: int | None
    start_lat: float | None
    start_lng: float | None
    end_lat: float | None
    end_lng: float | None
    route_geometry: list[dict]
    elevation_gain_meters: float | None
    difficulty_score: float | None
    created_at: datetime
    updated_at: datetime
    stats: RouteStats = field(default_factory=RouteStats)


@dataclass(frozen=True)
class RouteMatchSuggestion:
    route_id: int
    route_name: str
    confidence: float


@dataclass(frozen=True)
class RouteDashboard:
    route: RouteReadout
    attempts: list[RouteAttemptReadout]
    segments: list[RouteSegmentReadout]
    best_attempt: RouteAttemptReadout | None
    latest_attempt: RouteAttemptReadout | None
    insights: list[str]
    distance_markers: list[dict]


def list_routes(user_id: int) -> list[RouteReadout]:
    with session_scope() as s:
        routes = s.scalars(
            select(FitnessRoute)
            .where(FitnessRoute.user_id == user_id)
            .order_by(desc(FitnessRoute.updated_at), FitnessRoute.name)
        ).all()
        route_ids = [row.id for row in routes]
        attempts_by_route: dict[int, list[RouteAttemptReadout]] = {rid: [] for rid in route_ids}
        if route_ids:
            rows = s.execute(
                select(RouteAttempt, Workout)
                .join(Workout, Workout.id == RouteAttempt.workout_id)
                .where(RouteAttempt.route_id.in_(route_ids))
                .order_by(RouteAttempt.attempt_date)
            ).all()
            for attempt, workout in rows:
                attempts_by_route.setdefault(attempt.route_id, []).append(_attempt_readout(attempt, workout))
        return [_route_readout(row, attempts_by_route.get(row.id, [])) for row in routes]


def get_route_dashboard(user_id: int, route_id: int) -> RouteDashboard | None:
    with session_scope() as s:
        route = s.get(FitnessRoute, route_id)
        if route is None or route.user_id != user_id:
            return None
        rows = s.execute(
            select(RouteAttempt, Workout)
            .join(Workout, Workout.id == RouteAttempt.workout_id)
            .where(RouteAttempt.route_id == route_id)
            .order_by(desc(RouteAttempt.attempt_date), desc(RouteAttempt.id))
        ).all()
        attempts = [_attempt_readout(attempt, workout) for attempt, workout in rows]
        segments = [
            RouteSegmentReadout(row.id, row.route_id, row.name, row.start_distance_meters, row.end_distance_meters, row.description or "")
            for row in s.scalars(
                select(RouteSegment)
                .where(RouteSegment.route_id == route_id)
                .order_by(RouteSegment.start_distance_meters)
            ).all()
        ]
    route_readout = _route_readout(route, attempts)
    best = calculate_best_attempt(attempts)
    latest = calculate_latest_attempt(attempts)
    return RouteDashboard(
        route=route_readout,
        attempts=attempts,
        segments=segments,
        best_attempt=best,
        latest_attempt=latest,
        insights=route_insights(route_readout, attempts),
        distance_markers=calculate_distance_markers(route_readout.route_geometry, 500.0),
    )


def list_workouts(user_id: int, *, limit: int = 30) -> list[WorkoutReadout]:
    with session_scope() as s:
        rows = s.scalars(
            select(Workout)
            .where(Workout.user_id == user_id)
            .order_by(desc(Workout.started_at), desc(Workout.id))
            .limit(limit)
        ).all()
        return [_workout_readout(row) for row in rows]


def create_route(
    user_id: int,
    *,
    name: str,
    sport_type: str = "run",
    description: str = "",
    template_workout_id: int | None = None,
) -> int:
    sport = sport_type if sport_type in SPORT_TYPES else "other"
    with session_scope() as s:
        workout = s.get(Workout, template_workout_id) if template_workout_id else None
        if workout is not None and workout.user_id != user_id:
            workout = None
        geometry = extract_route_geometry_from_workout(_workout_readout(workout)) if workout else []
        start, finish = extract_start_finish(geometry)
        route = FitnessRoute(
            user_id=user_id,
            name=(name.strip() or "Untitled Route")[:160],
            sport_type=workout.sport_type if workout else sport,
            description=description.strip(),
            distance_meters=workout.distance_meters if workout else calculate_total_route_distance(geometry) or None,
            estimated_duration_seconds=workout.duration_seconds if workout else None,
            start_lat=start.get("lat") if start else None,
            start_lng=start.get("lng") if start else None,
            end_lat=finish.get("lat") if finish else None,
            end_lng=finish.get("lng") if finish else None,
            route_geometry=geometry,
            elevation_gain_meters=workout.elevation_gain_meters if workout else None,
            updated_at=utcnow(),
        )
        s.add(route)
        s.flush()
        route_id = route.id
        if workout is not None:
            _create_attempt_row(s, workout, route, manually_tagged=True, confidence=100.0)
        return route_id


def delete_route(user_id: int, route_id: int) -> None:
    with session_scope() as s:
        route = s.get(FitnessRoute, route_id)
        if route is None or route.user_id != user_id:
            return
        for row in s.scalars(select(RouteAttempt).where(RouteAttempt.route_id == route_id)).all():
            s.delete(row)
        for row in s.scalars(select(RouteSegment).where(RouteSegment.route_id == route_id)).all():
            s.delete(row)
        s.delete(route)


def assign_workout_to_route(user_id: int, workout_id: int, route_id: int, *, manually_tagged: bool = True) -> int | None:
    with session_scope() as s:
        workout = s.get(Workout, workout_id)
        route = s.get(FitnessRoute, route_id)
        if workout is None or route is None or workout.user_id != user_id or route.user_id != user_id:
            return None
        confidence = calculate_route_match_confidence(_workout_readout(workout), _route_readout(route, []))
        attempt = _create_attempt_row(s, workout, route, manually_tagged=manually_tagged, confidence=confidence)
        route.updated_at = utcnow()
        return attempt.id


def possible_route_matches(user_id: int, workout_id: int, *, limit: int = 5) -> list[RouteMatchSuggestion]:
    workouts = {row.id: row for row in list_workouts(user_id, limit=250)}
    workout = workouts.get(workout_id)
    if workout is None:
        return []
    suggestions = [
        RouteMatchSuggestion(route.id, route.name, calculate_route_match_confidence(workout, route))
        for route in list_routes(user_id)
        if route.id is not None
    ]
    return sorted([s for s in suggestions if s.confidence >= 50.0], key=lambda s: s.confidence, reverse=True)[:limit]


def create_segment(route_id: int, name: str, start_m: float, end_m: float, description: str = "") -> int:
    with session_scope() as s:
        route = s.get(FitnessRoute, route_id)
        if route is None:
            raise ValueError("Route not found")
        lo, hi = sorted((max(0.0, float(start_m)), max(0.0, float(end_m))))
        row = RouteSegment(
            route_id=route_id,
            name=(name.strip() or "Segment")[:120],
            start_distance_meters=lo,
            end_distance_meters=hi,
            description=description.strip(),
        )
        s.add(row)
        s.flush()
        route.updated_at = utcnow()
        return row.id


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds_per_km: int | float | None) -> str:
    if seconds_per_km is None:
        return "—"
    return f"{format_duration(seconds_per_km)}/km"


def calculate_pace(duration_seconds: int | float | None, distance_meters: int | float | None) -> float | None:
    if not duration_seconds or not distance_meters or distance_meters <= 0:
        return None
    return float(duration_seconds) / (float(distance_meters) / 1000.0)


def calculate_best_attempt(attempts: list[RouteAttemptReadout]) -> RouteAttemptReadout | None:
    valid = [row for row in attempts if row.duration_seconds is not None]
    return min(valid, key=lambda row: row.duration_seconds) if valid else None


def calculate_latest_attempt(attempts: list[RouteAttemptReadout]) -> RouteAttemptReadout | None:
    return max(attempts, key=lambda row: (row.attempt_date, row.id)) if attempts else None


def calculate_average_attempt_time(attempts: list[RouteAttemptReadout]) -> int | None:
    values = [row.duration_seconds for row in attempts if row.duration_seconds is not None]
    return int(round(sum(values) / len(values))) if values else None


def calculate_attempt_delta(latest: RouteAttemptReadout | None, best: RouteAttemptReadout | None) -> dict[str, float | None]:
    if latest is None or best is None:
        return {"time": None, "pace": None, "avg_hr": None, "max_hr": None, "distance": None}
    return {
        "time": _delta(latest.duration_seconds, best.duration_seconds),
        "pace": _delta(latest.average_pace_seconds_per_km, best.average_pace_seconds_per_km),
        "avg_hr": _delta(latest.average_heart_rate, best.average_heart_rate),
        "max_hr": _delta(latest.max_heart_rate, best.max_heart_rate),
        "distance": _delta(latest.distance_meters, best.distance_meters),
    }


def calculate_route_stats(_route: RouteReadout | FitnessRoute, attempts: list[RouteAttemptReadout]) -> RouteStats:
    best = calculate_best_attempt(attempts)
    latest = calculate_latest_attempt(attempts)
    paces = [row.average_pace_seconds_per_km for row in attempts if row.average_pace_seconds_per_km is not None]
    hrs = [row.average_heart_rate for row in attempts if row.average_heart_rate is not None]
    return RouteStats(
        attempts=len(attempts),
        best_time_seconds=best.duration_seconds if best else None,
        latest_time_seconds=latest.duration_seconds if latest else None,
        average_time_seconds=calculate_average_attempt_time(attempts),
        fastest_pace_seconds_per_km=min(paces) if paces else None,
        latest_pace_seconds_per_km=latest.average_pace_seconds_per_km if latest else None,
        lowest_average_heart_rate=min(hrs) if hrs else None,
        latest_vs_pb_seconds=(
            latest.duration_seconds - best.duration_seconds
            if latest and best and latest.duration_seconds is not None and best.duration_seconds is not None
            else None
        ),
        best_attempt_id=best.id if best else None,
        latest_attempt_id=latest.id if latest else None,
    )


def calculate_route_match_confidence(workout: WorkoutReadout, route: RouteReadout) -> float:
    score = 0.0
    if workout.sport_type == route.sport_type:
        score += 10.0
    if workout.distance_meters and route.distance_meters:
        diff = abs(workout.distance_meters - route.distance_meters) / max(route.distance_meters, 1.0)
        score += max(0.0, 25.0 * (1.0 - min(diff, 1.0)))
    workout_points = normalise_route_points(workout.route_geometry)
    route_points = normalise_route_points(route.route_geometry)
    if workout_points and route_points:
        w_start, w_end = extract_start_finish(workout_points)
        r_start, r_end = extract_start_finish(route_points)
        if w_start and r_start:
            score += max(0.0, 25.0 * (1.0 - min(calculate_distance_between_points(w_start, r_start) / 250.0, 1.0)))
        if w_end and r_end:
            score += max(0.0, 20.0 * (1.0 - min(calculate_distance_between_points(w_end, r_end) / 250.0, 1.0)))
        score += _path_overlap_score(workout_points, route_points) * 20.0
    elif workout.title and route.name:
        if route.name.lower() in workout.title.lower() or workout.title.lower() in route.name.lower():
            score += 20.0
    return round(max(0.0, min(100.0, score)), 1)


def calculate_distance_between_points(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def normalise_route_points(points: list[Any] | None) -> list[dict]:
    out: list[dict] = []
    for item in points or []:
        if not isinstance(item, dict):
            continue
        lat = item.get("lat", item.get("latitude"))
        lng = item.get("lng", item.get("lon", item.get("longitude")))
        if lat is None or lng is None:
            continue
        try:
            row = {"lat": float(lat), "lng": float(lng)}
        except (TypeError, ValueError):
            continue
        for src, dest in [
            ("timestamp", "timestamp"),
            ("altitude", "altitude"),
            ("distanceFromStartMeters", "distance_from_start_meters"),
            ("distance_from_start_meters", "distance_from_start_meters"),
            ("heartRate", "heart_rate"),
            ("heart_rate", "heart_rate"),
            ("speedMetersPerSecond", "speed_meters_per_second"),
            ("speed_meters_per_second", "speed_meters_per_second"),
            ("paceSecondsPerKm", "pace_seconds_per_km"),
            ("pace_seconds_per_km", "pace_seconds_per_km"),
        ]:
            if item.get(src) is not None:
                row[dest] = item[src]
        out.append(row)
    if out and out[0].get("distance_from_start_meters") is None:
        total = 0.0
        out[0]["distance_from_start_meters"] = 0.0
        for idx in range(1, len(out)):
            total += calculate_distance_between_points(out[idx - 1], out[idx])
            out[idx]["distance_from_start_meters"] = total
    return out


def calculate_bounds(points: list[dict]) -> dict | None:
    pts = normalise_route_points(points)
    if not pts:
        return None
    lats = [row["lat"] for row in pts]
    lngs = [row["lng"] for row in pts]
    return {"min_lat": min(lats), "max_lat": max(lats), "min_lng": min(lngs), "max_lng": max(lngs)}


def calculate_route_bounds(route_geometry: list[dict]) -> dict | None:
    return calculate_bounds(route_geometry)


def calculate_total_route_distance(points: list[dict]) -> float:
    pts = normalise_route_points(points)
    if len(pts) < 2:
        return 0.0
    if pts[-1].get("distance_from_start_meters") is not None:
        return float(pts[-1]["distance_from_start_meters"])
    return sum(calculate_distance_between_points(pts[idx - 1], pts[idx]) for idx in range(1, len(pts)))


def calculate_distance_markers(points: list[dict], interval_meters: float = 500.0) -> list[dict]:
    pts = normalise_route_points(points)
    if len(pts) < 2 or interval_meters <= 0:
        return []
    markers: list[dict] = []
    next_distance = interval_meters
    for idx in range(1, len(pts)):
        prev = pts[idx - 1]
        cur = pts[idx]
        start_d = float(prev.get("distance_from_start_meters") or 0.0)
        end_d = float(cur.get("distance_from_start_meters") or start_d)
        while start_d < next_distance <= end_d:
            ratio = (next_distance - start_d) / max(end_d - start_d, 1.0)
            markers.append(
                {
                    "lat": prev["lat"] + (cur["lat"] - prev["lat"]) * ratio,
                    "lng": prev["lng"] + (cur["lng"] - prev["lng"]) * ratio,
                    "distance_meters": next_distance,
                }
            )
            next_distance += interval_meters
    return markers


def calculate_direction_markers(points: list[dict], every: int = 12) -> list[dict]:
    pts = normalise_route_points(points)
    markers: list[dict] = []
    for idx in range(every, len(pts), every):
        prev = pts[idx - 1]
        cur = pts[idx]
        markers.append({"lat": cur["lat"], "lng": cur["lng"], "bearing": math.degrees(math.atan2(cur["lng"] - prev["lng"], cur["lat"] - prev["lat"]))})
    return markers


def extract_start_finish(points: list[dict]) -> tuple[dict | None, dict | None]:
    pts = normalise_route_points(points)
    if not pts:
        return None, None
    return pts[0], pts[-1]


def extract_route_geometry_from_workout(workout: WorkoutReadout) -> list[dict]:
    return normalise_route_points(workout.route_geometry)


def simplify_route_geometry(points: list[dict], max_points: int = 500) -> list[dict]:
    pts = normalise_route_points(points)
    if len(pts) <= max_points:
        return pts
    step = max(1, math.ceil(len(pts) / max_points))
    return [*pts[::step], pts[-1]]


def colour_route_by_pace(points: list[dict]) -> list[dict]:
    # Future overlay hook: the map widget already accepts per-point pace values.
    return normalise_route_points(points)


def colour_route_by_heart_rate(points: list[dict]) -> list[dict]:
    # Future overlay hook: the map widget already accepts per-point HR values.
    return normalise_route_points(points)


def route_insights(route: RouteReadout, attempts: list[RouteAttemptReadout]) -> list[str]:
    best = calculate_best_attempt(attempts)
    latest = calculate_latest_attempt(attempts)
    if not attempts:
        return ["No attempts yet. Assign a completed workout to start route intelligence."]
    out = [f"You have completed this route {len(attempts)} time{'s' if len(attempts) != 1 else ''}."]
    if best and latest and best.id != latest.id:
        delta = calculate_attempt_delta(latest, best)
        if delta["time"] is not None:
            direction = "slower" if delta["time"] > 0 else "faster"
            out.append(f"Latest attempt was {format_duration(abs(delta['time']))} {direction} than PB.")
        if delta["avg_hr"] is not None and delta["avg_hr"] < 0:
            out.append(f"Latest average HR was {abs(delta['avg_hr']):.0f} bpm lower than PB effort.")
    elif best and latest:
        out.append("Latest attempt is currently the PB for this route.")
    if route.stats.lowest_average_heart_rate is not None:
        out.append(f"Lowest average HR recorded here is {route.stats.lowest_average_heart_rate:.0f} bpm.")
    return out[:5]


def _create_attempt_row(session, workout: Workout, route: FitnessRoute, *, manually_tagged: bool, confidence: float | None):
    existing = session.scalars(
        select(RouteAttempt).where(RouteAttempt.route_id == route.id, RouteAttempt.workout_id == workout.id)
    ).first()
    pace = calculate_pace(workout.moving_time_seconds or workout.duration_seconds, workout.distance_meters)
    if existing is None:
        existing = RouteAttempt(route_id=route.id, workout_id=workout.id, attempt_date=workout.started_at.date())
        session.add(existing)
        session.flush()
    existing.duration_seconds = workout.duration_seconds
    existing.moving_time_seconds = workout.moving_time_seconds
    existing.distance_meters = workout.distance_meters
    existing.average_pace_seconds_per_km = pace
    existing.average_heart_rate = workout.average_heart_rate
    existing.max_heart_rate = workout.max_heart_rate
    existing.elevation_gain_meters = workout.elevation_gain_meters
    existing.route_match_confidence = confidence
    existing.manually_tagged = manually_tagged
    return existing


def _route_readout(row: FitnessRoute, attempts: list[RouteAttemptReadout]) -> RouteReadout:
    base = RouteReadout(
        id=row.id,
        name=row.name,
        sport_type=row.sport_type,
        description=row.description or "",
        distance_meters=row.distance_meters,
        estimated_duration_seconds=row.estimated_duration_seconds,
        start_lat=row.start_lat,
        start_lng=row.start_lng,
        end_lat=row.end_lat,
        end_lng=row.end_lng,
        route_geometry=normalise_route_points(row.route_geometry),
        elevation_gain_meters=row.elevation_gain_meters,
        difficulty_score=row.difficulty_score,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    return RouteReadout(**{**base.__dict__, "stats": calculate_route_stats(base, attempts)})


def _attempt_readout(row: RouteAttempt, workout: Workout | None = None) -> RouteAttemptReadout:
    return RouteAttemptReadout(
        id=row.id,
        route_id=row.route_id,
        workout_id=row.workout_id,
        attempt_date=row.attempt_date,
        duration_seconds=row.duration_seconds,
        moving_time_seconds=row.moving_time_seconds,
        distance_meters=row.distance_meters,
        average_pace_seconds_per_km=row.average_pace_seconds_per_km,
        average_heart_rate=row.average_heart_rate,
        max_heart_rate=row.max_heart_rate,
        elevation_gain_meters=row.elevation_gain_meters,
        route_match_confidence=row.route_match_confidence,
        manually_tagged=bool(row.manually_tagged),
        notes=row.notes or "",
        workout_title=workout.title if workout else "",
        route_geometry=normalise_route_points(workout.route_geometry if workout else []),
    )


def _workout_readout(row: Workout) -> WorkoutReadout:
    return WorkoutReadout(
        id=row.id,
        title=row.title or f"{row.sport_type.title()} · {row.started_at:%d %b %Y}",
        sport_type=row.sport_type,
        started_at=row.started_at,
        duration_seconds=row.duration_seconds,
        distance_meters=row.distance_meters,
        average_heart_rate=row.average_heart_rate,
        max_heart_rate=row.max_heart_rate,
        elevation_gain_meters=row.elevation_gain_meters,
        route_geometry=normalise_route_points(row.route_geometry),
    )


def _path_overlap_score(a: list[dict], b: list[dict]) -> float:
    if not a or not b:
        return 0.0
    sample = a[:: max(1, len(a) // 20)]
    close = 0
    for point in sample:
        nearest = min(calculate_distance_between_points(point, other) for other in b[:: max(1, len(b) // 60)])
        if nearest <= 120.0:
            close += 1
    return close / max(len(sample), 1)


def _delta(a, b) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)
