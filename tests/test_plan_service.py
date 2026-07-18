"""Habits and goals: streaks, completion rates and goal progress.

The streak rules are the subtle part, so they are pinned explicitly: an
unfinished *today* must not break a run, but a missed yesterday must.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domains import plan_service


UID = 1


def _tick(habit_id: int, *offsets: int) -> None:
    """Mark a habit done N days ago, for each offset given."""
    today = date.today()
    for offset in offsets:
        plan_service.set_habit_day(UID, habit_id, today - timedelta(days=offset), True)


def _fresh_habit(**kwargs) -> int:
    kwargs.setdefault("name", "Test habit")
    return plan_service.create_habit(UID, kwargs.pop("name"), **kwargs)


def _view(habit_id: int) -> plan_service.HabitView:
    return next(h for h in plan_service.list_habits(UID) if h.id == habit_id)


# --------------------------------------------------------------------------- #
# Habits
# --------------------------------------------------------------------------- #
def test_create_and_tick_a_habit():
    hid = _fresh_habit(name="Read", domain="mind")
    view = _view(hid)
    assert view.streak == 0 and not view.done_today

    view = plan_service.set_habit_day(UID, hid, date.today(), True)
    assert view.done_today
    assert view.streak == 1


def test_daily_streak_counts_back_from_today():
    hid = _fresh_habit(name="Streak daily")
    _tick(hid, 0, 1, 2, 3)
    assert _view(hid).streak == 4


def test_unfinished_today_does_not_break_the_streak():
    """Today is still in progress, so the run counts from yesterday."""
    hid = _fresh_habit(name="Not yet today")
    _tick(hid, 1, 2, 3)
    view = _view(hid)
    assert not view.done_today
    assert view.streak == 3


def test_missed_yesterday_breaks_the_streak():
    hid = _fresh_habit(name="Broken")
    _tick(hid, 0, 2, 3, 4)  # gap at yesterday
    assert _view(hid).streak == 1


def test_unticking_a_day_recomputes_the_streak():
    hid = _fresh_habit(name="Untick")
    _tick(hid, 0, 1, 2)
    assert _view(hid).streak == 3
    view = plan_service.set_habit_day(UID, hid, date.today() - timedelta(days=1), False)
    assert view.streak == 1  # today survives, the run behind it does not


def test_weekly_streak_requires_meeting_the_target():
    hid = _fresh_habit(name="Gym", cadence="weekly", target_per_period=3)
    today = date.today()
    # Fill last week and the week before with 3 sessions each.
    monday = today - timedelta(days=today.weekday())
    for weeks_back in (1, 2):
        start = monday - timedelta(days=7 * weeks_back)
        for day_offset in (0, 2, 4):
            plan_service.set_habit_day(UID, hid, start + timedelta(days=day_offset), True)
    view = _view(hid)
    assert view.streak == 2
    assert view.period_target == 3


def test_weekly_completion_rate_is_target_aware():
    """Meeting a '1x per week' target is 100%, not 1/7.

    Uses a target of 1 and ticks today so the assertion holds on every weekday
    — a 3x target would need three past days in the current week, which does
    not exist when the test runs on a Monday.
    """
    hid = _fresh_habit(name="Rate weekly", cadence="weekly", target_per_period=1)
    plan_service.set_habit_day(UID, hid, date.today(), True)
    assert _view(hid).completion_rate == 1.0


def test_completion_rate_only_counts_days_since_the_habit_existed():
    """A habit created today is not penalised for the weeks before it."""
    hid = _fresh_habit(name="Rate daily")
    plan_service.set_habit_day(UID, hid, date.today(), True)
    assert _view(hid).completion_rate == 1.0


def test_partial_week_scores_a_fraction_of_its_target():
    hid = _fresh_habit(name="Partial", cadence="weekly", target_per_period=4)
    plan_service.set_habit_day(UID, hid, date.today(), True)
    assert _view(hid).completion_rate == 0.25


def test_future_days_are_rejected():
    hid = _fresh_habit(name="No time travel")
    with pytest.raises(plan_service.PlanError):
        plan_service.set_habit_day(UID, hid, date.today() + timedelta(days=1), True)


def test_ticking_twice_is_idempotent():
    hid = _fresh_habit(name="Idempotent")
    plan_service.set_habit_day(UID, hid, date.today(), True)
    view = plan_service.set_habit_day(UID, hid, date.today(), True)
    assert view.streak == 1
    assert len(view.history) == 1


def test_archived_habits_are_hidden_but_kept():
    hid = _fresh_habit(name="Archived")
    _tick(hid, 0)
    plan_service.archive_habit(UID, hid)
    assert all(h.id != hid for h in plan_service.list_habits(UID))
    revived = next(
        h for h in plan_service.list_habits(UID, include_archived=True) if h.id == hid
    )
    assert revived.archived and revived.streak == 1  # entries survived


def test_invalid_habit_input_is_rejected():
    with pytest.raises(plan_service.PlanError):
        plan_service.create_habit(UID, "   ")
    with pytest.raises(plan_service.PlanError):
        plan_service.create_habit(UID, "Bad cadence", cadence="fortnightly")
    with pytest.raises(plan_service.PlanError):
        plan_service.create_habit(UID, "Too many", cadence="weekly", target_per_period=9)


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #
def test_manual_goal_progress():
    gid = plan_service.create_goal(
        UID, "Bodyweight", baseline_value=100.0, target_value=90.0,
        manual_value=95.0, unit="kg", direction="decrease",
    )
    goal = next(g for g in plan_service.list_goals(UID) if g.id == gid)
    assert goal.source == "manual"
    assert goal.current_value == 95.0
    assert goal.progress == pytest.approx(0.5)  # halfway from 100 to 90


def test_goal_without_a_target_has_no_progress():
    gid = plan_service.create_goal(UID, "Open ended", manual_value=5.0)
    goal = next(g for g in plan_service.list_goals(UID) if g.id == gid)
    assert goal.progress is None


def test_decrease_goal_without_baseline_refuses_to_guess():
    """current/target would be meaningless for a decrease goal, so: None."""
    gid = plan_service.create_goal(
        UID, "Cut", target_value=80.0, manual_value=95.0, direction="decrease"
    )
    goal = next(g for g in plan_service.list_goals(UID) if g.id == gid)
    assert goal.current_value == 95.0
    assert goal.progress is None


def test_progress_is_clamped():
    gid = plan_service.create_goal(
        UID, "Overshot", baseline_value=0.0, target_value=10.0, manual_value=25.0
    )
    goal = next(g for g in plan_service.list_goals(UID) if g.id == gid)
    assert goal.progress == 1.0


def test_metric_backed_goal_reports_its_source():
    gid = plan_service.create_goal(
        UID, "Sleep more", metric_kind="sleep", target_value=8.0,
        baseline_value=6.0, unit="h",
    )
    goal = next(g for g in plan_service.list_goals(UID) if g.id == gid)
    # Seeded DBs may or may not carry sleep data; either way the source must be
    # honest and must never be reported as "manual".
    assert goal.source in {"measured", "none"}
    assert goal.metric_kind == "sleep"
    if goal.source == "none":
        assert goal.current_value is None


def test_unknown_metric_is_rejected():
    with pytest.raises(plan_service.PlanError):
        plan_service.create_goal(UID, "Bad", metric_kind="vibes")


def test_update_goal_rejects_unknown_fields():
    gid = plan_service.create_goal(UID, "Editable")
    with pytest.raises(plan_service.PlanError):
        plan_service.update_goal(UID, gid, sneaky_column="x")
    updated = plan_service.update_goal(UID, gid, status="achieved", title="Done")
    assert updated.status == "achieved" and updated.title == "Done"


def test_snapshot_counts():
    snapshot = plan_service.get_plan_snapshot(UID)
    assert snapshot["habits_tracked"] == len(snapshot["habits"])
    assert snapshot["habits_done_today"] == len(
        [h for h in snapshot["habits"] if h.done_today]
    )
