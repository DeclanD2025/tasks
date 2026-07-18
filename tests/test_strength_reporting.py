"""Strength analytics (app/domains/strength/reporting.py).

The behaviours worth pinning here are mostly refusals: what the module declines
to claim when the data is thin. A number that appears with n=3 is worse than no
number, because it looks like a finding.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains.strength import calc, catalog, reporting, sessions, tracker

USER = 1


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


def _exercise(slug: str) -> int:
    with session_scope() as s:
        return s.scalars(
            select(StrengthExercise).where(StrengthExercise.slug == slug)
        ).first().id


def _log(slug: str, *sets, session_rpe: float | None = None) -> int:
    """One completed session of `slug`, sets given as (weight, reps, rpe)."""
    workout_id = sessions.start_session(USER, name=f"{slug} session")
    block_id = sessions.add_exercise(USER, workout_id, _exercise(slug))
    for weight, reps, rpe in sets:
        sessions.log_set(USER, block_id, weight_kg=weight, reps=reps, rpe=rpe)
    sessions.finish_session(USER, workout_id, session_rpe=session_rpe)
    return workout_id


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
def test_volume_excludes_warmups():
    workout_id = sessions.start_session(USER)
    block_id = sessions.add_exercise(USER, workout_id, _exercise("bench-press"))
    sessions.log_set(USER, block_id, weight_kg=60, reps=8, set_type="warmup")
    sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=8)
    sessions.finish_session(USER, workout_id)

    summary = reporting.volume_summary(reporting._load_sets(USER))
    assert summary["volumeKg"] == 500.0
    assert summary["workingSets"] == 1


def test_hard_sets_and_working_sets_are_different_counts():
    _log("bench-press", (100, 5, 8.0), (100, 5, 6.0), (100, 5, None))
    summary = reporting.volume_summary(reporting._load_sets(USER))
    assert summary["workingSets"] == 3
    assert summary["hardSets"] == 1
    assert summary["ratedSets"] == 2


def test_volume_groups_by_movement_pattern_and_family():
    _log("bench-press", (100, 5, 8.0))
    _log("dumbbell-bench-press", (30, 10, 8.0))
    sets = reporting._load_sets(USER)

    movements = {r["key"]: r for r in reporting.volume_by_movement(sets)}
    assert "horizontal_push" in movements
    assert movements["horizontal_push"]["sets"] == 2

    families = {r["key"]: r for r in reporting.volume_by_family(sets)}
    assert families["bench-press"]["sets"] == 2, "variants roll up to one family"


def test_muscle_volume_keeps_direct_and_indirect_apart():
    """Indirect weighting is a convention for comparability, not a measurement,
    so summing them into one number would overstate what is known."""
    _log("bench-press", (100, 5, 8.0))
    rows = {r["muscle"]: r for r in reporting.muscle_volume(reporting._load_sets(USER))}
    assert rows["Chest"]["directSets"] == 1
    assert rows["Chest"]["indirectSets"] == 0
    assert rows["Triceps"]["directSets"] == 0
    assert rows["Triceps"]["indirectSets"] == 0.5


def test_muscle_volume_reports_days_since_last_trained():
    _log("bench-press", (100, 5, 8.0))
    rows = {r["muscle"]: r for r in reporting.muscle_volume(reporting._load_sets(USER))}
    assert rows["Chest"]["daysSince"] == 0
    assert rows["Chest"]["lastTrained"] == date.today().isoformat()


# --------------------------------------------------------------------------- #
# Balance
# --------------------------------------------------------------------------- #
def test_a_ratio_against_zero_work_is_none_not_infinity():
    """Push/pull with no pulling is not "infinity", it is a programme with no
    pulling in it — which the warnings say in words."""
    _log("bench-press", (100, 5, 8.0))
    balance = reporting.balance_ratios(reporting._load_sets(USER))
    assert balance["pullSets"] == 0
    assert balance["pushPull"] is None


def test_balance_ratio_computes_when_both_sides_have_work():
    _log("bench-press", (100, 5, 8.0), (100, 5, 8.0))
    _log("barbell-row", (80, 8, 8.0))
    balance = reporting.balance_ratios(reporting._load_sets(USER))
    assert balance["pushPull"] == 2.0


# --------------------------------------------------------------------------- #
# Warnings
# --------------------------------------------------------------------------- #
def test_a_programme_with_no_pulling_is_flagged():
    _log("bench-press", (100, 5, 8.0))
    codes = {w["code"] for w in reporting.programme_warnings(reporting._load_sets(USER))}
    assert "no_pulling" in codes


def test_mostly_unrated_sets_are_flagged_as_limiting_the_analysis():
    _log("bench-press", (100, 5, None), (100, 5, None), (100, 5, None))
    warnings = reporting.programme_warnings(reporting._load_sets(USER))
    codes = {w["code"] for w in warnings}
    assert "mostly_unrated" in codes


def test_warnings_are_empty_when_there_is_nothing_to_judge():
    assert reporting.programme_warnings([]) == []


# --------------------------------------------------------------------------- #
# Trends and plateaus
# --------------------------------------------------------------------------- #
def test_a_plateau_needs_repeated_exposures_not_two_flat_sessions():
    """Two unchanged sessions is a fortnight. Calling that a plateau teaches
    the operator to ignore the signal."""
    _log("bench-press", (100, 5, 8.0))
    _log("bench-press", (100, 5, 8.0))
    trend = reporting.exercise_trend(reporting._load_sets(USER), exercise_id=_exercise("bench-press"))
    assert trend["plateau"]["plateaued"] is False
    assert trend["plateau"]["confident"] is False
    assert "needed before calling a plateau" in trend["plateau"]["reason"]


def test_a_genuinely_flat_lift_is_called_a_plateau_once_there_is_evidence():
    for _ in range(4):
        _log("bench-press", (100, 5, 8.0))
    trend = reporting.exercise_trend(reporting._load_sets(USER), exercise_id=_exercise("bench-press"))
    assert trend["plateau"]["confident"] is True
    assert trend["plateau"]["plateaued"] is True


def test_a_lift_that_is_still_moving_is_not_a_plateau():
    for load in (100, 102.5, 105, 107.5):
        _log("bench-press", (load, 5, 8.0))
    trend = reporting.exercise_trend(reporting._load_sets(USER), exercise_id=_exercise("bench-press"))
    assert trend["plateau"]["plateaued"] is False
    assert trend["plateau"]["confident"] is True


def test_window_changes_refuse_to_compare_against_absent_history():
    """"Up 40% over 26 weeks" is misleading when the log is three days old."""
    _log("bench-press", (100, 5, 8.0))
    trend = reporting.exercise_trend(reporting._load_sets(USER), exercise_id=_exercise("bench-press"))
    for change in trend["changes"]:
        assert change["available"] is False
        assert "compare with" in change["reason"]


# --------------------------------------------------------------------------- #
# Adherence
# --------------------------------------------------------------------------- #
def test_adherence_says_so_when_nothing_was_scheduled():
    """A completion rate with no plan behind it is a made-up number."""
    _log("bench-press", (100, 5, 8.0))
    result = reporting.adherence(USER, since=date.today() - timedelta(days=7))
    assert result["rateAvailable"] is False
    assert result["completionRate"] is None
    assert "no plan to measure" in result["note"]


def test_unplanned_sessions_are_counted_but_kept_out_of_the_rate():
    """Training that was never scheduled cannot be adherence to a schedule."""
    _log("bench-press", (100, 5, 8.0))
    result = reporting.adherence(USER, since=date.today() - timedelta(days=7))
    assert result["unplannedSessions"] == 1
    assert result["completionRate"] is None


def test_partial_and_abandoned_sessions_are_reported_separately():
    workout_id = sessions.start_session(USER)
    sessions.add_exercise(USER, workout_id, _exercise("bench-press"))
    sessions.finish_session(USER, workout_id)  # no sets → abandoned

    result = reporting.adherence(USER, since=date.today() - timedelta(days=7))
    assert result["abandonedSessions"] == 1
    assert result["completedSessions"] == 0


# --------------------------------------------------------------------------- #
# Readiness associations
# --------------------------------------------------------------------------- #
def test_associations_are_refused_below_the_sample_threshold():
    """A coefficient over six sessions presented as insight would be the most
    dishonest thing in the module."""
    for _ in range(3):
        _log("bench-press", (100, 5, 8.0), session_rpe=8.0)
    rows = reporting.readiness_associations(USER)
    assert rows, "the refusal itself must be reported"
    for row in rows:
        assert row["available"] is False
        assert row["observations"] < reporting.MIN_CORRELATION_N
        assert str(reporting.MIN_CORRELATION_N) in row["note"]


def test_a_reported_association_carries_its_sample_size_and_a_causal_caveat():
    for _ in range(reporting.MIN_CORRELATION_N + 2):
        _log("bench-press", (100, 5, 8.0), session_rpe=8.0)
    rows = {r["input"]: r for r in reporting.readiness_associations(USER)}
    reported = [r for r in rows.values() if r["available"]]
    for row in reported:
        assert row["observations"] >= reporting.MIN_CORRELATION_N
        assert "not evidence that one causes the other" in row["note"]
        assert row["from"] and row["to"]
        assert row["strength"] in {"strong", "moderate", "weak", "negligible", "unknown"}


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def test_overview_assembles_without_any_data():
    """An empty log must render an empty dashboard, not raise."""
    result = reporting.overview(USER, days=28)
    assert result["summary"]["volumeKg"] == 0
    assert result["byWeek"] == []
    assert result["adherence"]["rateAvailable"] is False


def test_overview_exposes_the_weighting_it_used():
    """The indirect-set weighting is a convention, so the number it produced
    has to travel with it."""
    _log("bench-press", (100, 5, 8.0))
    result = reporting.overview(USER)
    weighting = result["weighting"]
    assert set(weighting) == {"primary", "secondary", "stabiliser"}
    assert weighting["primary"] > weighting["secondary"] > weighting["stabiliser"] > 0
