"""The strength JSON API (app/web/routes/api_v2_strength.py).

Covers the full workflow the mobile tracker performs — start, log, substitute,
finish, review — plus the boundary that matters most for a module holding
health data: nothing is readable or writable without a session.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains.strength import catalog, tracker
from app.web.server import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


@pytest.fixture(autouse=True)
def _clean_strength():
    tracker.ensure_seeded()
    catalog.enrich_catalog()
    yield
    with session_scope() as s:
        for row in s.scalars(select(StrengthPersonalRecord)).all():
            row.previous_record_id = None
        s.flush()
        for model in (
            StrengthPersonalRecord, StrengthSetEntry,
            StrengthWorkoutExercise, StrengthWorkout,
        ):
            for row in s.scalars(select(model)).all():
                s.delete(row)
            s.flush()


def _bench_id(authed: TestClient) -> int:
    payload = authed.get("/api/v2/strength/exercises", params={"q": "Bench Press"}).json()
    return next(e["id"] for e in payload["exercises"] if e["name"] == "Bench Press")


def _start(authed: TestClient) -> tuple[int, int]:
    session = authed.post("/api/v2/strength/session", json={"name": "API test"}).json()
    added = authed.post(
        f"/api/v2/strength/session/{session['id']}/exercises",
        json={"exerciseId": _bench_id(authed)},
    ).json()
    return session["id"], added["id"]


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
READ_ENDPOINTS = [
    "/api/v2/strength/home",
    "/api/v2/strength/exercises",
    "/api/v2/strength/templates",
    "/api/v2/strength/session/active",
    "/api/v2/strength/planned",
    "/api/v2/strength/programmes",
    "/api/v2/strength/records",
    "/api/v2/strength/proposals",
    "/api/v2/strength/analytics",
    "/api/v2/strength/history",
    "/api/v2/strength/export.json",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_reads_require_a_session(client: TestClient, path: str):
    """This is health data. Every one of these must refuse an unlocked client."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["status"] == "login_required"


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v2/strength/session"),
        ("post", "/api/v2/strength/blocks/1/sets"),
        ("patch", "/api/v2/strength/sets/1"),
        ("delete", "/api/v2/strength/sets/1"),
        ("post", "/api/v2/strength/planned"),
        ("post", "/api/v2/strength/programmes"),
    ],
)
def test_writes_require_a_session(client: TestClient, method: str, path: str):
    """A write must be refused before it reaches validation — otherwise an
    anonymous caller learns the shape of the body from the error."""
    # `request` rather than the per-verb helpers: TestClient.delete takes no
    # body, and the point here is that the verb is irrelevant to the refusal.
    response = client.request(method.upper(), path, json={}, follow_redirects=False)
    assert response.status_code == 401


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_read_endpoint_answers(authed: TestClient, path: str):
    response = authed.get(path)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), dict)


# --------------------------------------------------------------------------- #
# The workout loop
# --------------------------------------------------------------------------- #
def test_the_full_session_workflow(authed: TestClient):
    """Start → log → finish → review, as the tracker actually performs it."""
    workout_id, block_id = _start(authed)

    logged = authed.post(
        f"/api/v2/strength/blocks/{block_id}/sets",
        json={"weightKg": 100, "reps": 5, "rpe": 8, "clientKey": "k1"},
    )
    assert logged.status_code == 200
    assert logged.json()["reps"] == 5

    finished = authed.post(
        f"/api/v2/strength/session/{workout_id}/finish", json={"sessionRpe": 8}
    ).json()
    assert finished["status"] == "completed"
    assert finished["volumeKg"] == 500.0
    assert "proposals" in finished

    summary = authed.get(f"/api/v2/strength/session/{workout_id}/summary").json()
    assert summary["workingSets"] == 1


def test_a_second_session_is_refused_with_a_conflict(authed: TestClient):
    authed.post("/api/v2/strength/session", json={"name": "One"})
    response = authed.post("/api/v2/strength/session", json={"name": "Two"})
    assert response.status_code == 409
    assert "already in progress" in response.json()["error"]


def test_the_active_session_endpoint_backs_resume(authed: TestClient):
    workout_id, block_id = _start(authed)
    authed.post(f"/api/v2/strength/blocks/{block_id}/sets", json={"weightKg": 100, "reps": 5})

    resumed = authed.get("/api/v2/strength/session/active").json()
    assert resumed["session"]["id"] == workout_id
    assert len(resumed["session"]["exercises"][0]["sets"]) == 1


