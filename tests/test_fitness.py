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


def test_session_metadata_swap_and_completion():
    uid = get_default_user_id()
    day = date.today() + timedelta(days=8)
    sid = fs.add_session(uid, day, "ZONE 2 CARDIO")

    fs.update_session(sid, notes="Keep nasal breathing", completed=True)
    item = fs.get_session(sid)
    assert item is not None
    assert item.notes == "Keep nasal breathing"
    assert item.completed is True
    assert item.title == "Zone 2 Cardio"
    assert item.duration_label == "45 min"
    assert item.recovery_label == "R2"

    new_type = fs.swap_session(sid)
    item = fs.get_session(sid)
    assert new_type == "UPPER STRENGTH"
    assert item is not None
    assert item.session_type == "UPPER STRENGTH"
    assert item.color == fs.SESSION_COLOR["UPPER STRENGTH"]

    fs.mark_complete(sid, False)
    item = fs.get_session(sid)
    assert item is not None
    assert item.completed is False

    fs.delete_session(sid)


def test_custom_card_create_edit_delete_and_drop():
    uid = get_default_user_id()
    day = date.today() + timedelta(days=10)

    key = fs.create_custom_card(
        uid, title="Tempo Run", color="#ff9d3d", intensity="MOD+",
        duration_min=40, recovery_cost=3, goal="threshold",
    )
    assert key.startswith("CUSTOM-")
    assert any(c.key == key for c in fs.custom_cards(uid))
    # palette = built-in library plus the new custom card
    assert len(fs.palette_cards(uid)) == len(fs.SESSION_LIBRARY) + len(fs.custom_cards(uid))

    # dropping the custom card resolves its full definition
    sid = fs.add_session(uid, day, key)
    item = fs.get_session(sid)
    assert item is not None
    assert item.color == "#ff9d3d"
    assert item.definition.intensity == "MOD+"
    assert item.definition.duration_min == 40
    assert item.title == "Tempo Run"

    # editing the card recolours placed sessions and updates the resolved title
    fs.update_custom_card(uid, key, color="#3ad6a0", title="Tempo X")
    item = fs.get_session(sid)
    assert item.color == "#3ad6a0"
    assert item.definition.title == "Tempo X"

    # deleting the card keeps the placed session and stamps a readable label
    fs.delete_custom_card(uid, key)
    assert all(c.key != key for c in fs.custom_cards(uid))
    item = fs.get_session(sid)
    assert item is not None
    assert item.title == "Tempo X"  # inherited from the deleted card

    fs.delete_session(sid)


def test_session_rename_label_overrides_title():
    uid = get_default_user_id()
    day = date.today() + timedelta(days=11)
    sid = fs.add_session(uid, day, "ZONE 2 CARDIO")

    fs.update_session(sid, label="Easy Recovery Spin")
    item = fs.get_session(sid)
    assert item is not None
    assert item.label == "Easy Recovery Spin"
    assert item.title == "Easy Recovery Spin"

    # clearing the label falls back to the definition title
    fs.update_session(sid, label="")
    assert fs.get_session(sid).title == "Zone 2 Cardio"

    fs.delete_session(sid)


def test_session_definitions_carry_categories():
    cats = {d.key: d.category for d in fs.SESSION_LIBRARY}
    assert cats["UPPER STRENGTH"] == fs.CATEGORY_STRENGTH
    assert cats["LOWER STRENGTH"] == fs.CATEGORY_STRENGTH
    assert cats["ZONE 2 CARDIO"] == fs.CATEGORY_CARDIO
    assert cats["LONG RUN"] == fs.CATEGORY_CARDIO
    assert cats["MOBILITY"] == fs.CATEGORY_MOBILITY
    assert cats["REST"] == fs.CATEGORY_RECOVERY


