from __future__ import annotations

from datetime import date, timedelta

from app.domains.fitness import fitness_service as fs
from app.services import get_default_user_id


def test_plan_autocreates_with_week_label():
    uid = get_default_user_id()
    plan = fs.get_or_create_plan(uid)
    assert plan.block_name
    assert plan.weeks >= 1
    # week label is one of the expected forms
    assert plan.week_label.startswith(("WEEK", "STARTS"))


def test_plan_week_counter():
    uid = get_default_user_id()
    plan = fs.get_or_create_plan(uid)
    fs.update_plan(plan.id, start_date=date.today() - timedelta(days=14), weeks=6)
    plan = fs.get_or_create_plan(uid)
    assert plan.current_week == 3
    assert plan.week_label == "WEEK 3 OF 6"


def test_session_add_move_delete():
    uid = get_default_user_id()
    today = date.today()
    tomorrow = today + timedelta(days=1)
    sid = fs.add_session(uid, today, "ZONE 2 CARDIO")
    month = fs.sessions_for_month(uid, today.year, today.month)
    assert any(s.id == sid for s in month.get(today, []))
    assert month[today][0].color == fs.SESSION_COLOR["ZONE 2 CARDIO"]

    fs.move_session(sid, tomorrow)
    month = fs.sessions_for_month(uid, today.year, today.month)
    if today.month == tomorrow.month:
        assert any(s.id == sid for s in month.get(tomorrow, []))
        assert all(s.id != sid for s in month.get(today, []))

    fs.delete_session(sid)
    month = fs.sessions_for_month(uid, tomorrow.year, tomorrow.month)
    assert all(s.id != sid for s in month.get(tomorrow, []))


def test_fitness_frame_reads_apple_health_metrics():
    uid = get_default_user_id()
    fr = fs.fitness_frame(uid)
    assert {"day", "distance_km", "vo2max", "resting_hr"}.issubset(fr.columns)
    # seeded mock includes distance + vo2max
    assert fr["vo2max"].notna().any()
