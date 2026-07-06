from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains import strength
from app.services import get_default_user_id
from app.web.server import create_app


def _authed() -> TestClient:
    client = TestClient(create_app())
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def test_strength_seed_has_required_exercises_and_templates():
    strength.ensure_seeded()
    with session_scope() as s:
        names = set(s.scalars(select(StrengthExercise.name)).all())
    assert len(names) >= 80
    for name in [
        "Bench Press",
        "Incline Bench Press",
        "Lat Pulldown",
        "Squat",
        "Romanian Deadlift",
        "Tricep Pushdown",
        "Hanging Leg Raise",
    ]:
        assert name in names
    template_names = {row["name"] for row in strength.templates()}
    assert {
        "Upper Body Accessories",
        "Lower Body",
        "Push",
        "Pull",
        "Legs",
        "Full Body",
        "Chest & Triceps",
        "Back & Biceps",
        "Shoulders & Arms",
    } <= template_names


def test_strength_routes_render_and_template_start_flow():
    client = _authed()
    assert client.get("/strength").status_code == 200
    assert client.get("/strength/analytics").status_code == 200
    templates_page = client.get("/strength/templates")
    assert templates_page.status_code == 200
    assert "Upper Body Accessories" in templates_page.text

    template_id = strength.templates()[0]["id"]
    preview = client.get(f"/strength/templates/{template_id}")
    assert preview.status_code == 200
    assert "Device iPhone" in preview.text

    response = client.post(
        "/strength/start",
        data={"template_id": str(template_id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/strength/workout/")
    workout = client.get(response.headers["location"])
    assert workout.status_code == 200
    assert "Active cockpit" in workout.text
    assert "Last time you did this" in workout.text


def test_strength_set_logging_finish_history_and_exercise_detail():
    client = _authed()
    uid = get_default_user_id()
    active = strength.active_workout(uid)
    if active:
        strength.discard_workout(uid, active["id"])
    bench = strength.exercise_picker(uid, q="Bench Press")["exercises"][0]
    workout_id = strength.start_workout(uid, name="Test Push")
    strength.add_exercise_to_workout(uid, workout_id, bench["id"])

    with session_scope() as s:
        we = s.scalars(
            select(StrengthWorkoutExercise).where(
                StrengthWorkoutExercise.workout_id == workout_id
            )
        ).first()
        first_set = s.scalars(
            select(StrengthSetEntry).where(StrengthSetEntry.workout_exercise_id == we.id)
        ).first()

    response = client.post(
        f"/strength/sets/{first_set.id}",
        data={
            "workout_id": str(workout_id),
            "weight": "80",
            "reps": "5",
            "rpe": "8",
            "set_type": "working",
            "completed": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = client.post(
        f"/strength/workout/{workout_id}/finish",
        data={"notes": "Felt strong"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with session_scope() as s:
        workout = s.get(StrengthWorkout, workout_id)
    assert workout.status == "completed"

    history = client.get("/strength/history")
    assert history.status_code == 200
    assert "Test Push" in history.text

    detail = client.get(f"/strength/exercises/{bench['id']}")
    assert detail.status_code == 200
    assert "Best e1RM" in detail.text
    assert "80.0" in detail.text or "80" in detail.text
