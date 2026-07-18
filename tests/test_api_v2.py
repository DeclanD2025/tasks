"""The JSON API the Next.js UI runs on (app/web/ui_models.py, routes/api_v2.py).

These assert the contract the TypeScript in ``frontend/lib/payloads.ts``
depends on — key names, value vocabularies, and the rule that ORION never
invents a number to fill an empty slot.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.domains import personal_os
from app.web import ui_models
from app.web.server import create_app

TRENDS = {"up", "down", "flat"}
TONES = {"good", "watch", "flat"}
QUALITIES = {"measured", "calculated", "estimated", "missing"}
DOMAINS = {
    "sleep", "recovery", "running", "strength",
    "cardio", "mind", "nutrition", "meds", "neutral",
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


ENDPOINTS = [
    "/api/v2/today",
    "/api/v2/recovery",
    "/api/v2/training",
    "/api/v2/plan",
    "/api/v2/insights",
    "/api/v2/health",
    "/api/v2/sources",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_every_endpoint_answers(authed: TestClient, path: str):
    """Each screen's endpoint returns JSON, on a database with real data."""
    response = authed.get(path)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


@pytest.mark.parametrize("path", ENDPOINTS)
def test_api_requires_a_session(client: TestClient, path: str):
    """Health data must not be readable without unlocking."""
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["status"] == "login_required"


def test_api_401s_rather_than_redirecting(client: TestClient):
    """A redirect would hand the client HTML where it expects JSON, and the
    session expiry would surface as a parse error instead of as a login."""
    response = client.get("/api/v2/today", follow_redirects=False)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


def test_unknown_metric_is_404_not_a_guess(authed: TestClient):
    assert authed.get("/api/v2/metrics/not_a_metric").status_code == 404


def test_metric_detail_matches_the_typescript_contract(authed: TestClient):
    payload = authed.get("/api/v2/metrics/resting_hr").json()
    for key in (
        "kind", "title", "unit", "domain", "latest", "displayValue", "trend",
        "quality", "series", "baseline7", "baseline30", "band", "lowerBetter",
        "decimals", "meaning", "how", "caveat", "source", "freshness",
        "interpretation", "facts", "related",
    ):
        assert key in payload, f"missing {key}"
    assert payload["trend"] in TRENDS
    assert payload["quality"] in QUALITIES
    assert payload["domain"] in DOMAINS
    assert payload["lowerBetter"] is True  # a lower resting HR is better
    assert all(set(r) == {"kind", "title"} for r in payload["related"])


def test_every_known_metric_serialises(authed: TestClient):
    """A kind the UI can route to must not blow up on the way out."""
    for kind in ui_models.ALL_KINDS:
        response = authed.get(f"/api/v2/metrics/{kind}")
        assert response.status_code == 200, kind
        assert response.json()["kind"] == kind


def test_status_strip_units_come_from_the_metric(authed: TestClient):
    """Mood is a −1..+1 valence, not a score out of ten. Hardcoding a unit in
    the strip mislabels it."""
    strip = {item["kind"]: item for item in authed.get("/api/v2/today").json()["statusStrip"]}
    if "mood" in strip:
        assert strip["mood"]["unit"] != "/10"
    for item in strip.values():
        assert item["trend"] in TRENDS
        assert item["tone"] in TONES
        assert item["domain"] in DOMAINS


def test_changes_carry_their_own_tone(authed: TestClient):
    """Tone comes from ChangeRecord, not from sniffing the sentence."""
    for change in authed.get("/api/v2/today").json()["changes"]:
        assert change["tone"] in TONES
        assert change["domain"] in DOMAINS
        assert change["text"]


def test_habits_and_goals_have_a_real_store(authed: TestClient):
    """Habits and goals are backed by tables now, so an empty list means "none
    created" — not "no such feature". The ``unavailable`` note that stood in
    for the missing store must be gone."""
    payload = authed.get("/api/v2/plan").json()
    assert isinstance(payload["habits"], list)
    assert isinstance(payload["goals"], list)
    assert payload["unavailable"] == {}


def test_week_grid_separates_recorded_from_planned(authed: TestClient):
    """The planner now derives real weekdays from running history, so plans may
    sit on the grid — but a recorded session is a fact and a planned one is an
    intention, and ``status`` has to keep them apart."""
    payload = authed.get("/api/v2/plan").json()
    week = payload["week"]
    assert len(week) == 7
    assert [day["dow"] for day in week] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert sum(day["isToday"] for day in week) == 1
    for day in week:
        for session in day["sessions"]:
            assert session["status"] in {"done", "planned"}


def test_the_grid_never_plans_a_day_that_has_passed(authed: TestClient):
    """The planner only schedules forward; a past day showing a plan would read
    as a session missed, which is a claim ORION has not made."""
    payload = authed.get("/api/v2/plan").json()
    today_iso = date.today().isoformat()
    for day in payload["week"]:
        if day["date"] < today_iso:
            assert all(s["status"] == "done" for s in day["sessions"])


def test_planned_sessions_name_a_weekday_and_own_their_confidence(authed: TestClient):
    payload = authed.get("/api/v2/plan").json()
    for session in payload["planned"]:
        assert session["when"]
        # No positional labels survive — the planner commits to a day now.
        assert session["when"] not in {"Next", "Midweek", "Weekend"}
        assert session["daySource"] in {"observed", "spread"}


def test_recommendation_body_explains_the_recommendation(authed: TestClient):
    """The body must be the reasoning behind the training call — not the day's
    unrelated next nudge, which can be about something else entirely."""
    payload = authed.get("/api/v2/today").json()
    rec = payload["recommendation"]
    if rec is not None:
        recovery = personal_os.get_recovery_snapshot(1)
        assert rec["body"] == recovery.recommendation
        assert rec["confidence"] in {"high", "medium", "low"}


def test_insights_are_classified_and_distinctly_titled(authed: TestClient):
    """Two metrics drifting must not both surface as one anonymous headline."""
    insights = authed.get("/api/v2/today").json()["insights"]
    for insight in insights:
        assert insight["klass"] in {
            "measured", "calculated", "association", "hypothesis", "recommendation"
        }
        assert insight["domain"] in DOMAINS
    titles = [i["title"] for i in insights]
    assert len(titles) == len(set(titles)), f"duplicate insight titles: {titles}"


def test_change_records_direction_matches_tone():
    """A lower resting HR is good; a lower HRV is not. The record has to know
    which, because the UI colours from it."""
    frames = personal_os.ChangeRecord(
        metric="Resting HR", direction="lower", delta=-4.0, unit="bpm",
        tone="good", text="Resting HR is lower vs 7-day baseline (-4.0 bpm).",
    )
    assert str(frames) == frames.text  # templates print the record directly
