"""Web access layer: auth gate, page rendering, and logging actions."""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domains import personal_os, strength
from app.db.database import session_scope
from app.db.models import ClientMutation, Task, WorkoutSessionLog
from app.services import get_default_user_id
from app.web.server import create_app

PAGES = ["/", "/training", "/run", "/recovery", "/tasks", "/money", "/mind", "/stoic", "/data"]


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post("/login", data={"passphrase": "orion"}, follow_redirects=False)
    assert response.status_code == 303
    return client


class _TagBalanceChecker(HTMLParser):
    VOID = {"meta", "link", "img", "br", "hr", "input", "circle", "line", "polyline", "path"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append(f"closing </{tag}> with nothing open")
        elif self.stack[-1] != tag:
            self.errors.append(f"expected </{self.stack[-1]}>, got </{tag}>")
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.stack.pop()


def test_html_is_well_formed(authed: TestClient):
    """Every rendered page must have balanced, properly nested tags."""
    targets = PAGES + ["/mind?phase=morning", "/mind?phase=evening", "/login"]
    for path in targets:
        checker = _TagBalanceChecker()
        checker.feed(authed.get(path).text)
        assert not checker.errors, f"{path}: {checker.errors[:3]}"
        leftovers = [t for t in checker.stack if t not in ("html", "body")]
        assert not leftovers, f"{path}: unclosed tags {leftovers}"


def test_delta_helper_precision():
    from app.web.server import _delta

    metric = personal_os.TodayMetric(
        "Resting HR", "66 bpm", "up", "", "real", [62, 63, 62, 61, 63, 62, 66]
    )
    out = _delta(metric)
    assert out is not None
    assert out["tone"] == "watch"  # rising resting HR is a watch signal
    assert "vs 7-day" in out["text"]

    sparse = personal_os.TodayMetric("HRV", "58 ms", "flat", "", "real", [58, 60])
    assert _delta(sparse) is None  # too little history: no trend claim


def test_security_headers(client: TestClient):
    response = client.get("/login")
    csp = response.headers["Content-Security-Policy"]
    # Inline style attributes must work (bar widths are inline) while
    # scripts stay locked to 'self'.
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self'" in csp and "script-src 'self' 'unsafe-inline'" not in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_pwa_assets_are_served_without_login(client: TestClient):
    login = client.get("/login")
    assert 'rel="manifest"' in login.text
    assert "/static/orion-icon.svg" in login.text

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/"

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert "orion-static-v6" in worker.text


def test_pages_require_login(client: TestClient):
    for path in PAGES:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login"


def test_queued_write_requires_login_without_losing_client_state(client: TestClient):
    response = client.post(
        "/training/log",
        data={"title": "Offline Draft", "client_mutation_id": "queued-login-needed"},
        headers={"X-Orion-Queue": "1"},
    )
    assert response.status_code == 401
    assert response.json()["status"] == "login_required"


def test_bad_passphrase_rejected(client: TestClient):
    response = client.post("/login", data={"passphrase": "wrong"})
    assert response.status_code == 200
    assert "not recognised" in response.text
    assert "orion_session" not in client.cookies


def test_all_pages_render(authed: TestClient):
    for path in PAGES:
        response = authed.get(path)
        assert response.status_code == 200, path
        assert "ORION" in response.text


def test_offline_queue_forms_are_marked(authed: TestClient):
    training = authed.get("/training").text
    assert 'action="/training/plan"' in training
    assert 'action="/training/plan/session"' in training
    assert 'href="/strength/start"' in training

    launcher = authed.get("/strength/start").text
    assert "Start strength" in launcher

    start = authed.post(
        "/strength/start",
        data={"template_id": str(strength.templates()[0]["id"])},
        follow_redirects=False,
    )
    assert start.status_code == 303
    workout = authed.get(start.headers["location"]).text
    assert 'data-offline-queue' in workout

    mind = authed.get("/mind?phase=morning").text
    assert 'action="/mind/morning"' in mind
    assert 'action="/mind/mindfulness"' in mind
    assert mind.count("data-offline-queue") >= 2

    stoic = authed.get("/stoic").text
    assert 'action="/stoic/entry"' in stoic
    assert 'data-offline-queue' in stoic


def test_queued_workout_replay_is_idempotent(authed: TestClient):
    uid = get_default_user_id()
    response = authed.post(
        "/training/log",
        data={
            "title": "Offline Bench",
            "category": "push",
            "exercises_text": "Bench press 3x5 60kg",
            "duration_minutes": "35",
            "rpe": "8",
            "completed": "1",
            "client_mutation_id": "offline-workout-1",
        },
        headers={"X-Orion-Queue": "1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    first_id = response.json()["record_id"]

    replay = authed.post(
        "/training/log",
        data={
            "title": "Offline Bench",
            "category": "push",
            "exercises_text": "Bench press 3x5 60kg",
            "duration_minutes": "35",
            "rpe": "8",
            "completed": "1",
            "client_mutation_id": "offline-workout-1",
        },
        headers={"X-Orion-Queue": "1"},
    )
    assert replay.status_code == 200
    assert replay.json()["record_id"] == first_id

    with session_scope() as s:
        matching_workouts = s.scalar(
            select(func.count())
            .select_from(WorkoutSessionLog)
            .where(
                WorkoutSessionLog.user_id == uid,
                WorkoutSessionLog.title == "Offline Bench",
            )
        )
        matching_receipts = s.scalar(
            select(func.count())
            .select_from(ClientMutation)
            .where(
                ClientMutation.user_id == uid,
                ClientMutation.mutation_id == "offline-workout-1",
            )
        )
    assert matching_workouts == 1
    assert matching_receipts == 1


def test_api_today_snapshot(authed: TestClient):
    payload = authed.get("/api/today").json()
    assert {"status", "metrics", "plan", "insights"} <= set(payload)
    assert len(payload["plan"]) == 5


def test_log_workout_roundtrip(authed: TestClient):
    response = authed.post(
        "/training/log",
        data={
            "title": "Web Push A",
            "category": "push",
            "exercises_text": "Bench press 2x5 60kg RPE 8",
            "duration_minutes": "40",
            "rpe": "8",
            "completed": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = authed.get("/training").text
    assert "Web Push A" in page
    assert "Bench press" in page


def test_training_plan_session_entry_roundtrip(authed: TestClient):
    response = authed.post(
        "/training/plan/session",
        data={
            "day": date.today().isoformat(),
            "session_type": "LONG RUN",
            "label": "Sunday long run",
            "notes": "Keep the first half easy",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/training#training-plan"

    page = authed.get("/training").text
    assert "Sunday long run" in page
    assert "Keep the first half easy" in page


def test_tasks_web_roundtrip_queues_sync(authed: TestClient):
    uid = get_default_user_id()
    response = authed.post(
        "/tasks",
        data={
            "title": "Web task bridge",
            "area": "Coding Projects",
            "priority": "high",
            "notes": "Should push to the tasks app on sync",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = authed.get("/tasks").text
    assert "Web task bridge" in page
    assert "Coding Projects" in page
    assert "Should push to the tasks app on sync" in page

    with session_scope() as s:
        task = s.scalars(
            select(Task).where(Task.user_id == uid, Task.title == "Web task bridge")
        ).one()
        assert task.dirty == 1
        task_id = task.id

    response = authed.post(
        f"/tasks/{task_id}/complete",
        data={"done": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with session_scope() as s:
        task = s.get(Task, task_id)
        assert task.status == "done"
        assert task.dirty == 1


def test_mind_bookends_do_not_clobber_each_other(authed: TestClient):
    uid = get_default_user_id()
    response = authed.post(
        "/mind/morning",
        data={
            "mood": 6, "energy": 7, "anxiety": 4, "sleep_quality": 6,
            "intention": "Finish the run plan", "factors": ["sleep", "work"],
            "triggers": "deadline",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    snap = personal_os.get_mind_snapshot(uid)
    assert snap.today is not None and snap.today["mood"] == 6
    assert snap.today["intention"] == "Finish the run plan"
    assert snap.today["factors"] == ["sleep", "work"]
    assert snap.checkin_streak >= 1

    response = authed.post(
        "/mind/evening",
        data={
            "stress": 4, "day_rating": 7, "intention_done": "1",
            "evening_note": "This will be a disaster, everyone thinks I failed.",
            "situation": "Missed a deadline", "thought": "I always ruin things",
            "balanced": "One deadline slipped; most didn't.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    snap = personal_os.get_mind_snapshot(uid)
    # Evening save must not clobber the morning fields.
    assert snap.today["mood"] == 6
    assert snap.today["intention"] == "Finish the run plan"
    assert snap.today["day_rating"] == 7
    assert snap.today["intention_done"] is True
    assert snap.today["thought_record"]["balanced"].startswith("One deadline")
    assert snap.reflection_streak >= 1


def test_evening_page_shows_cbt_pattern_readout(authed: TestClient):
    authed.post(
        "/mind/evening",
        data={
            "stress": 5, "day_rating": 5,
            "evening_note": "Today was a complete disaster and everyone thinks I am a failure.",
        },
        follow_redirects=False,
    )
    page = authed.get("/mind?phase=evening").text
    assert "Pattern readout" in page
    assert "Catastrophising" in page or "All-or-nothing" in page
    assert "Regulation" in page
    assert "not a diagnosis" in page


def test_morning_page_renders_protocol_and_chips(authed: TestClient):
    page = authed.get("/mind?phase=morning").text
    assert "Morning brief" in page
    assert "intention" in page.lower()
    assert 'name="factors"' in page


def test_checkin_scales_and_confirmation(authed: TestClient):
    page = authed.get("/mind?phase=morning").text
    # Tappable radio scales, not sliders.
    assert 'type="range"' not in page
    assert page.count('type="radio"') >= 40  # 4 fields x 10 steps
    # Saving redirects to a confirmed state that renders a toast.
    response = authed.post(
        "/mind/morning",
        data={"mood": 7, "energy": 6, "anxiety": 3, "sleep_quality": 6},
        follow_redirects=False,
    )
    assert "saved=morning" in response.headers["location"]
    confirmed = authed.get(response.headers["location"]).text
    assert "Morning brief logged." in confirmed


def test_stoic_screen_and_practice_log(authed: TestClient):
    page = authed.get("/stoic").text
    for word in ["Memento mori", "Wisdom", "Justice", "Courage", "Temperance", "sophia"]:
        assert word in page
    assert 'class="motif"' in page  # the classical line-art is present
    response = authed.post(
        "/stoic/entry",
        data={
            "virtue_focus": "justice", "control_pct": 70, "reflected": "1",
            "served_others": "1", "study_minutes": 20,
            "reflection": "Helped a friend move house.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    confirmed = authed.get(response.headers["location"]).text
    assert "Practice logged." in confirmed
    assert "Helped a friend move house." in confirmed


def test_mindfulness_logging(authed: TestClient):
    uid = get_default_user_id()
    personal_os.clear_today_mindfulness(uid)
    response = authed.post(
        "/mind/mindfulness",
        data={"duration_minutes": 5, "kind": "breathwork"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    snap = personal_os.get_mind_snapshot(uid)
    assert snap.mindfulness_streak >= 1


def test_sleep_debt_and_strain_surface(authed: TestClient):
    # The seeded dataset has sleep history, so the debt readout must exist
    # (either calibrating or resolved) and Today must carry the label.
    from app.domains.health import derived

    uid = get_default_user_id()
    debt = derived.get_sleep_debt(uid)
    assert debt.label
    snap = personal_os.get_today_snapshot(uid)
    assert snap.sleep_debt_label == debt.label
    recovery_page = authed.get("/recovery").text
    assert "Sleep debt" in recovery_page
