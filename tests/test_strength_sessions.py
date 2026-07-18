"""Session lifecycle and personal records (app/domains/strength/).

Integration-level: these run against a real SQLite database through the real
services, because the behaviours worth protecting here — idempotency,
corrections rebuilding records, partial completion — are all about what
survives a round trip, not about arithmetic.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
    utcnow,
)
from app.domains.strength import catalog, records, sessions, tracker

USER = 1


@pytest.fixture(autouse=True)
def _clean_strength():
    """The test DB is session-scoped and shared, so wipe strength state around
    each test — otherwise a stray active session fails every later start."""
    tracker.ensure_seeded()
    catalog.enrich_catalog()
    yield
    with session_scope() as s:
        # Break the PR chain's self-reference before deleting, same reason as
        # in records.rebuild_records_for_exercise.
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


def _exercise(slug: str = "bench-press") -> int:
    with session_scope() as s:
        row = s.scalars(
            select(StrengthExercise).where(StrengthExercise.slug == slug)
        ).first()
        assert row is not None, f"seed is missing {slug}"
        return row.id


def _session_with(slug: str = "bench-press") -> tuple[int, int]:
    workout_id = sessions.start_session(USER, name="Test session")
    block_id = sessions.add_exercise(USER, workout_id, _exercise(slug))
    return workout_id, block_id


# --------------------------------------------------------------------------- #
# Starting and resuming
# --------------------------------------------------------------------------- #
def test_starting_a_session_snapshots_readiness_and_bodyweight():
    """Apple Health revises sleep and HRV after the fact, so a live join would
    rewrite the conditions a session was performed under."""
    workout_id = sessions.start_session(USER, name="Snapshot test")
    detail = sessions.session_detail(USER, workout_id)
    assert "readiness" in detail
    assert detail["readiness"].get("available") in (True, False)
    assert detail["status"] == "active"


def test_a_second_concurrent_session_is_refused():
    """Two live sessions means the operator has lost track of where their sets
    are landing. Resume exists so they never need a second."""
    sessions.start_session(USER, name="First")
    with pytest.raises(sessions.SessionError, match="already in progress"):
        sessions.start_session(USER, name="Second")


def test_an_interrupted_session_can_be_resumed():
    """Browser refresh, crash, accidental navigation — the session is server
    state, so none of them lose it."""
    workout_id, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)

    resumed = sessions.active_session(USER)
    assert resumed is not None
    assert resumed["id"] == workout_id
    assert len(resumed["exercises"][0]["sets"]) == 1


def test_no_active_session_reads_as_none_not_an_error():
    assert sessions.active_session(USER) is None


def test_starting_from_a_template_copies_the_prescription():
    """Copied, not referenced: editing the template next month must not rewrite
    what this session was asked to do."""
    templates = tracker.templates()
    assert templates, "seed should provide templates"
    workout_id = sessions.start_session(USER, template_id=templates[0]["id"])
    detail = sessions.session_detail(USER, workout_id)
    assert detail["exercises"], "template exercises should be copied in"
    assert detail["exercises"][0]["prescription"]["targetSets"] >= 1


def test_each_exercise_freezes_how_it_was_classified():
    """Reclassifying an exercise later must not restate historical volume."""
    workout_id, block_id = _session_with()
    with session_scope() as s:
        block = s.get(StrengthWorkoutExercise, block_id)
        snapshot = block.classification_snapshot
    assert snapshot["primaryMuscle"] == "Chest"
    assert snapshot["movementPattern"] == "horizontal_push"
    assert snapshot["familySlug"] == "bench-press"


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def test_logging_a_set_stores_it_individually():
    _, block_id = _session_with()
    result = sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=8)
    assert result["weightKg"] == 100
    assert result["reps"] == 5
    assert result["setNumber"] == 1
    assert result["completed"] is True


def test_rir_is_derived_from_rpe_when_not_given():
    _, block_id = _session_with()
    result = sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=8)
    assert result["rir"] == 2.0


def test_a_retried_set_is_not_written_twice():
    """A phone that loses signal mid-request retries. Without idempotency that
    is a duplicated set, and duplicated sets are invisible once the operator
    has moved on."""
    _, block_id = _session_with()
    first = sessions.log_set(USER, block_id, client_key="abc-123", weight_kg=100, reps=5)
    second = sessions.log_set(USER, block_id, client_key="abc-123", weight_kg=100, reps=5)
    assert first["id"] == second["id"]

    detail = sessions.session_detail(USER, first_workout_id := _only_workout())
    assert len(detail["exercises"][0]["sets"]) == 1
    assert first_workout_id  # silence linters; the id is the assertion's subject


def test_weights_entered_in_pounds_are_stored_in_kilograms():
    """Canonical units, so switching display later cannot corrupt history."""
    _, block_id = _session_with()
    result = sessions.log_set(USER, block_id, weight_kg=225, reps=5, unit="lb")
    assert result["weightKg"] == pytest.approx(102.06, abs=0.01)


def test_set_numbers_increment_within_an_exercise():
    _, block_id = _session_with()
    a = sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    b = sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    assert (a["setNumber"], b["setNumber"]) == (1, 2)


def test_previous_performance_is_offered_for_the_next_session():
    """The single most useful number to have on screen mid-set."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    workout_id, _ = _session_with()
    detail = sessions.session_detail(USER, workout_id)
    previous = detail["exercises"][0]["previous"]
    assert previous is not None
    assert previous["sets"][0]["weightKg"] == 100


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
def test_correcting_a_set_keeps_what_it_said_before():
    _, block_id = _session_with()
    logged = sessions.log_set(USER, block_id, weight_kg=200, reps=5)
    sessions.update_set(USER, logged["id"], weight_kg=100)

    with session_scope() as s:
        entry = s.get(StrengthSetEntry, logged["id"])
        assert entry.weight_kg == 100
        assert entry.edit_history
        assert entry.edit_history[0]["was"]["weight_kg"] == 200