def test_training_breakdown_splits_strength_and_cardio():
    uid = get_default_user_id()
    base = date.today() + timedelta(days=20)
    # 2 strength sessions, 1 cardio
    fs.add_session(uid, base, "UPPER STRENGTH")       # 55 min strength
    fs.add_session(uid, base + timedelta(days=1), "LOWER STRENGTH")  # 60 min strength
    fs.add_session(uid, base + timedelta(days=2), "ZONE 2 CARDIO")   # 45 min cardio

    bd = fs.training_breakdown(uid, base, base + timedelta(days=6))
    assert bd.total_sessions == 3
    strength_share, cardio_share = bd.strength_cardio_ratio
    # strength minutes = 115, cardio = 45 -> strength is the majority
    assert strength_share > cardio_share
    assert round(strength_share + cardio_share, 5) == 1.0
    stats = {s.category: s for s in bd.stats}
    assert stats[fs.CATEGORY_STRENGTH].sessions == 2
    assert stats[fs.CATEGORY_STRENGTH].minutes == 115
    assert stats[fs.CATEGORY_CARDIO].sessions == 1


def test_custom_card_category_feeds_breakdown():
    uid = get_default_user_id()
    day = date.today() + timedelta(days=40)
    key = fs.create_custom_card(
        uid, title="Heavy Squat", category=fs.CATEGORY_STRENGTH,
        duration_min=70, recovery_cost=4,
    )
    sid = fs.add_session(uid, day, key)
    assert fs.get_session(sid).category == fs.CATEGORY_STRENGTH
    bd = fs.training_breakdown(uid, day, day)
    stats = {s.category: s for s in bd.stats}
    assert stats[fs.CATEGORY_STRENGTH].minutes == 70
    fs.delete_session(sid)
    fs.delete_custom_card(uid, key)


def test_plan_create_switch_and_update_purpose_focus():
    uid = get_default_user_id()
    existing = fs.list_plans(uid)
    pid = fs.create_plan(
        uid, block_name="Strength Block", purpose="Get stronger",
        focus="strength", goal="+10kg squat", weeks=8,
    )
    plans = fs.list_plans(uid)
    assert len(plans) == len(existing) + 1
    # the new plan is active
    active = fs.get_or_create_plan(uid)
    assert active.id == pid
    assert active.focus == "strength"
    assert active.focus_label == "Strength"
    assert active.purpose == "Get stronger"
    assert active.weeks == 8
    assert active.end_date == active.start_date + timedelta(weeks=8) - timedelta(days=1)

    # update purpose/focus/goal
    fs.update_plan(pid, purpose="Peak strength", focus="hybrid", goal="3 plate DL")
    active = fs.get_or_create_plan(uid)
    assert active.purpose == "Peak strength"
    assert active.focus == "hybrid"
    assert active.goal == "3 plate DL"

    # switch back to the original, then delete the new one
    if existing:
        fs.activate_plan(uid, existing[0].id)
        assert fs.get_or_create_plan(uid).id == existing[0].id
    fs.delete_plan(uid, pid)
    assert all(p.id != pid for p in fs.list_plans(uid))


def test_fitness_frame_reads_apple_health_metrics():
    uid = get_default_user_id()
    fr = fs.fitness_frame(uid)
    assert {"day", "distance_km", "vo2max", "resting_hr", "weight_kg"}.issubset(fr.columns)
    # seeded mock includes distance + vo2max
    assert fr["vo2max"].notna().any()
    assert fr["resting_hr"].notna().any()
    assert fr["weight_kg"].notna().any()


def test_body_state_snapshot_reads_rhr_and_weight():
    uid = get_default_user_id()
    snap = fs.body_state_snapshot(uid)

    assert snap.has_data
    assert snap.readiness_label in {"SYNC NEEDED", "RECOVERY WATCH", "PRIMED", "STEADY"}
    assert snap.resting_hr.value is not None
    assert snap.resting_hr.unit == "bpm"
    assert snap.weight.value is not None
    assert snap.weight.unit == "kg"
