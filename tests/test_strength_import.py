"""Importing training history (app/domains/strength/export.py).

The fixture is a real session — Declan's "Upper Body", 18 July 2026 — because
imported data is exactly where invented test fixtures hide problems. Real logs
have warm-up ramps, rest times, per-side dumbbell loads and equipment notes,
and every one of those is a chance to silently drop or corrupt something.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains.strength import catalog, export, reporting, records, tracker

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


def _upper_body_payload() -> dict:
    """The session as recorded on the phone.

    Flame-marked sets in the source app are warm-ups: they carry no set number
    and the working sets restart at 1. Preserving that distinction is the whole
    reason the import takes a `set_type`.
    """
    return {
        "sessions": [
            {
                "session_id": 1,
                "import_id": "phone-2026-07-18-upper-body",
                "name": "Upper Body",
                "status": "completed",
                "started_at": "2026-07-18T20:18:00",
                "finished_at": "2026-07-18T20:56:00",
            }
        ],
        "sets": [
            # Bench Press — two warm-ups, three working
            {"session_id": 1, "exercise_slug": "bench-press", "set_number": 1,
             "set_type": "warmup", "weight_kg": 40, "reps": 12, "rest_seconds": 275},
            {"session_id": 1, "exercise_slug": "bench-press", "set_number": 2,
             "set_type": "warmup", "weight_kg": 60, "reps": 8, "rest_seconds": 74},
            {"session_id": 1, "exercise_slug": "bench-press", "set_number": 3,
             "set_type": "working", "weight_kg": 70, "reps": 6, "rest_seconds": 157},
            {"session_id": 1, "exercise_slug": "bench-press", "set_number": 4,
             "set_type": "working", "weight_kg": 70, "reps": 6, "rest_seconds": 264},
            {"session_id": 1, "exercise_slug": "bench-press", "set_number": 5,
             "set_type": "working", "weight_kg": 70, "reps": 6, "rest_seconds": 179},
            # Dumbbell shoulder press — 22 kg per hand
            {"session_id": 1, "exercise_slug": "dumbbell-shoulder-press", "set_number": 1,
             "set_type": "working", "weight_kg": 22, "reps": 6, "rest_seconds": 237},
            {"session_id": 1, "exercise_slug": "dumbbell-shoulder-press", "set_number": 2,
             "set_type": "working", "weight_kg": 22, "reps": 8, "rest_seconds": 390},
            {"session_id": 1, "exercise_slug": "dumbbell-shoulder-press", "set_number": 3,
             "set_type": "working", "weight_kg": 22, "reps": 8, "rest_seconds": 202},
            # Tricep pushdown on a 1:1 single pulley — the ratio matters
            {"session_id": 1, "exercise_slug": "tricep-pushdown", "set_number": 1,
             "set_type": "working", "weight_kg": 21, "reps": 8, "rest_seconds": 41,
             "equipment_variation": "1:1 single pulley"},
            {"session_id": 1, "exercise_slug": "tricep-pushdown", "set_number": 2,
             "set_type": "working", "weight_kg": 21, "reps": 8, "rest_seconds": 236,
             "equipment_variation": "1:1 single pulley"},
            {"session_id": 1, "exercise_slug": "tricep-pushdown", "set_number": 3,
             "set_type": "working", "weight_kg": 21, "reps": 8,
             "equipment_variation": "1:1 single pulley"},
        ],
    }


# --------------------------------------------------------------------------- #
# Importing
# --------------------------------------------------------------------------- #
def test_a_real_session_imports_with_its_sets():
    result = export.import_sessions(USER, _upper_body_payload(), source="phone")
    assert result["imported"] == 1
    assert result["problems"] == []

    with session_scope() as s:
        assert s.scalars(select(StrengthWorkout)).one().name == "Upper Body"
        assert len(s.scalars(select(StrengthSetEntry)).all()) == 11


def test_the_session_keeps_the_date_it_was_performed():
    """Importing at today's date would put a July session wherever the import
    happened to run, wrecking every trend it appears in."""
    export.import_sessions(USER, _upper_body_payload())
    with session_scope() as s:
        workout = s.scalars(select(StrengthWorkout)).one()
        assert workout.started_at.date().isoformat() == "2026-07-18"
        assert workout.started_at.hour == 20


def test_warmups_survive_the_import_as_warmups():
    """A warm-up ramp imported as working sets would inflate this session's
    volume by 76% and hand it a false 40 kg "record" at 12 reps."""
    export.import_sessions(USER, _upper_body_payload())
    sets = reporting._load_sets(USER)

    bench = [s for s in sets if s.exercise_name == "Bench Press"]
    assert len(bench) == 3, "only the three 70 kg sets should count"
    assert {s.weight_kg for s in bench} == {70.0}


def test_working_volume_excludes_the_warmup_ramp():
    export.import_sessions(USER, _upper_body_payload())
    summary = reporting.volume_summary(reporting._load_sets(USER))

    # Bench 3×70×6 = 1260. Dumbbells count both hands: 22×(6+8+8)×2 = 968.
    # Triceps 3×21×8 = 504.
    assert summary["volumeKg"] == pytest.approx(1260 + 968 + 504)
    assert summary["workingSets"] == 9


def test_dumbbell_loads_count_both_hands():
    """22 kg per hand for 8 reps is 352 kg of work, not 176 — the limb did it
    twice. Getting this wrong halves every dumbbell trend."""
    export.import_sessions(USER, _upper_body_payload())
    sets = reporting._load_sets(USER)
    press = [s for s in sets if "Shoulder Press" in s.exercise_name]
    eight_rep = [s for s in press if s.reps == 8][0]
    assert eight_rep.volume_kg == pytest.approx(352.0)


def test_rest_durations_are_preserved():
    """The only signal for how a session was actually paced. The import used to
    drop them silently."""
    export.import_sessions(USER, _upper_body_payload())
    with session_scope() as s:
        rests = [
            e.rest_seconds
            for e in s.scalars(
                select(StrengthSetEntry).order_by(StrengthSetEntry.id)
            ).all()
        ]
    assert rests[:5] == [275, 74, 157, 264, 179]
    assert rests[-1] is None, "a missing rest stays null rather than being guessed"


def test_the_equipment_variation_is_kept():
    """A cable stack at 2:1 and the same number at 1:1 are different loads."""
    export.import_sessions(USER, _upper_body_payload())
    with session_scope() as s:
        blocks = s.scalars(select(StrengthWorkoutExercise)).all()
        variations = {b.equipment_variation for b in blocks if b.equipment_variation}
    assert variations == {"1:1 single pulley"}


def test_importing_builds_the_record_chain():
    """A year of imported history with no personal bests behind it would be a
    dataset that cannot answer the question it exists for."""
    result = export.import_sessions(USER, _upper_body_payload())
    assert result["recordsRebuilt"] == 1
    standing = records.active_records(USER)
    assert standing, "imported work should establish baselines"
    assert any(r["exercise"] == "Bench Press" for r in standing)


def test_a_warmup_never_becomes_a_record_through_import():
    export.import_sessions(USER, _upper_body_payload())
    bench_records = [
        r for r in records.active_records(USER) if r["exercise"] == "Bench Press"
    ]
    heaviest = [r for r in bench_records if r["type"] == "heaviest_weight"]
    assert heaviest and heaviest[0]["value"] == 70.0


# --------------------------------------------------------------------------- #
# Duplicate safety
# --------------------------------------------------------------------------- #
def test_running_the_same_import_twice_changes_nothing():
    """The standard way a fitness-app migration silently doubles every total."""
    export.import_sessions(USER, _upper_body_payload())
    second = export.import_sessions(USER, _upper_body_payload())

    assert second["imported"] == 0
    assert second["duplicatesSkipped"] == 1
    with session_scope() as s:
        assert len(s.scalars(select(StrengthWorkout)).all()) == 1
        assert len(s.scalars(select(StrengthSetEntry)).all()) == 11


def test_a_session_without_an_import_id_is_skipped_and_reported():
    """Silently importing it would make the row impossible to deduplicate later."""
    payload = _upper_body_payload()
    payload["sessions"][0].pop("import_id")
    payload["sessions"][0].pop("session_id")
    result = export.import_sessions(USER, payload)
    assert result["imported"] == 0
    assert result["skipped"] == 1
    assert result["problems"]


def test_an_unknown_exercise_is_reported_not_invented():
    """Inventing an exercise to make the numbers land is how a catalogue fills
    with near-duplicates that split an exercise's history."""
    payload = _upper_body_payload()
    payload["sets"].append({
        "session_id": 1, "exercise_slug": "reverse-hyper-machine",
        "set_number": 1, "set_type": "working", "weight_kg": 50, "reps": 10,
    })
    result = export.import_sessions(USER, payload)
    assert result["imported"] == 1
    assert any("reverse-hyper-machine" in p for p in result["problems"])


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #
def test_an_export_can_be_imported_back():
    """The real test of whether the export preserved the raw data: put it back
    and see whether the same numbers come out."""
    export.import_sessions(USER, _upper_body_payload())
    before = reporting.volume_summary(reporting._load_sets(USER))

    backup = export.export_all(USER)
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

    # The export writes `import_id`; feed it straight back.
    restored = export.import_sessions(USER, backup, source="restore")
    assert restored["imported"] == 1

    after = reporting.volume_summary(reporting._load_sets(USER))
    assert after["volumeKg"] == before["volumeKg"]
    assert after["workingSets"] == before["workingSets"]