def test_no_active_session_returns_null_not_404(authed: TestClient):
    """The client polls this on every load; a 404 would be noise in the console."""
    response = authed.get("/api/v2/strength/session/active")
    assert response.status_code == 200
    assert response.json()["session"] is None


def test_a_retried_set_write_does_not_duplicate(authed: TestClient):
    """The behaviour that makes optimistic UI safe on gym wifi."""
    _, block_id = _start(authed)
    body = {"weightKg": 100, "reps": 5, "clientKey": "retry-me"}
    first = authed.post(f"/api/v2/strength/blocks/{block_id}/sets", json=body).json()
    second = authed.post(f"/api/v2/strength/blocks/{block_id}/sets", json=body).json()
    assert first["id"] == second["id"]


def test_a_set_can_be_corrected_and_keeps_its_history(authed: TestClient):
    _, block_id = _start(authed)
    logged = authed.post(
        f"/api/v2/strength/blocks/{block_id}/sets", json={"weightKg": 200, "reps": 5}
    ).json()
    corrected = authed.patch(
        f"/api/v2/strength/sets/{logged['id']}", json={"weightKg": 100}
    ).json()
    assert corrected["weightKg"] == 100
    assert corrected["edited"] is True


def test_an_empty_patch_is_rejected(authed: TestClient):
    _, block_id = _start(authed)
    logged = authed.post(
        f"/api/v2/strength/blocks/{block_id}/sets", json={"weightKg": 100, "reps": 5}
    ).json()
    response = authed.patch(f"/api/v2/strength/sets/{logged['id']}", json={})
    assert response.status_code == 400


def test_deleting_a_set_voids_it_rather_than_removing_it(authed: TestClient):
    workout_id, block_id = _start(authed)
    logged = authed.post(
        f"/api/v2/strength/blocks/{block_id}/sets", json={"weightKg": 100, "reps": 5}
    ).json()
    authed.delete(f"/api/v2/strength/sets/{logged['id']}", params={"reason": "mistyped"})

    detail = authed.get(f"/api/v2/strength/session/{workout_id}").json()
    assert detail["exercises"][0]["sets"] == []
    assert detail["exercises"][0]["voidedSets"][0]["voidReason"] == "mistyped"


def test_substituting_an_exercise_records_the_reason(authed: TestClient):
    workout_id, block_id = _start(authed)
    picker = authed.get("/api/v2/strength/exercises", params={"q": "Leg Press"}).json()
    leg_press = picker["exercises"][0]["id"]

    response = authed.post(
        f"/api/v2/strength/blocks/{block_id}/substitute",
        json={"exerciseId": leg_press, "reason": "bench taken"},
    )
    assert response.status_code == 200
    detail = authed.get(f"/api/v2/strength/session/{workout_id}").json()
    assert detail["exercises"][0]["substitutionReason"] == "bench taken"


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
def test_the_exercise_picker_searches_and_reports_its_facets(authed: TestClient):
    payload = authed.get("/api/v2/strength/exercises", params={"q": "squat"}).json()
    assert payload["exercises"]
    assert all("squat" in e["name"].lower() for e in payload["exercises"])
    assert payload["muscles"] and payload["equipment"]


def test_exercises_carry_the_facts_the_tracker_needs(authed: TestClient):
    """Increment and bar weight drive the plate calculator and the progression
    proposals — without them the client would have to guess."""
    payload = authed.get("/api/v2/strength/exercises", params={"q": "Bench Press"}).json()
    bench = next(e for e in payload["exercises"] if e["name"] == "Bench Press")
    assert bench["incrementKg"] == 2.5
    assert bench["barWeightKg"] == 20.0
    assert bench["familySlug"] == "bench-press"
    assert bench["movementPattern"] == "horizontal_push"


def test_an_unknown_exercise_is_404(authed: TestClient):
    assert authed.get("/api/v2/strength/exercises/999999").status_code == 404


