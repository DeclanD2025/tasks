"""Export and import.

Export exists so the operator's training data is theirs and not hostage to
ORION continuing to run. It is therefore deliberately boring: flat rows, real
column names, no ORION-specific encoding, and every derived figure recomputed
rather than referenced so a CSV is analysable on its own in a spreadsheet.

The set-level CSV is the important one. It is one row per set with everything
needed to redo any calculation in this package from scratch — which is also the
honest test of whether the raw data was really preserved, rather than only the
summaries ORION happens to compute today.

Export is always an explicit user action. Nothing here runs on a schedule or
pushes anywhere; personal health data leaves the system only when asked.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPersonalRecord,
    StrengthPlannedSession,
    StrengthProgramme,
    StrengthSetEntry,
    StrengthWorkout,
    StrengthWorkoutExercise,
    StrengthWorkoutTemplate,
)
from app.domains.strength import calc, catalog

EXPORT_VERSION = 1
TABLES = ("sets", "sessions", "exercises", "records", "programmes")


def _iso(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return "" if value is None else str(value)


# --------------------------------------------------------------------------- #
# Row builders
# --------------------------------------------------------------------------- #
def set_rows(user_id: int) -> list[dict]:
    """One row per set, with the raw inputs *and* the derived figures.

    Both, deliberately. The raw columns mean any future analysis can start from
    scratch; the derived ones mean a spreadsheet user does not have to
    reimplement bodyweight-load resolution to get a volume total.
    """
    with session_scope() as s:
        rows = s.execute(
            select(StrengthSetEntry, StrengthWorkoutExercise, StrengthWorkout, StrengthExercise)
            .join(
                StrengthWorkoutExercise,
                StrengthSetEntry.workout_exercise_id == StrengthWorkoutExercise.id,
            )
            .join(StrengthWorkout, StrengthWorkoutExercise.workout_id == StrengthWorkout.id)
            .join(StrengthExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .where(StrengthWorkout.user_id == user_id)
            .order_by(StrengthWorkout.started_at, StrengthSetEntry.set_number)
        ).all()

        out = []
        for entry, block, workout, exercise in rows:
            load_type = catalog.resolve_load_type(
                exercise.load_type,
                weight_kg=entry.weight_kg,
                assistance_kg=entry.assistance_kg,
            )
            si = calc.SetInput(
                weight_kg=entry.weight_kg, reps=entry.reps, set_type=entry.set_type,
                load_type=load_type, duration_seconds=entry.duration_seconds,
                bodyweight_kg=entry.bodyweight_kg,
                bodyweight_factor=entry.bodyweight_factor,
                assistance_kg=entry.assistance_kg, rpe=entry.rpe, rir=entry.rir,
                to_failure=bool(entry.to_failure),
                left_reps=entry.left_reps, right_reps=entry.right_reps,
            )
            est = calc.estimate_1rm(calc.effective_load_kg(si), entry.reps)
            out.append({
                "set_id": entry.id,
                "session_id": workout.id,
                "session_name": workout.name,
                "session_status": workout.status,
                "date": _iso(workout.started_at.date()),
                "started_at": _iso(workout.started_at),
                "exercise_id": exercise.id,
                "exercise": exercise.display_name or exercise.name,
                "exercise_slug": exercise.slug,
                "family": exercise.family_slug,
                "movement_pattern": exercise.movement_pattern,
                "primary_muscle": exercise.primary_muscle,
                "secondary_muscles": "|".join(exercise.secondary_muscles or []),
                "equipment": exercise.equipment,
                "set_number": entry.set_number,
                "set_type": calc.normalise_set_type(entry.set_type),
                "is_working_set": calc.is_working_set(entry.set_type),
                "weight_kg": entry.weight_kg,
                "reps": entry.reps,
                "left_reps": entry.left_reps,
                "right_reps": entry.right_reps,
                "duration_seconds": entry.duration_seconds,
                "distance_m": entry.distance_m,
                "rpe": entry.rpe,
                "rir": entry.rir,
                "to_failure": bool(entry.to_failure),
                "tempo": entry.tempo,
                "rest_seconds": entry.rest_seconds,
                "load_type": load_type,
                "bodyweight_kg": entry.bodyweight_kg,
                "bodyweight_factor": entry.bodyweight_factor,
                "assistance_kg": entry.assistance_kg,
                # Derived — recomputed here, never read from a cache.
                "effective_load_kg": round(calc.effective_load_kg(si), 2),
                "volume_kg": round(calc.set_volume_kg(si), 2),
                "estimated_1rm_kg": est.value if est else None,
                "estimated_1rm_formula": est.formula if est else "",
                "estimated_1rm_valid": bool(est),
                "is_hard_set": calc.is_hard_set(
                    entry.set_type, rpe=entry.rpe, rir=entry.rir,
                    to_failure=bool(entry.to_failure),
                ),
                # Provenance — an importer needs these to avoid duplicating.
                "source": entry.source,
                "client_key": entry.client_key or "",
                "voided": entry.voided_at is not None,
                "void_reason": entry.void_reason,
                "edited": bool(entry.edit_history),
                "notes": entry.notes,
            })
        return out


def session_rows(user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(StrengthWorkout)
            .where(StrengthWorkout.user_id == user_id)
            .order_by(StrengthWorkout.started_at)
        ).all()
        return [
            {
                "session_id": w.id,
                "name": w.name,
                "status": w.status,
                "started_at": _iso(w.started_at),
                "finished_at": _iso(w.finished_at),
                "location": w.location,
                "bodyweight_kg": w.bodyweight_kg,
                "session_rpe": w.session_rpe,
                "programme_id": w.programme_id,
                "planned_session_id": w.planned_session_id,
                "template_id": w.template_id,
                "source": w.source,
                "import_id": w.import_id or "",
                "sleep_hours": (w.readiness_snapshot or {}).get("sleepHours"),
                "hrv_ms": (w.readiness_snapshot or {}).get("hrvMs"),
                "resting_hr": (w.readiness_snapshot or {}).get("restingHr"),
                "readiness_age_days": (w.readiness_snapshot or {}).get("ageDays"),
                "notes": w.notes,
                "pain_notes": w.pain_notes,
                "abandoned_reason": w.abandoned_reason,
            }
            for w in rows
        ]


def exercise_rows(_user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(StrengthExercise).order_by(StrengthExercise.name)).all()
        return [
            {
                "exercise_id": ex.id,
                "slug": ex.slug,
                "name": ex.name,
                "display_name": ex.display_name,
                "aliases": "|".join(str(a) for a in (ex.aliases or [])),
                "family": ex.family_slug,
                "primary_muscle": ex.primary_muscle,
                "secondary_muscles": "|".join(ex.secondary_muscles or []),
                "equipment": ex.equipment,
                "movement_pattern": ex.movement_pattern,
                "load_type": ex.load_type,
                "measurement": ex.measurement,
                "laterality": ex.laterality,
                "is_compound": bool(ex.is_compound),
                "increment_kg": ex.increment_kg,
                "bar_weight_kg": ex.bar_weight_kg,
                "is_custom": bool(ex.is_custom),
                "archived": ex.archived_at is not None,
            }
            for ex in rows
        ]


def record_rows(user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(StrengthPersonalRecord, StrengthExercise)
            .join(StrengthExercise, StrengthPersonalRecord.exercise_id == StrengthExercise.id)
            .where(StrengthPersonalRecord.user_id == user_id)
            .order_by(StrengthPersonalRecord.achieved_at)
        ).all()
        return [
            {
                "record_id": r.id,
                "exercise": ex.display_name or ex.name,
                "exercise_id": ex.id,
                "record_type": r.record_type,
                "value": r.value,
                "unit": r.unit,
                "qualifier": r.qualifier,
                "calculation_method": r.calculation_method,
                "previous_value": r.previous_value,
                "achieved_at": _iso(r.achieved_at),
                "session_id": r.workout_id,
                "set_id": r.set_entry_id,
                "is_active": bool(r.is_active),
                "invalidated": r.invalidated_at is not None,
            }
            for r, ex in rows
        ]


def programme_rows(user_id: int) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(StrengthProgramme).where(StrengthProgramme.user_id == user_id)
        ).all()
        return [
            {
                "programme_id": p.id, "name": p.name, "goal": p.goal,
                "weeks": p.weeks, "days_per_week": p.days_per_week,
                "status": p.status, "version": p.version,
                "start_date": _iso(p.start_date), "end_date": _iso(p.end_date),
                "description": p.description, "notes": p.notes,
            }
            for p in rows
        ]


_BUILDERS = {
    "sets": set_rows,
    "sessions": session_rows,
    "exercises": exercise_rows,
    "records": record_rows,
    "programmes": programme_rows,
}


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #
def export_csv(user_id: int, *, table: str = "sets") -> str:
    if table not in _BUILDERS:
        raise ValueError(f"Unknown table {table!r}. Choose one of: {', '.join(TABLES)}.")
    rows = _BUILDERS[table](user_id)
    if not rows:
        # Headers still go out on an empty export: a file with column names and
        # no rows is unambiguous, whereas an empty file could be a failure.
        sample = _EMPTY_HEADERS.get(table, [])
        buffer = io.StringIO()
        csv.writer(buffer).writerow(sample)
        return buffer.getvalue()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


#: Column names for an empty export, so the shape is still self-describing.
_EMPTY_HEADERS = {
    "sets": [
        "set_id", "session_id", "date", "exercise", "set_number", "set_type",
        "weight_kg", "reps", "rpe", "volume_kg", "estimated_1rm_kg",
    ],
    "sessions": ["session_id", "name", "status", "started_at", "finished_at"],
    "exercises": ["exercise_id", "slug", "name", "family", "primary_muscle"],
    "records": ["record_id", "exercise", "record_type", "value", "achieved_at"],
    "programmes": ["programme_id", "name", "goal", "weeks", "status"],
}


def export_all(user_id: int) -> dict:
    """Full JSON backup — every table, plus the conventions needed to read it.

    The ``conventions`` block matters as much as the rows: a volume figure is
    meaningless without knowing warm-ups were excluded, and an e1RM without its
    formula and rep cap cannot be compared with anything.
    """
    return {
        "version": EXPORT_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "conventions": {
            "units": "All loads in kilograms.",
            "volume": "Load × reps, working sets only. Warm-ups and technique sets excluded.",
            "workingSetTypes": sorted(calc.WORKING_SET_TYPES),
            "hardSet": "A working set at RPE ≥ 7, RIR ≤ 3, or taken to failure.",
            "e1rmFormula": "epley",
            "e1rmRepLimit": calc.MAX_VALID_E1RM_REPS,
            "muscleWeighting": calc.MuscleWeighting().as_dict(),
            "bodyweightFactorDefault": calc.DEFAULT_BODYWEIGHT_FACTOR,
            "voidedSets": "Included with voided=true. Excluded from all statistics.",
        },
        "exercises": exercise_rows(user_id),
        "sessions": session_rows(user_id),
        "sets": set_rows(user_id),
        "records": record_rows(user_id),
        "programmes": programme_rows(user_id),
    }


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def import_sessions(user_id: int, payload: dict, *, source: str = "import") -> dict:
    """Bring sessions in from an export or another app.

    Duplicate-safe by ``import_id``: re-running the same import updates nothing
    and creates nothing. That matters because the common failure mode with
    fitness-app migrations is running the import twice and silently doubling
    every historical total.

    Deliberately conservative — it matches exercises by slug and skips rows it
    cannot place, reporting them, rather than inventing exercises to make the
    numbers land.
    """
    sessions_in = payload.get("sessions") or []
    sets_in = payload.get("sets") or []
    by_session: dict = {}
    for row in sets_in:
        by_session.setdefault(row.get("session_id"), []).append(row)

    imported = skipped = duplicates = 0
    problems: list[str] = []

    with session_scope() as s:
        known = {ex.slug: ex for ex in s.scalars(select(StrengthExercise)).all()}

        for row in sessions_in:
            import_id = str(row.get("import_id") or row.get("session_id") or "")
            if not import_id:
                skipped += 1
                problems.append("A session had no import_id and was skipped.")
                continue

            existing = s.scalars(
                select(StrengthWorkout).where(
                    StrengthWorkout.user_id == user_id,
                    StrengthWorkout.import_id == import_id,
                )
            ).first()
            if existing is not None:
                duplicates += 1
                continue

            started = row.get("started_at")
            workout = StrengthWorkout(
                user_id=user_id,
                name=row.get("name") or "Imported session",
                status=row.get("status") or "completed",
                started_at=datetime.fromisoformat(started) if started else datetime.utcnow(),
                finished_at=(
                    datetime.fromisoformat(row["finished_at"])
                    if row.get("finished_at") else None
                ),
                bodyweight_kg=row.get("bodyweight_kg"),
                session_rpe=row.get("session_rpe"),
                notes=row.get("notes") or "",
                source=source,
                import_id=import_id,
            )
            s.add(workout)
            s.flush()

            blocks: dict[str, int] = {}
            for set_row in by_session.get(row.get("session_id"), []):
                slug = set_row.get("exercise_slug") or ""
                exercise = known.get(slug)
                if exercise is None:
                    problems.append(f"Unknown exercise {slug!r} — its sets were skipped.")
                    continue
                if slug not in blocks:
                    block = StrengthWorkoutExercise(
                        workout_id=workout.id,
                        exercise_id=exercise.id,
                        sort_order=len(blocks) + 1,
                    )
                    s.add(block)
                    s.flush()
                    blocks[slug] = block.id
                s.add(
                    StrengthSetEntry(
                        workout_exercise_id=blocks[slug],
                        set_number=int(set_row.get("set_number") or 1),
                        set_type=calc.normalise_set_type(set_row.get("set_type")),
                        weight_kg=set_row.get("weight_kg"),
                        reps=set_row.get("reps"),
                        rpe=set_row.get("rpe"),
                        rir=set_row.get("rir"),
                        duration_seconds=set_row.get("duration_seconds"),
                        notes=set_row.get("notes") or "",
                        bodyweight_kg=set_row.get("bodyweight_kg"),
                        source=source,
                        completed=True,
                        completed_at=workout.started_at,
                    )
                )
            imported += 1

    return {
        "imported": imported,
        "duplicatesSkipped": duplicates,
        "skipped": skipped,
        "problems": sorted(set(problems)),
    }