def test_updating_an_unknown_field_is_refused():
    """Otherwise a typo in an API call silently writes nothing."""
    _, block_id = _session_with()
    logged = sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    with pytest.raises(sessions.SessionError, match="Cannot update"):
        sessions.update_set(USER, logged["id"], bogus_field=1)


def test_a_voided_set_is_kept_but_leaves_the_statistics():
    _, block_id = _session_with()
    good = sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    bad = sessions.log_set(USER, block_id, weight_kg=999, reps=5)
    sessions.void_set(USER, bad["id"], reason="mistyped")

    detail = sessions.session_detail(USER, _only_workout())
    live = detail["exercises"][0]["sets"]
    voided = detail["exercises"][0]["voidedSets"]
    assert [s["id"] for s in live] == [good["id"]]
    assert [s["id"] for s in voided] == [bad["id"]]
    assert voided[0]["voidReason"] == "mistyped"


# --------------------------------------------------------------------------- #
# Finishing
# --------------------------------------------------------------------------- #
def test_a_session_where_everything_was_trained_is_completed():
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    summary = sessions.finish_session(USER, _only_workout())
    assert summary["status"] == "completed"


def test_a_session_with_untouched_exercises_is_partial_not_complete():
    """Collapsing partial into complete makes adherence unanswerable."""
    workout_id, block_id = _session_with("bench-press")
    sessions.add_exercise(USER, workout_id, _exercise("squat"))
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    summary = sessions.finish_session(USER, workout_id)
    assert summary["status"] == "partial"


def test_a_session_with_no_sets_is_abandoned_not_completed():
    workout_id, _ = _session_with()
    summary = sessions.finish_session(USER, workout_id)
    assert summary["status"] == "abandoned"


def test_a_session_with_work_in_it_cannot_be_discarded():
    """The work happened, even if the session did not finish."""
    workout_id, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    with pytest.raises(sessions.SessionError, match="Abandon it instead"):
        sessions.discard_session(USER, workout_id)


def test_an_empty_session_can_be_discarded():
    """A mis-tap on "start" should not litter the history."""
    workout_id, _ = _session_with()
    sessions.discard_session(USER, workout_id)
    assert sessions.active_session(USER) is None


def test_the_summary_reports_volume_and_separates_hard_sets():
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=60, reps=8, set_type="warmup")
    sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=8)
    sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=6)
    summary = sessions.finish_session(USER, _only_workout())

    assert summary["volumeKg"] == 1000.0  # warm-up excluded
    assert summary["workingSets"] == 2
    assert summary["hardSets"] == 1


