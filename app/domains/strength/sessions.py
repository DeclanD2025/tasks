"""Session lifecycle: start, log, correct, finish, resume.

This is the module the gym floor actually touches, so its priorities are
different from the analytics layer's. It optimises for: never losing a set,
never duplicating one, and never blocking a log write on anything expensive.

Three mechanisms carry most of that weight:

**Idempotent writes.** ``log_set`` takes a ``client_key`` minted by the device.
A phone that loses signal mid-request and retries collides on the unique index
and gets the original set back, rather than silently writing a second one.

**Corrections, not deletions.** ``update_set`` appends the previous values to
``edit_history``; ``void_set`` retires a row without removing it. A mistyped
200 kg bench can be fixed without the fix being indistinguishable from the
mistake never happening.

**Snapshots at start.** Readiness and bodyweight are copied onto the session
when it begins. Apple Health revises sleep and HRV for a day afterwards, so
joining live would quietly rewrite the conditions a session was performed
under — and any correlation drawn from them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import (
    HealthMetricDaily,
    StrengthExercise,
    StrengthPlannedSession,
    StrengthSetEntry,
    StrengthTemplateExercise,
    StrengthWorkout,
    StrengthWorkoutExercise,
    StrengthWorkoutTemplate,
    utcnow,
)
from app.domains.strength import calc, catalog, muscles, records

log = get_logger(__name__)


class SessionError(ValueError):
    """A request that cannot be honoured — surfaced to the API as a 400."""


# --------------------------------------------------------------------------- #
# Readiness snapshot
# --------------------------------------------------------------------------- #
def _readiness_snapshot(s, user_id: int) -> dict:
    """What ORION knew about the operator's state when the session started.

    Records the reading *and* its age. A 3-day-old HRV is not the same claim as
    this morning's, and a correlation built on stale readings should be able to
    say so rather than treating them alike.
    """
    today = date.today()
    row = s.scalars(
        select(HealthMetricDaily)
        .where(HealthMetricDaily.user_id == user_id, HealthMetricDaily.day <= today)
        .order_by(HealthMetricDaily.day.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"available": False}
    extra = row.extra or {}
    return {
        "available": True,
        "day": row.day.isoformat(),
        "ageDays": (today - row.day).days,
        "sleepHours": round(row.sleep_minutes / 60.0, 2) if row.sleep_minutes else None,
        "hrvMs": row.hrv_ms,
        "restingHr": row.resting_hr,
        "weightKg": row.weight_kg,
        "vo2max": extra.get("vo2max"),
    }


def _latest_bodyweight(s, user_id: int) -> float | None:
    row = s.scalars(
        select(HealthMetricDaily)
        .where(HealthMetricDaily.user_id == user_id, HealthMetricDaily.weight_kg.isnot(None))
        .order_by(HealthMetricDaily.day.desc())
        .limit(1)
    ).first()
    return row.weight_kg if row else None


# --------------------------------------------------------------------------- #
# Starting a session
# --------------------------------------------------------------------------- #
def _prescription_from_template_item(item: StrengthTemplateExercise) -> dict:
    return {
        "targetSets": item.target_sets,
        "targetReps": item.target_reps,
        "repMin": item.rep_min,
        "repMax": item.rep_max,
        "targetWeightKg": item.target_weight_kg,
        "targetRpe": item.target_rpe,
        "targetRir": item.target_rir,
        "restSeconds": item.rest_seconds,
        "tempo": item.tempo,
        "progressionRule": item.progression_rule,
        "progressionConfig": item.progression_config or {},
        "notes": item.notes,
    }


def _classification_snapshot(exercise: StrengthExercise) -> dict:
    """Freeze how the exercise was classified today.

    Reclassifying an exercise later (deciding RDLs are hinge-primary rather
    than hamstring-primary) would otherwise silently restate years of
    muscle-group volume. Both readings stay available afterwards.
    """
    return {
        "primaryMuscle": exercise.primary_muscle,
        "secondaryMuscles": list(exercise.secondary_muscles or []),
        "muscleAttribution": muscles.attribution_for(
            exercise.slug, exercise.primary_muscle
        ),
        "movementPattern": exercise.movement_pattern,
        "familySlug": exercise.family_slug,
        "loadType": exercise.load_type,
        "isCompound": bool(exercise.is_compound),
        "capturedAt": utcnow().isoformat(),
    }


def start_session(
    user_id: int,
    *,
    template_id: int | None = None,
    planned_session_id: int | None = None,
    name: str = "",
    location: str = "",
) -> int:
    """Begin a session. Returns the workout id.

    Refuses to start a second concurrent session — an operator with two live
    sessions has lost track of which one their sets are landing in, and the
    resume flow exists precisely so they do not need a second.
    """
    with session_scope() as s:
        existing = s.scalars(
            select(StrengthWorkout).where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "active",
            )
        ).first()
        if existing is not None:
            raise SessionError(
                f"A session is already in progress (started {existing.started_at:%H:%M}). "
                "Finish or discard it first."
            )

        planned: StrengthPlannedSession | None = None
        if planned_session_id is not None:
            planned = s.get(StrengthPlannedSession, planned_session_id)
            if planned is None or planned.user_id != user_id:
                raise SessionError("That planned session does not exist.")
            template_id = template_id or planned.template_id

        template: StrengthWorkoutTemplate | None = None
        if template_id is not None:
            template = s.get(StrengthWorkoutTemplate, template_id)
            if template is None:
                raise SessionError("That template does not exist.")

        title = name or (planned.name if planned else "") or (
            template.name if template else "Strength Workout"
        )
        workout = StrengthWorkout(
            user_id=user_id,
            template_id=template_id,
            planned_session_id=planned_session_id,
            programme_id=planned.programme_id if planned else None,
            name=title,
            status="active",
            location=location,
            bodyweight_kg=_latest_bodyweight(s, user_id),
            readiness_snapshot=_readiness_snapshot(s, user_id),
            started_at=utcnow(),
        )
        s.add(workout)
        s.flush()

        if template is not None:
            items = s.scalars(
                select(StrengthTemplateExercise)
                .where(StrengthTemplateExercise.template_id == template.id)
                .order_by(StrengthTemplateExercise.sort_order)
            ).all()
            for order, item in enumerate(items, start=1):
                exercise = s.get(StrengthExercise, item.exercise_id)
                if exercise is None:
                    continue
                s.add(
                    StrengthWorkoutExercise(
                        workout_id=workout.id,
                        exercise_id=item.exercise_id,
                        sort_order=order,
                        section=item.section,
                        superset_group=item.superset_group,
                        target_sets=item.target_sets,
                        target_reps=item.target_reps,
                        prescription=_prescription_from_template_item(item),
                        classification_snapshot=_classification_snapshot(exercise),
                    )
                )

        if planned is not None:
            planned.status = "active"
        return workout.id


def add_exercise(
    user_id: int,
    workout_id: int,
    exercise_id: int,
    *,
    substituted_from_id: int | None = None,
    substitution_reason: str = "",
) -> int:
    """Add an exercise to a live session, optionally as a substitution.

    The substitution keeps its reason. "Squat rack was busy" and "knee hurt"
    imply completely different follow-ups, and a bare swap loses that.
    """
    with session_scope() as s:
        workout = _owned_workout(s, user_id, workout_id)
        exercise = s.get(StrengthExercise, exercise_id)
        if exercise is None:
            raise SessionError("That exercise does not exist.")
        highest = s.scalars(
            select(StrengthWorkoutExercise.sort_order)
            .where(StrengthWorkoutExercise.workout_id == workout.id)
            .order_by(StrengthWorkoutExercise.sort_order.desc())
            .limit(1)
        ).first()
        row = StrengthWorkoutExercise(
            workout_id=workout.id,
            exercise_id=exercise_id,
            sort_order=(highest or 0) + 1,
            target_sets=exercise.default_sets,
            target_reps=exercise.default_reps,
            substituted_from_id=substituted_from_id,
            substitution_reason=substitution_reason,
            classification_snapshot=_classification_snapshot(exercise),
        )
        s.add(row)
        s.flush()
        return row.id


def substitute_exercise(
    user_id: int, workout_exercise_id: int, new_exercise_id: int, *, reason: str = ""
) -> None:
    """Swap an exercise in place, keeping its position and prescription.

    Any sets already logged against the original stay with it — they really
    happened. Substituting mid-exercise is therefore refused rather than
    silently re-labelling completed work as a different movement.
    """
    with session_scope() as s:
        block = s.get(StrengthWorkoutExercise, workout_exercise_id)
        if block is None:
            raise SessionError("That exercise block does not exist.")
        _owned_workout(s, user_id, block.workout_id)
        logged = s.scalars(
            select(StrengthSetEntry).where(
                StrengthSetEntry.workout_exercise_id == block.id,
                StrengthSetEntry.completed.is_(True),
                StrengthSetEntry.voided_at.is_(None),
            )
        ).first()
        if logged is not None:
            raise SessionError(
                "Sets are already logged against this exercise. Add the "
                "replacement as a new exercise instead so both are recorded."
            )
        new_exercise = s.get(StrengthExercise, new_exercise_id)
        if new_exercise is None:
            raise SessionError("That exercise does not exist.")
        block.substituted_from_id = block.exercise_id
        block.substitution_reason = reason
        block.exercise_id = new_exercise_id
        block.classification_snapshot = _classification_snapshot(new_exercise)


# --------------------------------------------------------------------------- #
# Logging sets
# --------------------------------------------------------------------------- #
def log_set(
    user_id: int,
    workout_exercise_id: int,
    *,
    client_key: str | None = None,
    weight_kg: float | None = None,
    reps: int | None = None,
    set_type: str = "working",
    rpe: float | None = None,
    rir: float | None = None,
    duration_seconds: float | None = None,
    distance_m: float | None = None,
    assistance_kg: float | None = None,
    left_reps: int | None = None,
    right_reps: int | None = None,
    rest_seconds: float | None = None,
    to_failure: bool = False,
    has_partials: bool = False,
    notes: str = "",
    unit: str = "kg",
) -> dict:
    """Record one completed set. Idempotent on ``client_key``.

    Returns the stored set. A retry with the same key returns the original
    rather than writing a duplicate, so a flaky gym connection costs a round
    trip and nothing else.
    """
    with session_scope() as s:
        if client_key:
            existing = s.scalars(
                select(StrengthSetEntry).where(StrengthSetEntry.client_key == client_key)
            ).first()
            if existing is not None:
                return _set_dict(existing)

        block = s.get(StrengthWorkoutExercise, workout_exercise_id)
        if block is None:
            raise SessionError("That exercise block does not exist.")
        workout = _owned_workout(s, user_id, block.workout_id)
        exercise = s.get(StrengthExercise, block.exercise_id)

        highest = s.scalars(
            select(StrengthSetEntry.set_number)
            .where(StrengthSetEntry.workout_exercise_id == block.id)
            .order_by(StrengthSetEntry.set_number.desc())
            .limit(1)
        ).first()

        weight = calc.to_kg(weight_kg, unit) if weight_kg is not None else None
        entry = StrengthSetEntry(
            workout_exercise_id=block.id,
            set_number=(highest or 0) + 1,
            set_type=calc.normalise_set_type(set_type),
            weight_kg=weight,
            reps=reps,
            duration_seconds=duration_seconds,
            distance_m=distance_m,
            assistance_kg=assistance_kg,
            left_reps=left_reps,
            right_reps=right_reps,
            rpe=rpe,
            rir=rir if rir is not None else calc.rpe_to_rir(rpe),
            rest_seconds=rest_seconds,
            to_failure=to_failure,
            has_partials=has_partials,
            notes=notes,
            # Bodyweight is copied per set, not read at analysis time: a lifter
            # who gains 5 kg over a year must not have last year's push-up
            # volume silently restated upward.
            bodyweight_kg=workout.bodyweight_kg,
            bodyweight_factor=catalog.bodyweight_factor_for(exercise) if exercise else None,
            client_key=client_key,
            completed=True,
            completed_at=utcnow(),
        )
        s.add(entry)
        s.flush()
        return _set_dict(entry)


def update_set(user_id: int, set_id: int, **changes) -> dict:
    """Correct a set, keeping what it said before.

    The prior values go onto ``edit_history`` rather than being overwritten, so
    a correction is auditable and a suspiciously-edited PR can be examined.
    """
    allowed = {
        "weight_kg", "reps", "set_type", "rpe", "rir", "duration_seconds",
        "distance_m", "assistance_kg", "left_reps", "right_reps",
        "rest_seconds", "to_failure", "has_partials", "notes", "completed",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise SessionError(f"Cannot update: {', '.join(sorted(unknown))}")

    with session_scope() as s:
        entry = s.get(StrengthSetEntry, set_id)
        if entry is None:
            raise SessionError("That set does not exist.")
        block = s.get(StrengthWorkoutExercise, entry.workout_exercise_id)
        workout = _owned_workout(s, user_id, block.workout_id, require_active=False)

        before = {k: getattr(entry, k) for k in changes if hasattr(entry, k)}
        if before:
            history = list(entry.edit_history or [])
            history.append({"at": utcnow().isoformat(), "was": _jsonable(before)})
            entry.edit_history = history

        for key, value in changes.items():
            if key == "set_type":
                value = calc.normalise_set_type(value)
            setattr(entry, key, value)
        if "rpe" in changes and "rir" not in changes:
            entry.rir = calc.rpe_to_rir(entry.rpe)
        s.flush()
        result = _set_dict(entry)
        exercise_id = block.exercise_id
        completed = workout.status in ("completed", "partial", "abandoned")

    # Records are derived from sets, so a correction has to rebuild them or the
    # old value stands as a permanent PR.
    if completed:
        records.rebuild_records_for_exercise(user_id, exercise_id)
    return result


def void_set(user_id: int, set_id: int, *, reason: str = "") -> None:
    """Retire a set without deleting it.

    A set that never happened and a set entered wrongly are different facts.
    Voiding keeps the row readable and out of every statistic.
    """
    with session_scope() as s:
        entry = s.get(StrengthSetEntry, set_id)
        if entry is None:
            raise SessionError("That set does not exist.")
        block = s.get(StrengthWorkoutExercise, entry.workout_exercise_id)
        workout = _owned_workout(s, user_id, block.workout_id, require_active=False)
        entry.voided_at = utcnow()
        entry.void_reason = reason
        exercise_id = block.exercise_id
        completed = workout.status in ("completed", "partial", "abandoned")

    if completed:
        records.rebuild_records_for_exercise(user_id, exercise_id)


# --------------------------------------------------------------------------- #
# Finishing
# --------------------------------------------------------------------------- #
def finish_session(
    user_id: int,
    workout_id: int,
    *,
    notes: str = "",
    session_rpe: float | None = None,
    pain_notes: str = "",
) -> dict:
    """Complete a session and return its summary.

    Status reflects what was actually done against what was planned:
    ``completed`` when every prescribed exercise saw work, ``partial`` when
    some did not, ``abandoned`` when none did. Collapsing these into one
    "done" would make adherence unanswerable.
    """
    with session_scope() as s:
        workout = _owned_workout(s, user_id, workout_id, require_active=False)
        blocks = s.scalars(
            select(StrengthWorkoutExercise).where(
                StrengthWorkoutExercise.workout_id == workout_id
            )
        ).all()
        worked = 0
        for block in blocks:
            has_set = s.scalars(
                select(StrengthSetEntry).where(
                    StrengthSetEntry.workout_exercise_id == block.id,
                    StrengthSetEntry.completed.is_(True),
                    StrengthSetEntry.voided_at.is_(None),
                )
            ).first()
            if has_set is not None:
                worked += 1

        if worked == 0:
            workout.status = "abandoned"
            workout.abandoned_reason = workout.abandoned_reason or "no sets logged"
        elif worked < len(blocks):
            workout.status = "partial"
        else:
            workout.status = "completed"

        workout.finished_at = utcnow()
        workout.notes = notes or workout.notes
        workout.session_rpe = session_rpe
        workout.pain_notes = pain_notes or workout.pain_notes

        if workout.planned_session_id:
            planned = s.get(StrengthPlannedSession, workout.planned_session_id)
            if planned is not None:
                planned.status = workout.status
        status = workout.status

    new_records = records.rebuild_records_for_workout(user_id, workout_id)
    summary = session_summary(user_id, workout_id)
    summary["status"] = status
    summary["newRecords"] = new_records
    return summary


def abandon_session(user_id: int, workout_id: int, *, reason: str = "") -> None:
    with session_scope() as s:
        workout = _owned_workout(s, user_id, workout_id, require_active=False)
        workout.status = "abandoned"
        workout.abandoned_reason = reason
        workout.finished_at = utcnow()


def discard_session(user_id: int, workout_id: int) -> None:
    """Delete a session outright.

    The one place deletion is allowed, and only for a session with no completed
    sets — a mis-tap on "start". Anything with work in it must be abandoned
    instead, so the record of having shown up survives.
    """
    with session_scope() as s:
        workout = _owned_workout(s, user_id, workout_id, require_active=False)
        blocks = s.scalars(
            select(StrengthWorkoutExercise).where(
                StrengthWorkoutExercise.workout_id == workout_id
            )
        ).all()
        for block in blocks:
            entries = s.scalars(
                select(StrengthSetEntry).where(
                    StrengthSetEntry.workout_exercise_id == block.id,
                    StrengthSetEntry.completed.is_(True),
                )
            ).all()
            if entries:
                raise SessionError(
                    "This session has logged sets. Abandon it instead — the "
                    "work happened, even if the session did not finish."
                )
            s.delete(block)
        # Flush the child deletes before removing the parent; without this
        # SQLAlchemy is free to order the workout delete first and trip the FK.
        s.flush()
        s.delete(workout)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def active_session(user_id: int) -> dict | None:
    """The session in progress, if any. Backs resume-after-crash."""
    with session_scope() as s:
        workout = s.scalars(
            select(StrengthWorkout).where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status == "active",
            )
        ).first()
        if workout is None:
            return None
        workout_id = workout.id
    return session_detail(user_id, workout_id)


def session_detail(user_id: int, workout_id: int) -> dict:
    """The full session, with each exercise's prescription and previous bests."""
    with session_scope() as s:
        workout = _owned_workout(s, user_id, workout_id, require_active=False)
        blocks = s.execute(
            select(StrengthWorkoutExercise, StrengthExercise)
            .join(StrengthExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .where(StrengthWorkoutExercise.workout_id == workout_id)
            .order_by(StrengthWorkoutExercise.sort_order)
        ).all()

        exercises = []
        for block, exercise in blocks:
            entries = s.scalars(
                select(StrengthSetEntry)
                .where(StrengthSetEntry.workout_exercise_id == block.id)
                .order_by(StrengthSetEntry.set_number)
            ).all()
            exercises.append(
                {
                    "id": block.id,
                    "exerciseId": exercise.id,
                    "name": exercise.display_name or exercise.name,
                    "equipment": exercise.equipment,
                    "primaryMuscle": exercise.primary_muscle,
                    "loadType": exercise.load_type,
                    "measurement": exercise.measurement,
                    "limbMultiplier": catalog.limb_multiplier_for(exercise),
                    "incrementKg": exercise.increment_kg,
                    "barWeightKg": exercise.bar_weight_kg,
                    "section": block.section,
                    "supersetGroup": block.superset_group,
                    "targetSets": block.target_sets,
                    "targetReps": block.target_reps,
                    "prescription": block.prescription or {},
                    "substitutedFrom": block.substituted_from_id,
                    "substitutionReason": block.substitution_reason,
                    "notes": block.notes,
                    "sets": [_set_dict(e) for e in entries if e.voided_at is None],
                    "voidedSets": [_set_dict(e) for e in entries if e.voided_at is not None],
                    "previous": _previous_performance(s, user_id, exercise.id, workout_id),
                }
            )

        elapsed = _elapsed_minutes(workout.started_at, workout.finished_at)
        return {
            "id": workout.id,
            "name": workout.name,
            "status": workout.status,
            "startedAt": workout.started_at.isoformat(),
            "finishedAt": workout.finished_at.isoformat() if workout.finished_at else None,
            "elapsedMinutes": round(elapsed, 1),
            "location": workout.location,
            "bodyweightKg": workout.bodyweight_kg,
            "readiness": workout.readiness_snapshot or {},
            "sessionRpe": workout.session_rpe,
            "notes": workout.notes,
            "painNotes": workout.pain_notes,
            "defaultRestSeconds": workout.default_rest_seconds,
            "exercises": exercises,
        }


def _previous_performance(s, user_id: int, exercise_id: int, exclude_workout_id: int) -> dict | None:
    """The last time this exercise was trained — the single most useful number
    to have on screen mid-set, because it is what today is being judged against."""
    row = s.execute(
        select(StrengthWorkout, StrengthWorkoutExercise)
        .join(
            StrengthWorkoutExercise,
            StrengthWorkoutExercise.workout_id == StrengthWorkout.id,
        )
        .where(
            StrengthWorkout.user_id == user_id,
            StrengthWorkoutExercise.exercise_id == exercise_id,
            StrengthWorkout.id != exclude_workout_id,
            StrengthWorkout.status.in_(("completed", "partial", "abandoned")),
        )
        .order_by(StrengthWorkout.started_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    workout, block = row
    entries = s.scalars(
        select(StrengthSetEntry)
        .where(
            StrengthSetEntry.workout_exercise_id == block.id,
            StrengthSetEntry.completed.is_(True),
            StrengthSetEntry.voided_at.is_(None),
        )
        .order_by(StrengthSetEntry.set_number)
    ).all()
    if not entries:
        return None
    return {
        "date": workout.started_at.date().isoformat(),
        "daysAgo": (date.today() - workout.started_at.date()).days,
        "sets": [
            {
                "weightKg": e.weight_kg,
                "reps": e.reps,
                "rpe": e.rpe,
                "setType": e.set_type,
            }
            for e in entries
            if calc.is_working_set(e.set_type)
        ],
    }


def session_summary(user_id: int, workout_id: int) -> dict:
    """Transparent post-session summary: what was done, and what it totalled."""
    detail = session_detail(user_id, workout_id)
    all_sets: list[calc.SetInput] = []
    per_exercise = []

    for block in detail["exercises"]:
        inputs = [
            calc.SetInput(
                weight_kg=s_["weightKg"],
                reps=s_["reps"],
                set_type=s_["setType"],
                load_type=catalog.resolve_load_type(
                    block["loadType"],
                    weight_kg=s_["weightKg"],
                    assistance_kg=s_["assistanceKg"],
                ),
                duration_seconds=s_["durationSeconds"],
                bodyweight_kg=detail["bodyweightKg"],
                assistance_kg=s_["assistanceKg"],
                rpe=s_["rpe"],
                rir=s_["rir"],
                to_failure=s_["toFailure"],
                left_reps=s_["leftReps"],
                right_reps=s_["rightReps"],
                limb_multiplier=block.get("limbMultiplier", 1.0),
            )
            for s_ in block["sets"]
        ]
        all_sets.extend(inputs)
        best = calc.best_e1rm(inputs)
        per_exercise.append(
            {
                "name": block["name"],
                "exerciseId": block["exerciseId"],
                "workingSets": calc.count_working_sets(inputs),
                "hardSets": calc.count_hard_sets(inputs),
                "volumeKg": round(calc.session_volume_kg(inputs), 1),
                "topSetKg": max((i.weight_kg or 0) for i in inputs) if inputs else None,
                "bestE1rmKg": best.value if best else None,
                "plannedSets": block["targetSets"],
            }
        )

    warnings = _data_quality_warnings(detail, all_sets)
    return {
        "id": detail["id"],
        "name": detail["name"],
        "status": detail["status"],
        "startedAt": detail["startedAt"],
        "durationMinutes": detail["elapsedMinutes"],
        "volumeKg": round(calc.session_volume_kg(all_sets), 1),
        "workingSets": calc.count_working_sets(all_sets),
        "hardSets": calc.count_hard_sets(all_sets),
        "totalReps": sum(calc.total_reps(i) for i in all_sets if calc.is_working_set(i.set_type)),
        "sessionRpe": detail["sessionRpe"],
        "sessionLoad": calc.session_rpe_load(detail["sessionRpe"], detail["elapsedMinutes"]),
        "readiness": detail["readiness"],
        "exercises": per_exercise,
        "dataQuality": warnings,
    }


def _data_quality_warnings(detail: dict, sets: list[calc.SetInput]) -> list[str]:
    """Say plainly where this session's data is thin.

    Better that the summary admits an unrated session than that the analytics
    quietly treat it as if effort had been recorded.
    """
    out: list[str] = []
    working = [s for s in sets if calc.is_working_set(s.set_type)]
    if working and not any(s.rpe is not None or s.rir is not None for s in working):
        out.append("No effort ratings recorded — hard-set count will read as zero.")
    if detail["sessionRpe"] is None:
        out.append("No session RPE — this session is excluded from internal-load trends.")
    if not detail["readiness"].get("available"):
        out.append("No readiness data for this date.")
    elif detail["readiness"].get("ageDays", 0) > 1:
        out.append(
            f"Readiness data is {detail['readiness']['ageDays']} days old."
        )
    return out


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _naive(value: datetime | None) -> datetime | None:
    """Drop the tzinfo so stored and fresh timestamps can be compared.

    ``models.utcnow`` is timezone-aware, but SQLite's DATETIME has nowhere to
    put an offset and hands the value back naive. Subtracting one from the
    other raises, so every duration in this module goes through here. Both
    sides are UTC — this discards a label, not information.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def _elapsed_minutes(started_at: datetime, finished_at: datetime | None) -> float:
    start = _naive(started_at)
    end = _naive(finished_at) or _naive(utcnow())
    return max(0.0, (end - start).total_seconds() / 60.0)


def _owned_workout(s, user_id: int, workout_id: int, *, require_active: bool = True) -> StrengthWorkout:
    workout = s.get(StrengthWorkout, workout_id)
    if workout is None or workout.user_id != user_id:
        raise SessionError("That session does not exist.")
    if require_active and workout.status != "active":
        raise SessionError("That session is not in progress.")
    return workout


def _set_dict(entry: StrengthSetEntry) -> dict:
    return {
        "id": entry.id,
        "setNumber": entry.set_number,
        "setType": entry.set_type,
        "weightKg": entry.weight_kg,
        "reps": entry.reps,
        "durationSeconds": entry.duration_seconds,
        "distanceM": entry.distance_m,
        "assistanceKg": entry.assistance_kg,
        "leftReps": entry.left_reps,
        "rightReps": entry.right_reps,
        "rpe": entry.rpe,
        "rir": entry.rir,
        "restSeconds": entry.rest_seconds,
        "toFailure": bool(entry.to_failure),
        "hasPartials": bool(entry.has_partials),
        "notes": entry.notes,
        "completed": bool(entry.completed),
        "completedAt": entry.completed_at.isoformat() if entry.completed_at else None,
        "voided": entry.voided_at is not None,
        "voidReason": entry.void_reason,
        "edited": bool(entry.edit_history),
    }


def _jsonable(values: dict) -> dict:
    out = {}
    for key, value in values.items():
        if isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out
