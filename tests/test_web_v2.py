"""V2 web surfaces: new tabs, drilldown API, imports/exports, ingest, settings."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.services import get_default_user_id
from app.web.server import create_app

NEW_PAGES = ["/health", "/nutrition", "/nutrition/scan", "/routes", "/calendar", "/settings"]

GPX_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Test Loop</name><trkseg>
    <trkpt lat="55.8070" lon="-4.0170"><ele>70</ele></trkpt>
    <trkpt lat="55.8080" lon="-4.0160"><ele>74</ele></trkpt>
    <trkpt lat="55.8090" lon="-4.0175"><ele>72</ele></trkpt>
  </trkseg></trk>
</gpx>"""


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def test_new_pages_render(authed: TestClient):
    for path in NEW_PAGES:
        response = authed.get(path)
        assert response.status_code == 200, path
        assert "ORION" in response.text, path


def test_new_pages_require_login(client: TestClient):
    for path in NEW_PAGES:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path


def test_detail_api_shape_and_unknown_kind(authed: TestClient):
    detail = authed.get("/api/detail/sleep?days=30").json()
    for key in ("title", "unit", "series", "meaning", "how", "source", "related"):
        assert key in detail
    assert detail["title"] == "Sleep"
    assert authed.get("/api/detail/not_a_metric").status_code == 404


def test_detail_api_readiness_exposes_formula(authed: TestClient):
    detail = authed.get("/api/detail/readiness").json()
    assert detail["facts"], "readiness must list its factor inputs"
    assert "blend" in detail["how"].lower() or "weighted" in detail["how"].lower()


def test_settings_roundtrip_feeds_nutrition_targets(authed: TestClient):
    response = authed.post(
        "/settings", data={"protein_target_g": "150"}, follow_redirects=False
    )
    assert response.status_code == 303
    page = authed.get("/nutrition").text
    assert "/ 150" in page  # protein bar shows the new target
    # blank resets to default
    authed.post("/settings", data={"protein_target_g": ""}, follow_redirects=False)
    assert "/ 120" in authed.get("/nutrition").text


def test_nutrition_quick_add_and_water_roundtrip(authed: TestClient):
    response = authed.post(
        "/nutrition/quick",
        data={"meal_type": "lunch", "calories": "430", "protein": "32", "name": "Test bowl"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    authed.post("/nutrition/water", data={"ml": "500"}, follow_redirects=False)
    page = authed.get("/nutrition").text
    assert "Test bowl" in page
    assert "430" in page


def test_calendar_manual_event_add_and_delete(authed: TestClient):
    response = authed.post(
        "/calendar/event",
        data={"title": "Test dentist", "day": "", "start_time": "10:00", "end_time": "11:00"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = authed.get("/calendar").text
    assert "Test dentist" in page

    from sqlalchemy import select

    from app.db.database import session_scope
    from app.db.models import CalendarEvent

    with session_scope() as s:
        event = s.scalars(
            select(CalendarEvent).where(CalendarEvent.title == "Test dentist")
        ).first()
        event_id = event.id
        assert event.ext_id.startswith("orion-manual-")
    authed.post(f"/calendar/event/{event_id}/delete", follow_redirects=False)
    assert "Test dentist" not in authed.get("/calendar").text


def test_gpx_import_route_detail_and_export(authed: TestClient):
    response = authed.post(
        "/routes/import-gpx",
        files={"file": ("loop.gpx", GPX_SAMPLE, "application/gpx+xml")},
        data={"name": "Test Loop"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    route_path = response.headers["location"]
    assert route_path.startswith("/routes/")
    page = authed.get(route_path).text
    assert "Test Loop" in page

    route_id = route_path.rsplit("/", 1)[-1]
    geometry = authed.get(f"/api/routes/{route_id}/geometry.json").json()
    assert len(geometry["points"]) == 3
    gpx_export = authed.get(f"/data/export/routes/{route_id}.gpx")
    assert gpx_export.status_code == 200
    assert "<trkpt" in gpx_export.text


def test_data_exports(authed: TestClient):
    bundle = authed.get("/data/export.json")
    assert bundle.status_code == 200
    payload = bundle.json()
    assert payload["format"] == "orion-v1"
    assert "health_metrics_daily" in payload

    csv_response = authed.get("/data/export/tasks.csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert authed.get("/data/export/not_a_table.csv").status_code == 404


def test_hae_ingest_token_gate(client: TestClient):
    os.environ.pop("ORION_INGEST_TOKEN", None)
    response = client.post("/api/ingest/hae", json={"data": {"metrics": []}})
    assert response.status_code == 403  # disabled without a token

    os.environ["ORION_INGEST_TOKEN"] = "test-token-123"
    try:
        response = client.post("/api/ingest/hae", json={"data": {"metrics": []}})
        assert response.status_code == 401  # no/wrong credential

        response = client.post(
            "/api/ingest/hae",
            json={"data": {"metrics": [
                {"name": "resting_heart_rate", "units": "bpm",
                 "data": [{"date": "2026-07-01 08:00:00 +0100", "qty": 58}]},
            ], "workouts": []}},
            headers={"Authorization": "Bearer test-token-123"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["days"] == 1
    finally:
        os.environ.pop("ORION_INGEST_TOKEN", None)


def test_signals_fail_gracefully_offline(authed: TestClient):
    weather = authed.get("/api/signals/weather").json()
    assert weather["ok"] is False or weather.get("stale")  # offline guard active
    # Pages that surface signals still render.
    assert authed.get("/calendar").status_code == 200
    assert authed.get("/money").status_code == 200


def test_html_well_formed_new_pages(authed: TestClient):
    from tests.test_web_app import _TagBalanceChecker

    for path in NEW_PAGES + ["/routes"]:
        checker = _TagBalanceChecker()
        checker.feed(authed.get(path).text)
        assert not checker.errors, f"{path}: {checker.errors[:3]}"


def test_default_user_exists():
    assert get_default_user_id() is not None
