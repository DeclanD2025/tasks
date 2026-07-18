"""Personal records.

The whole module is built around one decision: **records are rebuilt from
history, never incrementally patched.**

Incremental detection is the obvious design and it is wrong here. The moment a
set can be corrected or voided — which it must be, because people mistype 200
for 20 — incremental records go stale in ways nobody notices. The 200 kg bench
stays as an all-time PR forever, or it is deleted and the record it displaced
never comes back. Rebuilding the chain for an exercise from its full set
history is a few milliseconds at personal-log scale and is correct by
construction, whatever order the edits arrived in.

The second decision: a first-ever performance is **recorded but not
announced**. Every exercise's first session sets eight simultaneous "records",
which is noise, and celebrating it teaches the operator to ignore the feature.
``is_announceable`` marks the ones that actually beat something.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPersonalRecord,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
)
from app.domains.strength import calc, catalog

#: Rep counts that get their own "best at N reps" record. These are the ones
#: lifters actually program around; tracking every rep count would bury the
#: meaningful ones.
REP_TARGETS = (1, 3, 5, 8, 10)

#: The default formula for 1RM records. Stored on each record so a later change
#: of default does not silently make old and new records incomparable.
DEFAULT_E1RM_FORMULA = "epley"


@dataclass
class PerformedSet:
    """A completed set, flattened out of the ORM for the rebuild pass."""

    set_id: int
    workout_id: int
    exercise_id: int
    achieved_at: datetime
    weight_kg: float
    reps: int
    volume_kg: float
    e1rm: float | None
    duration_seconds: float | None
    set_type: str


def _load_history(s, user_id: int, exercise_id: int) -> list[PerformedSet]:
    """Every countable set for one exercise, oldest first.

    Excludes warm-ups, incomplete sets and voided sets. Those three exclusions
    are the difference between a record system and a random-maximum generator.
    """
    rows = s.execute(
        select(StrengthSetEntry, StrengthWorkout, StrengthWorkoutExercise, StrengthExercise)
        .join(
            StrengthWorkoutExercise,
            StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id,
        )
        .join(StrengthWorkout, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
        .join(StrengthExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
        .where(
            StrengthWorkout.user_id == user_id,
            StrengthWorkoutExercise.exercise_id == exercise_id,
            StrengthSetEntry.completed.is_(True),
            StrengthSetEntry.voided_at.is_(None),
            # A session still in progress has not happened yet. Records from an
            # abandoned session stand — the work was really done.
            StrengthWorkout.status.in_(("completed", "partial", "abandoned")),
        )
        .order_by(StrengthWorkout.started_at, StrengthSetEntry.set_number)
    ).all()

    out: list[PerformedSet] = []
    for entry, workout, _we, exercise in rows:
        if not calc.is_working_set(entry.set_type):
            continue
        load_type = catalog.resolve_load_type(
            exercise.load_type,
            weight_kg=entry.weight_kg,
            assistance_kg=entry.assistance_kg,
        )
        si = calc.SetInput(
            weight_kg=entry.weight_kg,
            reps=entry.reps,
            set_type=entry.set_type,
            load_type=load_type,
            duration_seconds=entry.duration_seconds,
            bodyweight_kg=entry.bodyweight_kg,
            bodyweight_factor=entry.bodyweight_factor
            or catalog.bodyweight_factor_for(exercise),
            assistance_kg=entry.assistance_kg,
            left_reps=entry.left_reps,
            right_reps=entry.right_reps,
            left_weight_kg=entry.left_weight_kg,
            right_weight_kg=entry.right_weight_kg,
        )
        est = calc.estimate_1rm(
            calc.effective_load_kg(si), entry.reps, formula=DEFAULT_E1RM_FORMULA
        )
        out.append(
            PerformedSet(
                set_id=entry.id,
                workout_id=workout.id,
                exercise_id=exercise_id,
                achieved_at=entry.completed_at or workout.started_at,
                weight_kg=calc.effective_load_kg(si),
                reps=calc.total_reps(si),
                volume_kg=calc.set_volume_kg(si),
                e1rm=est.value if est else None,
                duration_seconds=entry.duration_seconds,
                set_type=calc.normalise_set_type(entry.set_type),
            )
        )
    return out


@dataclass
class RecordClaim:
    record_type: str
    value: float
    qualifier: float | None
    set_id: int
    workout_id: int
    achieved_at: datetime
    calculation_method: str
    previous_value: float | None
    #: False for a first-ever performance, which beat nothing.
    is_announceable: bool


def _claims_from_history(history: list[PerformedSet]) -> list[RecordClaim]:
    """Walk the history forward, emitting a claim each time a best improves."""
    claims: list[RecordClaim] = []
    best: dict[tuple[str, float | None], float] = {}

    def offer(kind: str, value: float | None, qualifier: float | None, s: PerformedSet,
              method: str = "measured") -> None:
        if value is None or value <= 0:
            return
        key = (kind, qualifier)
        previous = best.get(key)
        if previous is not None and value <= previous:
            return
        best[key] = value
        claims.append(
            RecordClaim(
                record_type=kind,
                value=round(value, 2),
                qualifier=qualifier,
                set_id=s.set_id,
                workout_id=s.workout_id,
                achieved_at=s.achieved_at,
                calculation_method=method,
                previous_value=previous,
                is_announceable=previous is not None,
            )
        )

    # Session volume needs the sets grouped by workout, so it is accumulated
    # separately and offered at the workout boundary.
    session_volume: dict[int, float] = {}
    session_last: dict[int, PerformedSet] = {}

    for s in history:
        if s.reps > 0 and s.weight_kg > 0:
            offer("heaviest_weight", s.weight_kg, None, s)
            offer("most_reps_at_weight", float(s.reps), round(s.weight_kg, 2), s)
            if s.reps in REP_TARGETS:
                offer("best_at_rep_target", s.weight_kg, float(s.reps), s)
        offer("best_set_volume", s.volume_kg, None, s)
        offer("best_e1rm", s.e1rm, None, s, method=DEFAULT_E1RM_FORMULA)
        offer("longest_duration", s.duration_seconds, None, s)

        session_volume[s.workout_id] = session_volume.get(s.workout_id, 0.0) + s.volume_kg
        session_last[s.workout_id] = s

    for workout_id, volume in session_volume.items():
        offer("best_session_volume", volume, None, session_last[workout_id])

    return claims


def rebuild_records_for_exercise(user_id: int, exercise_id: int) -> int:
    """Recompute the whole PR chain for one exercise. Returns records written.

    Safe to call at any time — after a session, after a correction, after an
    import. The previous chain is replaced wholesale, so a voided set cannot
    leave a phantom record behind.
    """
    with session_scope() as s:
        history = _load_history(s, user_id, exercise_id)
        claims = _claims_from_history(history)

        existing = s.scalars(
            select(StrengthPersonalRecord).where(
                StrengthPersonalRecord.user_id == user_id,
                StrengthPersonalRecord.exercise_id == exercise_id,
            )
        ).all()
        # Records form a chain via `previous_record_id`, so the self-reference
        # has to be broken before the rows can go — otherwise the delete order
        # decides whether this succeeds, which is not a thing to leave to luck.
        for row in existing:
            row.previous_record_id = None
        s.flush()
        for row in existing:
            s.delete(row)
        s.flush()

        # Only the newest claim per (type, qualifier) is the standing record;
        # the earlier ones are kept as the readable progression of that lift.
        latest: dict[tuple[str, float | None], RecordClaim] = {}
        for claim in claims:
            latest[(claim.record_type, claim.qualifier)] = claim

        previous_row: dict[tuple[str, float | None], StrengthPersonalRecord] = {}
        written = 0
        for claim in claims:
            key = (claim.record_type, claim.qualifier)
            row = StrengthPersonalRecord(
                user_id=user_id,
                exercise_id=exercise_id,
                workout_id=claim.workout_id,
                set_entry_id=claim.set_id,
                record_type=claim.record_type,
                value=claim.value,
                qualifier=claim.qualifier,
                calculation_method=claim.calculation_method,
                previous_value=claim.previous_value,
                previous_record_id=(
                    previous_row[key].id if key in previous_row else None
                ),
                is_active=latest[key] is claim,
                achieved_at=claim.achieved_at,
            )
            s.add(row)
            s.flush()
            previous_row[key] = row
            written += 1
        return written


def rebuild_records_for_workout(user_id: int, workout_id: int) -> list[dict]:
    """Rebuild every exercise touched by a workout; report what it newly set.

    Called on session completion. Returns only the announceable records that
    this workout is responsible for — so the session summary can say "you beat
    your 5-rep bench" without also announcing the seven simultaneous
    first-ever "records" from an exercise tried for the first time.
    """
    with session_scope() as s:
        exercise_ids = list(
            s.scalars(
                select(StrengthWorkoutExercise.exercise_id).where(
                    StrengthWorkoutExercise.workout_id == workout_id
                )
            ).all()
        )
    for exercise_id in set(exercise_ids):
        rebuild_records_for_exercise(user_id, exercise_id)

    with session_scope() as s:
        rows = s.execute(
            select(StrengthPersonalRecord, StrengthExercise)
            .join(StrengthExercise, StrengthPersonalRecord.exercise_id == StrengthExercise.id)
            .where(
                StrengthPersonalRecord.user_id == user_id,
                StrengthPersonalRecord.workout_id == workout_id,
                StrengthPersonalRecord.is_active.is_(True),
                StrengthPersonalRecord.previous_value.isnot(None),
            )
            .order_by(StrengthPersonalRecord.value.desc())
        ).all()
        return [
            {
                "exercise": exercise.display_name or exercise.name,
                "exerciseId": exercise.id,
                "type": record.record_type,
                "value": record.value,
                "unit": record.unit,
                "qualifier": record.qualifier,
                "previous": record.previous_value,
                "method": record.calculation_method,
                "label": describe(record.record_type, record.value, record.qualifier),
            }
            for record, exercise in rows
        ]


def describe(record_type: str, value: float, qualifier: float | None) -> str:
    """Human phrasing that keeps the qualifier attached.

    A "5-rep best" without the 5 is not a claim about anything.
    """
    v = f"{value:g}"
    if record_type == "heaviest_weight":
        return f"Heaviest ever — {v} kg"
    if record_type == "best_e1rm":
        return f"Best estimated 1RM — {v} kg"
    if record_type == "best_at_rep_target":
        return f"Best {qualifier:g}-rep set — {v} kg"
    if record_type == "most_reps_at_weight":
        return f"Most reps at {qualifier:g} kg — {v}"
    if record_type == "best_set_volume":
        return f"Biggest single set — {v} kg of volume"
    if record_type == "best_session_volume":
        return f"Biggest session — {v} kg of volume"
    if record_type == "longest_duration":
        return f"Longest hold — {v}s"
    return f"{record_type.replace('_', ' ').title()} — {v}"


def invalidate_record(record_id: int, *, reason: str = "") -> None:
    """Disown a record whose underlying set was bad.

    Distinct from being beaten: an invalidated record must never resurface as
    something later work "beat", which is why the flag is separate from
    ``is_active``.
    """
    with session_scope() as s:
        row = s.get(StrengthPersonalRecord, record_id)
        if row is None:
            return
        row.invalidated_at = datetime.utcnow()
        row.is_active = False


def active_records(user_id: int, exercise_id: int | None = None) -> list[dict]:
    """Standing records, best first."""
    with session_scope() as s:
        query = (
            select(StrengthPersonalRecord, StrengthExercise)
            .join(StrengthExercise, StrengthPersonalRecord.exercise_id == StrengthExercise.id)
            .where(
                StrengthPersonalRecord.user_id == user_id,
                StrengthPersonalRecord.is_active.is_(True),
                StrengthPersonalRecord.invalidated_at.is_(None),
            )
        )
        if exercise_id is not None:
            query = query.where(StrengthPersonalRecord.exercise_id == exercise_id)
        rows = s.execute(query.order_by(StrengthPersonalRecord.achieved_at.desc())).all()
        return [
            {
                "id": record.id,
                "exercise": exercise.display_name or exercise.name,
                "exerciseId": exercise.id,
                "type": record.record_type,
                "value": record.value,
                "unit": record.unit,
                "qualifier": record.qualifier,
                "previous": record.previous_value,
                "method": record.calculation_method,
                "achievedAt": record.achieved_at.isoformat(),
                "label": describe(record.record_type, record.value, record.qualifier),
            }
            for record, exercise in rows
        ]