def test_the_summary_admits_where_its_data_is_thin():
    """Better to say the session was unrated than to let the analytics treat it
    as if effort had been recorded."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    summary = sessions.finish_session(USER, _only_workout())
    assert any("effort ratings" in w for w in summary["dataQuality"])
    assert any("session RPE" in w for w in summary["dataQuality"])


# --------------------------------------------------------------------------- #
# Substitution
# --------------------------------------------------------------------------- #
def test_substituting_keeps_the_reason():
    """"Rack was busy" and "knee hurt" imply different follow-ups."""
    workout_id, block_id = _session_with("squat")
    sessions.substitute_exercise(USER, block_id, _exercise("leg-press"), reason="knee pain")
    detail = sessions.session_detail(USER, workout_id)
    assert detail["exercises"][0]["name"] == "Leg Press"
    assert detail["exercises"][0]["substitutionReason"] == "knee pain"


def test_an_exercise_with_logged_sets_cannot_be_relabelled():
    """Those sets really happened as the original movement."""
    _, block_id = _session_with("squat")
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    with pytest.raises(sessions.SessionError, match="already logged"):
        sessions.substitute_exercise(USER, block_id, _exercise("leg-press"))


# --------------------------------------------------------------------------- #
# Personal records
# --------------------------------------------------------------------------- #
def test_a_first_ever_performance_is_recorded_but_not_announced():
    """Every exercise's first session sets eight simultaneous "records".
    Announcing them teaches the operator to ignore the feature."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5, rpe=8)
    summary = sessions.finish_session(USER, _only_workout())

    assert summary["newRecords"] == []
    standing = records.active_records(USER, _exercise())
    assert standing, "the baseline must still be stored"


def test_beating_a_previous_best_is_announced_with_what_it_beat():
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=105, reps=5)
    summary = sessions.finish_session(USER, _only_workout())

    heaviest = [r for r in summary["newRecords"] if r["type"] == "heaviest_weight"]
    assert heaviest, f"expected a heaviest-weight PR, got {summary['newRecords']}"
    assert heaviest[0]["value"] == 105
    assert heaviest[0]["previous"] == 100


def test_a_warmup_never_sets_a_record():
    """A heavy warm-up single would otherwise outrank every working set."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=140, reps=1, set_type="warmup")
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    summary = sessions.finish_session(USER, _only_workout())
    assert not any(r["value"] == 140 for r in summary["newRecords"])


def test_a_high_rep_set_sets_no_estimated_1rm_record():
    """Estimating a 1RM from 25 reps produces a number, just not that number."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=40, reps=25)
    sessions.finish_session(USER, _only_workout())
    standing = {r["type"] for r in records.active_records(USER, _exercise())}
    assert "best_e1rm" not in standing


def test_voiding_a_mistyped_set_removes_the_record_it_created():
    """The whole reason records are rebuilt rather than patched: a 999 kg typo
    must not stand as an all-time best after being corrected."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    _, block_id = _session_with()
    bad = sessions.log_set(USER, block_id, weight_kg=999, reps=5)
    sessions.finish_session(USER, _only_workout())
    assert _best(records.active_records(USER, _exercise())) == 999

    sessions.void_set(USER, bad["id"], reason="mistyped")
    assert _best(records.active_records(USER, _exercise())) == 100


def test_correcting_a_set_downward_restores_the_earlier_record():
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    _, block_id = _session_with()
    bad = sessions.log_set(USER, block_id, weight_kg=500, reps=5)
    sessions.finish_session(USER, _only_workout())
    sessions.update_set(USER, bad["id"], weight_kg=102.5)

    assert _best(records.active_records(USER, _exercise())) == 102.5


def test_records_keep_the_chain_of_what_they_beat():
    """Kept rather than overwritten, so the progression of a lift is itself a
    readable series."""
    for load in (100, 105, 110):
        _, block_id = _session_with()
        sessions.log_set(USER, block_id, weight_kg=load, reps=5)
        sessions.finish_session(USER, _only_workout())

    with session_scope() as s:
        rows = s.scalars(
            select(StrengthPersonalRecord).where(
                StrengthPersonalRecord.record_type == "heaviest_weight",
                StrengthPersonalRecord.exercise_id == _exercise(),
            )
        ).all()
        values = sorted(r.value for r in rows)
        active = [r for r in rows if r.is_active]
    assert values == [100, 105, 110]
    assert len(active) == 1 and active[0].value == 110


def test_a_rep_target_record_keeps_its_rep_count():
    """A "5-rep best" without the 5 is not a claim about anything."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())

    rep_records = [
        r for r in records.active_records(USER, _exercise())
        if r["type"] == "best_at_rep_target"
    ]
    assert rep_records
    assert rep_records[0]["qualifier"] == 5.0
    assert "5-rep" in rep_records[0]["label"]


