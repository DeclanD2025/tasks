"""The homepage brief API (app/web/routes/api_v2_brief.py).

Contract tests for the one composed endpoint the homepage runs on, plus the
write paths that record what the operator did about each suggestion.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import init_db, session_scope
from app.db.models import BriefEvent, DailyBrief, Task
from app.web.server import create_app


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


@pytest.fixture()
def a_task():
    """A real task so priorities are non-empty regardless of seed contents."""
    with session_scope() as s:
        task = Task(
            user_id=1, title="Write the editorial", area="Steelmen Dispatch / Features",
            status="open", due_date=date.today(), next_action="Open the draft",
        )
        s.add(task)
        s.flush()
        task_id = task.id
    yield task_id
    with session_scope() as s:
        for row in s.scalars(select(BriefEvent)).all():
            s.delete(row)
        s.flush()
        for row in s.scalars(select(DailyBrief)).all():
            s.delete(row)
        s.flush()
        row = s.get(Task, task_id)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/api/v2/brief", "/api/v2/brief/history"])
def test_reads_require_a_session(client: TestClient, path: str):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/brief/priorities/1/defer",
        "/api/v2/brief/priorities/1/pin",
        "/api/v2/brief/priorities/1/complete",
        "/api/v2/brief/events",
        "/api/v2/brief/edit",
    ],
)
def test_writes_require_a_session(client: TestClient, path: str):
    response = client.post(path, json={}, follow_redirects=False)
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #
def test_the_brief_is_one_composed_response(authed: TestClient, a_task):
    """The homepage should not fetch six things and reconcile them itself —
    that reconciliation is the judgement that belongs in the backend."""
    payload = authed.get("/api/v2/brief").json()
    for key in (
        "day", "daypart", "stateSummary", "focus", "nextAction", "priorities",
        "insight", "review", "timeline", "dataQuality", "sources",
        "confidence", "ruleVersion", "sourceDataAt",
    ):
        assert key in payload, f"missing {key}"


def test_never_more_than_three_priorities(authed: TestClient, a_task):
    payload = authed.get("/api/v2/brief").json()
    assert len(payload["priorities"]) <= 3


def test_each_priority_can_explain_itself(authed: TestClient, a_task):
    """"View evidence" must open real evidence, not generic copy."""
    payload = authed.get("/api/v2/brief").json()
    for priority in payload["priorities"]:
        assert priority["why"]
        assert priority["components"]
        assert priority["selectedBy"] in {"you", "orion"}
        for component in priority["components"]:
            assert component["label"] and component["detail"]


def test_data_quality_travels_with_the_brief(authed: TestClient, a_task):
    """A page that shows a number without its provenance is asserting more than
    it knows."""
    payload = authed.get("/api/v2/brief").json()
    assert set(payload["sources"]) == {"health", "tasks", "calendar", "training"}
    for source in payload["sources"].values():
        assert source["trust"] in {"live", "stale", "empty"}


def test_the_review_section_reframes_rather_than_counting(authed: TestClient, a_task):
    payload = authed.get("/api/v2/brief").json()
    assert payload["review"]["headline"]
    assert isinstance(payload["review"]["buckets"], list)


def test_the_brief_is_stable_between_loads(authed: TestClient, a_task):
    """The next action changing under the operator mid-glance would make the
    page untrustworthy."""
    first = authed.get("/api/v2/brief").json()
    second = authed.get("/api/v2/brief").json()
    assert first["stateSummary"] == second["stateSummary"]
    assert first["nextAction"] == second["nextAction"]


# --------------------------------------------------------------------------- #
# Interaction
# --------------------------------------------------------------------------- #
def test_completing_a_priority_updates_the_brief(authed: TestClient, a_task):
    authed.get("/api/v2/brief")
    response = authed.post(f"/api/v2/brief/priorities/{a_task}/complete")
    assert response.status_code == 200
    assert a_task not in [p["taskId"] for p in response.json()["priorities"]]

    with session_scope() as s:
        assert s.get(Task, a_task).status == "done"


def test_deferring_records_that_it_was_deferred(authed: TestClient, a_task):
    """The counter is what stops the same task being offered every morning
    forever, and makes the pattern visible at review."""
    authed.get("/api/v2/brief")
    authed.post(f"/api/v2/brief/priorities/{a_task}/defer", json={})
    with session_scope() as s:
        task = s.get(Task, a_task)
        assert task.deferral_count == 1
        assert task.defer_until > date.today()


def test_pinning_survives_into_the_next_brief(authed: TestClient, a_task):
    authed.post(f"/api/v2/brief/priorities/{a_task}/pin")
    payload = authed.get("/api/v2/brief?refresh=true").json()
    pinned = [p for p in payload["priorities"] if p["taskId"] == a_task]
    assert pinned and pinned[0]["selectedBy"] == "you"


def test_an_unknown_task_is_rejected(authed: TestClient):
    assert authed.post("/api/v2/brief/priorities/999999/complete").status_code == 400


def test_interactions_are_logged_for_later_analysis(authed: TestClient, a_task):
    authed.post("/api/v2/brief/events", json={"kind": "evidence_opened", "taskId": a_task})
    with session_scope() as s:
        kinds = {e.kind for e in s.scalars(select(BriefEvent)).all()}
    assert "evidence_opened" in kinds


def test_editing_the_brief_overrides_the_generated_text(authed: TestClient, a_task):
    authed.get("/api/v2/brief")
    response = authed.post("/api/v2/brief/edit", json={"focus": "Rest tonight."})
    assert response.status_code == 200
    assert response.json()["focus"] == "Rest tonight."


def test_history_reports_counts_for_later_analysis(authed: TestClient, a_task):
    authed.get("/api/v2/brief")
    payload = authed.get("/api/v2/brief/history").json()
    assert "prioritiesGenerated" in payload
    assert "events" in payload