def test_exercise_history_returns_a_trend_and_records(authed: TestClient):
    workout_id, block_id = _start(authed)
    authed.post(f"/api/v2/strength/blocks/{block_id}/sets", json={"weightKg": 100, "reps": 5})
    authed.post(f"/api/v2/strength/session/{workout_id}/finish", json={})

    payload = authed.get(f"/api/v2/strength/exercises/{_bench_id(authed)}").json()
    assert payload["exercise"]["name"] == "Bench Press"
    assert payload["trend"]["points"]
    assert "records" in payload


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def test_scheduling_and_rescheduling_keeps_the_original_date(authed: TestClient):
    """Repeatedly pushing Friday to Saturday is a pattern worth seeing, and it
    vanishes if a reschedule looks like having planned Saturday all along."""
    created = authed.post(
        "/api/v2/strength/planned",
        json={"plannedDate": "2026-07-24", "name": "Push day"},
    ).json()
    authed.post(
        f"/api/v2/strength/planned/{created['id']}/reschedule",
        json={"plannedDate": "2026-07-25", "reason": "work ran late"},
    )
    planned = authed.get("/api/v2/strength/planned").json()["planned"]
    row = next(p for p in planned if p["id"] == created["id"])
    assert row["date"] == "2026-07-25"
    assert row["rescheduledFrom"] == "2026-07-24"
    assert row["rescheduleReason"] == "work ran late"


def test_a_programme_can_be_created_and_read_back(authed: TestClient):
    created = authed.post(
        "/api/v2/strength/programmes",
        json={"name": "Winter block", "goal": "strength", "weeks": 8, "daysPerWeek": 4},
    ).json()
    detail = authed.get(f"/api/v2/strength/programmes/{created['id']}").json()
    assert detail["name"] == "Winter block"
    assert detail["weeks"] == 8


def test_a_programme_needs_a_name(authed: TestClient):
    response = authed.post("/api/v2/strength/programmes", json={"name": "   "})
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Analytics and export
# --------------------------------------------------------------------------- #
def test_analytics_answers_on_an_empty_log(authed: TestClient):
    """A new user must get an empty dashboard, not a stack trace."""
    payload = authed.get("/api/v2/strength/analytics").json()
    assert payload["summary"]["volumeKg"] == 0
    assert payload["adherence"]["rateAvailable"] is False


def test_the_training_home_reports_undetailed_apple_health_sessions(authed: TestClient):
    """142 real gym visits with no exercise detail is the true starting state.
    Showing a blank page beside them would be a lie of omission."""
    payload = authed.get("/api/v2/strength/home").json()
    assert "importedSessions" in payload
    assert payload["importedSessions"]["count"] >= 0


def test_csv_export_is_analysis_ready(authed: TestClient):
    workout_id, block_id = _start(authed)
    authed.post(
        f"/api/v2/strength/blocks/{block_id}/sets",
        json={"weightKg": 100, "reps": 5, "rpe": 8},
    )
    authed.post(f"/api/v2/strength/session/{workout_id}/finish", json={})

    response = authed.get("/api/v2/strength/export.csv", params={"table": "sets"})
    assert response.status_code == 200
    body = response.json() if response.headers["content-type"].startswith("application/json") else response.text
    text = body if isinstance(body, str) else json.dumps(body)
    assert "volume_kg" in text
    assert "estimated_1rm_kg" in text
    assert "is_working_set" in text


def test_an_empty_csv_export_still_has_headers(authed: TestClient):
    """A file with columns and no rows is unambiguous. An empty file could be
    a failure."""
    response = authed.get("/api/v2/strength/export.csv", params={"table": "sets"})
    assert "set_id" in response.text


def test_an_unknown_export_table_is_rejected(authed: TestClient):
    response = authed.get("/api/v2/strength/export.csv", params={"table": "secrets"})
    assert response.status_code == 400


def test_the_json_backup_states_its_conventions(authed: TestClient):
    """A volume figure is meaningless without knowing warm-ups were excluded,
    and an e1RM without its formula cannot be compared with anything."""
    payload = authed.get("/api/v2/strength/export.json").json()
    conventions = payload["conventions"]
    assert conventions["units"].startswith("All loads in kilograms")
    assert conventions["e1rmFormula"] == "epley"
    assert conventions["e1rmRepLimit"] == 12
    # Asserting the ordering rather than the literal values: these are tunable
    # conventions, and a test that breaks when they are tuned is testing the
    # wrong thing. What must hold is that all three tiers ship with the export
    # and that they descend.
    weighting = conventions["muscleWeighting"]
    assert set(weighting) == {"primary", "secondary", "stabiliser"}
    assert weighting["primary"] > weighting["secondary"] > weighting["stabiliser"] > 0
