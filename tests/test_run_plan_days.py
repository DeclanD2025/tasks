"""The run planner places sessions on real weekdays.

The planner used to emit positional labels ("Next"/"Midweek"/"Weekend") and
refuse to name a day. It now infers days from the athlete's actual running
history — so these tests pin the inference, and just as importantly pin the
honesty flag that says when there was too little history to infer anything.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.domains import personal_os


def _run(day: date, km: float = 5.0) -> SimpleNamespace:
    return SimpleNamespace(
        started_at=datetime(day.year, day.month, day.day, 7, 0),
        distance_meters=km * 1000.0,
    )


def _runs_on(weekdays: tuple[int, ...], weeks: int, today: date, km: float = 5.0) -> list:
    """Build history: a run on each given weekday, for the last N weeks."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for week in range(1, weeks + 1):
        start = monday - timedelta(days=7 * week)
        for weekday in weekdays:
            out.append(_run(start + timedelta(days=weekday), km))
    return out


# --------------------------------------------------------------------------- #
# Weekday inference
# --------------------------------------------------------------------------- #
def test_thin_history_falls_back_to_a_spread_and_says_so():
    weekdays, source = personal_os._planned_weekdays(Counter({0: 2}))
    assert source == "spread"
    assert weekdays == list(personal_os._DEFAULT_SPREAD)


def test_enough_history_infers_the_athletes_own_days():
    # Mon/Wed/Fri, three weeks running.
    counts = Counter({0: 3, 2: 3, 4: 3})
    weekdays, source = personal_os._planned_weekdays(counts)
    assert source == "observed"
    assert weekdays == [0, 2, 4]


def test_inference_prefers_the_most_frequent_days():
    counts = Counter({0: 8, 2: 7, 4: 6, 6: 1})
    weekdays, _ = personal_os._planned_weekdays(counts)
    assert weekdays == [0, 2, 4]  # Sunday's single run does not make the cut


def test_ties_break_deterministically():
    counts = Counter({5: 4, 1: 4, 3: 4, 0: 4})
    first, _ = personal_os._planned_weekdays(counts)
    second, _ = personal_os._planned_weekdays(counts)
    assert first == second == [0, 1, 3]  # earlier weekdays win an equal tie


def test_too_few_distinct_days_are_padded():
    counts = Counter({0: 10})  # only ever runs Mondays
    weekdays, source = personal_os._planned_weekdays(counts)
    assert source == "observed"
    assert len(weekdays) == 3 and 0 in weekdays


# --------------------------------------------------------------------------- #
# Date scheduling
# --------------------------------------------------------------------------- #
def test_scheduled_days_are_distinct_and_in_the_future():
    today = date(2026, 7, 18)  # a Saturday
    workouts = _runs_on((0, 2, 4), weeks=3, today=today)
    days, source = personal_os._schedule_run_days(workouts, today, ran_today=False)
    assert source == "observed"
    assert len(days) == len(set(days)) == 3
    assert all(d >= today for d in days)
    assert days == sorted(days)


def test_a_run_already_done_today_pushes_the_plan_to_tomorrow():
    today = date(2026, 7, 18)
    workouts = _runs_on((0, 2, 4), weeks=3, today=today)
    days, _ = personal_os._schedule_run_days(workouts, today, ran_today=True)
    assert min(days) > today


def test_a_single_preferred_weekday_still_yields_three_days():
    today = date(2026, 7, 18)
    workouts = _runs_on((2,), weeks=8, today=today)  # Wednesdays only
    days, _ = personal_os._schedule_run_days(workouts, today, ran_today=False)
    assert len(set(days)) == 3


# --------------------------------------------------------------------------- #
# Session placement
# --------------------------------------------------------------------------- #
def _plan(today: date, workouts: list, score: float | None = 70.0):
    seed = personal_os.RunSessionSuggestion(
        "Next", "Easy run", "Easy run - 5.0 km", "detail", 5.0, "low"
    )
    return personal_os._weekly_run_plan(
        seed, weekly_target=30.0, score=score, workouts=workouts,
        today=today, ran_today=False,
    )


def test_every_session_names_a_weekday():
    today = date(2026, 7, 18)
    plan = _plan(today, _runs_on((0, 2, 5), weeks=3, today=today))
    assert len(plan) == 3
    for session in plan:
        assert session.day is not None
        assert session.day_source == "observed"
        # The label carries a real weekday name, not a position.
        assert session.day.strftime("%a") in session.day_label
        assert session.day_label not in {"Next", "Midweek", "Weekend"}


def test_the_next_run_is_the_soonest_session():
    today = date(2026, 7, 18)
    plan = _plan(today, _runs_on((0, 2, 5), weeks=3, today=today))
    assert plan[0].day == min(s.day for s in plan)


def test_the_long_run_lands_on_the_athletes_longest_day():
    """Saturday is where the long runs actually happen, so that is where it goes."""
    today = date(2026, 7, 19)  # Sunday, so Saturday is the far end of the week
    workouts = (
        _runs_on((1,), weeks=4, today=today, km=5.0)    # Tue: short
        + _runs_on((3,), weeks=4, today=today, km=5.0)  # Thu: short
        + _runs_on((5,), weeks=4, today=today, km=16.0)  # Sat: long
    )
    plan = _plan(today, workouts)
    long_run = next(s for s in plan if s.session_type == "Long run")
    assert long_run.day.weekday() == 5


def test_the_soonest_slot_keeps_its_prescribed_session():
    """When the long day is today, the long run moves rather than overriding it.

    The next run's type is set by the recovery/frequency rules upstream, so the
    scheduler must not reassign it — otherwise a "Recovery run" prescribed for
    a tired athlete would silently become a long run just because it is a
    Saturday.
    """
    today = date(2026, 7, 18)  # Saturday: the athlete's long day is today
    workouts = (
        _runs_on((1,), weeks=4, today=today, km=5.0)
        + _runs_on((3,), weeks=4, today=today, km=5.0)
        + _runs_on((5,), weeks=4, today=today, km=16.0)
    )
    plan = _plan(today, workouts)
    assert plan[0].day == today
    assert plan[0].session_type == "Easy run"  # unchanged by scheduling
    long_run = next(s for s in plan if s.session_type == "Long run")
    assert long_run.day > today


def test_thin_history_marks_the_days_as_a_default():
    today = date(2026, 7, 18)
    plan = _plan(today, [_run(today - timedelta(days=3))])
    assert all(s.day_source == "spread" for s in plan)
    assert all(s.day is not None for s in plan)


def test_low_recovery_still_downgrades_the_quality_session():
    """Scheduling must not disturb the existing recovery guardrail."""
    today = date(2026, 7, 18)
    workouts = _runs_on((0, 2, 5), weeks=3, today=today)
    plan = _plan(today, workouts, score=40.0)
    assert any(s.session_type == "Recovery run" for s in plan[1:])
    assert not any(s.session_type == "Intervals" for s in plan)


def test_day_labels_flag_today_and_tomorrow():
    today = date(2026, 7, 18)
    assert personal_os._day_label(today, today).startswith("Today")
    assert personal_os._day_label(today + timedelta(days=1), today).startswith("Tomorrow")
    assert personal_os._day_label(today + timedelta(days=4), today) == "Wed 22 Jul"