def test_an_estimated_1rm_record_says_which_formula_made_it():
    """Two estimates from different formulas are not comparable."""
    _, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=100, reps=5)
    sessions.finish_session(USER, _only_workout())
    e1rm = [
        r for r in records.active_records(USER, _exercise()) if r["type"] == "best_e1rm"
    ]
    assert e1rm and e1rm[0]["method"] == "epley"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _only_workout() -> int:
    """The most recent workout for the user — tests create exactly one at a time."""
    with session_scope() as s:
        row = s.scalars(
            select(StrengthWorkout)
            .where(StrengthWorkout.user_id == USER)
            .order_by(StrengthWorkout.id.desc())
        ).first()
        assert row is not None
        return row.id


def _best(records_list: list[dict]) -> float | None:
    for record in records_list:
        if record["type"] == "heaviest_weight":
            return record["value"]
    return None


# --------------------------------------------------------------------------- #
# Apple Health linkage
# --------------------------------------------------------------------------- #
def test_a_session_links_to_the_apple_health_activity_covering_it():
    """A logged session knows what was lifted but nothing about heart rate; the
    Apple Health record knows the reverse. Linking gives one session both."""
    from app.db.models import Workout

    workout_id, block_id = _session_with()
    sessions.log_set(USER, block_id, weight_kg=70, reps=6)
    sessions.finish_session(USER, workout_id)

    with session_scope() as s:
        started = s.get(StrengthWorkout, workout_id).started_at
        s.add(Workout(
            user_id=USER, source="hae", source_id="test-link-1",
            title="Traditional Strength Training", sport_type="other",
            started_at=started, duration_seconds=2220, average_heart_rate=99.7,
        ))
    try:
        match = sessions.link_health_workout(USER, workout_id)
        assert match is not None
        assert match["averageHeartRate"] == pytest.approx(99.7)
        with session_scope() as s:
            assert s.get(StrengthWorkout, workout_id).workout_id == match["workoutId"]
    finally:
        with session_scope() as s:
            for row in s.scalars(
                select(StrengthWorkout).where(StrengthWorkout.user_id == USER)
            ).all():
                row.workout_id = None
            s.flush()
            for row in s.scalars(
                select(Workout).where(Workout.source_id == "test-link-1")
            ).all():
                s.delete(row)


def test_an_ambiguous_match_is_left_unlinked_rather_than_guessed():
    """A wrong link attaches a run's heart rate to a bench session, and nothing
    downstream would ever question it."""
    from app.db.models import Workout

    workout_id, _ = _session_with()
    with session_scope() as s:
        started = s.get(StrengthWorkout, workout_id).started_at
        for i in (1, 2):
            s.add(Workout(
                user_id=USER, source="hae", source_id=f"test-ambig-{i}",
                title="Traditional Strength Training", sport_type="other",
                started_at=started + timedelta(minutes=i),
            ))
    try:
        assert sessions.link_health_workout(USER, workout_id) is None
    finally:
        with session_scope() as s:
            for row in s.scalars(
                select(Workout).where(Workout.source_id.like("test-ambig-%"))
            ).all():
                s.delete(row)


def test_a_nearby_run_is_not_matched_to_a_strength_session():
    from app.db.models import Workout

    workout_id, _ = _session_with()
    with session_scope() as s:
        started = s.get(StrengthWorkout, workout_id).started_at
        s.add(Workout(
            user_id=USER, source="hae", source_id="test-run-1",
            title="Outdoor Run", sport_type="run", started_at=started,
        ))
    try:
        assert sessions.link_health_workout(USER, workout_id) is None
    finally:
        with session_scope() as s:
            for row in s.scalars(
                select(Workout).where(Workout.source_id == "test-run-1")
            ).all():
                s.delete(row)
