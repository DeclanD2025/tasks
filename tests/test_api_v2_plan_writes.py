"""Habit and goal write endpoints — the first mutating routes in the v2 API.

Everything else under /api/v2 is an idempotent GET. These change state, so
they carry the obligations reads do not: reject bad input with a 400 rather
than a 500, refuse unauthenticated callers, and never touch another user's
rows.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.web.server import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def _habit(authed: TestClient, **overrides) -> int:
    body = {"name": "Test habit", "domain": "mind", "cadence": "daily"}
    body.update(overrides)
    response = authed.post("/api/v2/habits", json=body)
    assert response.status_code == 200, response.text
    return response.json()["id"]


# --------------------------------------------------------------------- auth
WRITE_ROUTES = [
    ("post", "/api/v2/habits", {"name": "x"}),
    ("post", "/api/v2/habits/1/day", {"day": "2026-07-18", "done": True}),
    ("delete", "/api/v2/habits/1", None),
    ("post", "/api/v2/goals", {"title": "x"}),
    ("patch", "/api/v2/goals/1", {"title": "x"}),
    ("delete", "/api/v2/goals/1", None),
]


@pytest.mark.parametrize("method,path,body", WRITE_ROUTES)
def test_writes_require_authentication(client: TestClient, method, path, body):
    """An expired session must not be able to mutate anything."""
    call = getattr(client, method)
    response = call(path, json=body) if body else call(path)
    assert response.status_code == 401, f"{method} {path} was not protected"


# ------------------------------------------------------------------- habits
def test_create_and_read_back_a_habit(authed: TestClient):
    habit_id = _habit(authed, name="Read 20 pages")
    plan = authed.get("/api/v2/plan").json()
    match = next(h for h in plan["habits"] if h["id"] == str(habit_id))
    assert match["name"] == "Read 20 pages"
    assert match["streak"] == 0
    assert match["doneToday"] is False
    assert len(match["weekTicks"]) == 7


def test_ticking_a_day_returns_the_recomputed_streak(authed: TestClient):
    habit_id = _habit(authed)
    response = authed.post(
        f"/api/v2/habits/{habit_id}/day",
        json={"day": date.today().isoformat(), "done": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["doneToday"] is True
    assert body["streak"] == 1


def test_unticking_clears_the_day(authed: TestClient):
    habit_id = _habit(authed)
    today = date.today().isoformat()
    authed.post(f"/api/v2/habits/{habit_id}/day", json={"day": today, "done": True})
    body = authed.post(
        f"/api/v2/habits/{habit_id}/day", json={"day": today, "done": False}
    ).json()
    assert body["doneToday"] is False
    assert body["streak"] == 0


def test_future_days_are_rejected_with_400(authed: TestClient):
    """A validation failure must not surface as a 500."""
    habit_id = _habit(authed)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = authed.post(
        f"/api/v2/habits/{habit_id}/day", json={"day": tomorrow, "done": True}
    )
    assert response.status_code == 400
    assert "future" in response.json()["error"].lower()


def test_unknown_habit_is_rejected(authed: TestClient):
    response = authed.post(
        "/api/v2/habits/999999/day", json={"day": date.today().isoformat(), "done": True}
    )
    assert response.status_code == 400


def test_bad_habit_input_is_rejected(authed: TestClient):
    assert authed.post("/api/v2/habits", json={"name": "  "}).status_code == 400
    assert authed.post(
        "/api/v2/habits", json={"name": "x", "cadence": "fortnightly"}
    ).status_code == 400


def test_archiving_removes_a_habit_from_the_plan(authed: TestClient):
    habit_id = _habit(authed, name="Temporary")
    assert authed.delete(f"/api/v2/habits/{habit_id}").status_code == 200
    plan = authed.get("/api/v2/plan").json()
    assert all(h["id"] != str(habit_id) for h in plan["habits"])


def test_week_ticks_do_not_mark_future_days_as_missed(authed: TestClient):
    """Days later this week have not happened, so they are neither done nor missed."""
    habit_id = _habit(authed)
    plan = authed.get("/api/v2/plan").json()
    match = next(h for h in plan["habits"] if h["id"] == str(habit_id))
    remaining = 6 - date.today().weekday()
    assert match["weekTicks"].count(None) == remaining


# -------------------------------------------------------------------- goals
def test_create_a_manual_goal_and_see_progress(authed: TestClient):
    response = authed.post(
        "/api/v2/goals",
        json={
            "title": "Bodyweight", "baselineValue": 100.0, "targetValue": 90.0,
            "manualValue": 95.0, "unit": "kg", "direction": "decrease",
        },
    )
    assert response.status_code == 200
    goal_id = response.json()["id"]

    plan = authed.get("/api/v2/plan").json()
    goal = next(g for g in plan["goals"] if g["id"] == str(goal_id))
    assert goal["progress"] == pytest.approx(0.5)
    assert goal["source"] == "manual"
    assert goal["current"] == "95 kg"


def test_patching_a_goal_updates_progress(authed: TestClient):
    goal_id = authed.post(
        "/api/v2/goals",
        json={"title": "Move", "baselineValue": 0.0, "targetValue": 10.0, "manualValue": 0.0},
    ).json()["id"]
    body = authed.patch(f"/api/v2/goals/{goal_id}", json={"manualValue": 5.0}).json()
    assert body["progress"] == pytest.approx(0.5)


def test_empty_patch_is_rejected(authed: TestClient):
    goal_id = authed.post("/api/v2/goals", json={"title": "Untouched"}).json()["id"]
    assert authed.patch(f"/api/v2/goals/{goal_id}", json={}).status_code == 400


def test_patch_cannot_reach_arbitrary_columns(authed: TestClient):
    """The patch model is a whitelist; unknown keys are ignored, not applied."""
    goal_id = authed.post("/api/v2/goals", json={"title": "Safe"}).json()["id"]
    response = authed.patch(f"/api/v2/goals/{goal_id}", json={"user_id": 999})
    assert response.status_code == 400  # nothing recognised to update


def test_unknown_metric_goal_is_rejected(authed: TestClient):
    response = authed.post("/api/v2/goals", json={"title": "Bad", "metricKind": "vibes"})
    assert response.status_code == 400
    assert "measure" in response.json()["error"].lower()


def test_goal_without_a_target_reports_no_progress(authed: TestClient):
    """An un-computable progress must be null, never a bar sitting at zero."""
    goal_id = authed.post(
        "/api/v2/goals", json={"title": "Open ended", "manualValue": 3.0}
    ).json()["id"]
    plan = authed.get("/api/v2/plan").json()
    goal = next(g for g in plan["goals"] if g["id"] == str(goal_id))
    assert goal["progress"] is None


def test_deleting_a_goal_removes_it(authed: TestClient):
    goal_id = authed.post("/api/v2/goals", json={"title": "Gone"}).json()["id"]
    assert authed.delete(f"/api/v2/goals/{goal_id}").status_code == 200
    plan = authed.get("/api/v2/plan").json()
    assert all(g["id"] != str(goal_id) for g in plan["goals"])


def test_plan_no_longer_reports_habits_as_unavailable(authed: TestClient):
    """The store exists now, so an empty list means "none yet", not "no feature"."""
    plan = authed.get("/api/v2/plan").json()
    assert plan["unavailable"] == {}
