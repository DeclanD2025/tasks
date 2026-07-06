from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app import services
from app.db.database import session_scope
from app.db.models import Workout
from app.domains.fitness import route_service as routes


def _workout(user_id: int, *, title="Bellshill 3K", seconds=1320, hr=150) -> int:
    geometry = [
        {"lat": 55.816, "lng": -4.026, "distance_from_start_meters": 0},
        {"lat": 55.817, "lng": -4.020, "distance_from_start_meters": 500},
        {"lat": 55.819, "lng": -4.018, "distance_from_start_meters": 1000},
        {"lat": 55.820, "lng": -4.024, "distance_from_start_meters": 2000},
        {"lat": 55.816, "lng": -4.026, "distance_from_start_meters": 3000},
    ]
    with session_scope() as s:
        row = Workout(
            user_id=user_id,
            source="test",
            source_id=f"{title}-{seconds}-{uuid4().hex}",
            title=title,
            sport_type="run",
            started_at=datetime(2026, 6, 25, 7, 0, tzinfo=timezone.utc),
            duration_seconds=seconds,
            moving_time_seconds=seconds,
            distance_meters=3000,
            average_heart_rate=hr,
            max_heart_rate=170,
            elevation_gain_meters=22,
            route_geometry=geometry,
        )
        s.add(row)
        s.flush()
        return row.id


def test_create_route_from_workout_creates_first_attempt():
    uid = services.get_default_user_id()
    workout_id = _workout(uid)

    route_id = routes.create_route(
        uid,
        name="Bellshill 3K Loop",
        sport_type="run",
        template_workout_id=workout_id,
    )
    dashboard = routes.get_route_dashboard(uid, route_id)

    assert dashboard is not None
    assert dashboard.route.name == "Bellshill 3K Loop"
    assert dashboard.route.distance_meters == 3000
    assert len(dashboard.route.route_geometry) == 5
    assert len(dashboard.attempts) == 1
    assert dashboard.route.stats.best_time_seconds == 1320
    assert dashboard.distance_markers


def test_route_stats_and_match_confidence_compare_attempts():
    uid = services.get_default_user_id()
    first = _workout(uid, seconds=1320, hr=152)
    second = _workout(uid, title="Bellshill 3K Latest", seconds=1380, hr=144)
    route_id = routes.create_route(uid, name="Bellshill 3K Loop", sport_type="run", template_workout_id=first)
    routes.assign_workout_to_route(uid, second, route_id)

    dashboard = routes.get_route_dashboard(uid, route_id)
    workout = routes.list_workouts(uid, limit=10)[0]
    confidence = routes.calculate_route_match_confidence(workout, dashboard.route)

    assert dashboard.route.stats.attempts == 2
    assert dashboard.route.stats.best_time_seconds == 1320
    assert dashboard.route.stats.latest_vs_pb_seconds == 60
    assert confidence >= 75
    assert any("average HR" in insight for insight in dashboard.insights)


def test_route_without_gps_degrades_gracefully():
    uid = services.get_default_user_id()
    route_id = routes.create_route(uid, name="Treadmill 5K", sport_type="run")
    dashboard = routes.get_route_dashboard(uid, route_id)

    assert dashboard is not None
    assert dashboard.route.route_geometry == []
    assert dashboard.distance_markers == []
    assert dashboard.insights
