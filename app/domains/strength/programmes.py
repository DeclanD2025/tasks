"""Programmes, templates, scheduling and the training-home payload.

The planning side of the system. Its one non-obvious responsibility is
generating progression proposals after a session: the engine in
``progression`` is pure and knows nothing about the database, so somebody has
to load what was actually done, hand it over, and record the result. That is
here, kept out of ``sessions`` so that finishing a workout never blocks on
analysis.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    StrengthExercise,
    StrengthPlannedSession,
    StrengthProgramme,
    StrengthProgrammeDay,
    StrengthSetEntry,
    StrengthTemplateExercise,
    StrengthWorkout,
    StrengthWorkoutExercise,
    StrengthWorkoutTemplate,
    Workout,
    utcnow,
)
from app.domains.strength import calc, progression, records, reporting


class ProgrammeError(ValueError):
    """A planning request that cannot be honoured."""


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
def list_exercises(
    *, q: str = "", muscle: str = "", equipment: str = "", limit: int = 200
) -> dict:
    """The exercise picker's data, searchable by name or alias."""
    with session_scope() as s:
        query = select(StrengthExercise).where(StrengthExercise.archived_at.is_(None))
        if muscle:
            query = query.where(StrengthExercise.primary_muscle == muscle)
        if equipment:
            query = query.where(StrengthExercise.equipment == equipment)
        rows = s.scalars(query.order_by(StrengthExercise.name)).all()

        needle = q.strip().lower()
        if needle:
            rows = [
                ex for ex in rows
                if needle in ex.name.lower()
                or needle in (ex.display_name or "").lower()
                or any(needle in str(a).lower() for a in (ex.aliases or []))
            ]
        return {
            "exercises": [_exercise_summary(ex) for ex in rows[:limit]],
            "muscles": sorted({ex.primary_muscle for ex in rows if ex.primary_muscle}),
            "equipment": sorted({ex.equipment for ex in rows if ex.equipment}),
            "total": len(rows),
        }


def _exercise_summary(ex: StrengthExercise) -> dict:
    return {
        "id": ex.id,
        "name": ex.display_name or ex.name,
        "canonicalName": ex.name,
        "slug": ex.slug,
        "familySlug": ex.family_slug,
        "primaryMuscle": ex.primary_muscle,
        "secondaryMuscles": list(ex.secondary_muscles or []),
        "equipment": ex.equipment,
        "movementPattern": ex.movement_pattern,
        "loadType": ex.load_type,
        "measurement": ex.measurement,
        "laterality": ex.laterality,
        "isCompound": bool(ex.is_compound),
        "incrementKg": ex.increment_kg,
        "barWeightKg": ex.bar_weight_kg,
        "defaultSets": ex.default_sets,
        "defaultReps": ex.default_reps,
        "favorite": bool(ex.favorite),
        "isCustom": bool(ex.is_custom),
    }


def list_templates() -> dict:
    with session_scope() as s:
        rows = s.scalars(
            select(StrengthWorkoutTemplate)
            .where(StrengthWorkoutTemplate.archived_at.is_(None))
            .order_by(StrengthWorkoutTemplate.name)
        ).all()
        out = []
        for template in rows:
            items = s.scalars(
                select(StrengthTemplateExercise).where(
                    StrengthTemplateExercise.template_id == template.id
                )
            ).all()
            muscles = []
            for item in items:
                ex = s.get(StrengthExercise, item.exercise_id)
                if ex and ex.primary_muscle not in muscles:
                    muscles.append(ex.primary_muscle)
            out.append({
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "version": template.version,
                "exerciseCount": len(items),
                "setCount": sum(i.target_sets for i in items),
                "muscles": muscles,
                "estimatedDurationMin": template.estimated_duration_min,
            })
        return {"templates": out}


def template_detail(template_id: int) -> dict:
    with session_scope() as s:
        template = s.get(StrengthWorkoutTemplate, template_id)
        if template is None:
            raise ProgrammeError("That template does not exist.")
        rows = s.execute(
            select(StrengthTemplateExercise, StrengthExercise)
            .join(StrengthExercise, StrengthTemplateExercise.exercise_id == StrengthExercise.id)
            .where(StrengthTemplateExercise.template_id == template_id)
            .order_by(StrengthTemplateExercise.sort_order)
        ).all()
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "exercises": [
                {
                    **_exercise_summary(ex),
                    "itemId": item.id,
                    "section": item.section,
                    "supersetGroup": item.superset_group,
                    "targetSets": item.target_sets,
                    "targetReps": item.target_reps,
                    "repMin": item.rep_min,
                    "repMax": item.rep_max,
                    "targetRpe": item.target_rpe,
                    "restSeconds": item.rest_seconds,
                    "progressionRule": item.progression_rule,
                    "notes": item.notes,
                }
                for item, ex in rows
            ],
        }


# --------------------------------------------------------------------------- #
# Training home
# --------------------------------------------------------------------------- #
def training_home(user_id: int) -> dict:
    """Everything the strength home screen needs, in one request.

    Includes ``importedSessions`` — gym sessions Apple Health recorded that
    have no logged detail. On a log that starts empty those are the only real
    training history there is, and showing a blank page beside 142 recorded
    gym visits would be a lie of omission.
    """
    today = date.today()
    since = today - timedelta(days=28)
    sets = reporting._load_sets(user_id, since=since)

    with session_scope() as s:
        recent = s.scalars(
            select(StrengthWorkout)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status.in_(reporting.COUNTED_STATUSES),
            )
            .order_by(StrengthWorkout.started_at.desc())
            .limit(1)
        ).first()
        last_session = {
            "id": recent.id,
            "name": recent.name,
            "day": recent.started_at.date().isoformat(),
            "daysAgo": (today - recent.started_at.date()).days,
            "status": recent.status,
        } if recent else None

        upcoming_rows = s.scalars(
            select(StrengthPlannedSession)
            .where(
                StrengthPlannedSession.user_id == user_id,
                StrengthPlannedSession.planned_date >= today,
                StrengthPlannedSession.status == "planned",
            )
            .order_by(StrengthPlannedSession.planned_date)
            .limit(5)
        ).all()
        next_planned = [_planned_dict(p, today) for p in upcoming_rows]

        active_programme = s.scalars(
            select(StrengthProgramme).where(
                StrengthProgramme.user_id == user_id,
                StrengthProgramme.status == "active",
            )
        ).first()
        programme = {
            "id": active_programme.id,
            "name": active_programme.name,
            "week": _programme_week(active_programme, today),
            "weeks": active_programme.weeks,
        } if active_programme else None

        # Apple Health strength sessions with no ORION detail behind them.
        linked = set(
            s.scalars(
                select(StrengthWorkout.workout_id).where(
                    StrengthWorkout.user_id == user_id,
                    StrengthWorkout.workout_id.isnot(None),
                )
            ).all()
        )
        # No LIMIT here: this is a count the UI states in words, and a limit
        # would silently report the cap instead of the truth ("60 sessions"
        # when there are 142). Two columns over a few hundred rows is cheap.
        imported = s.execute(
            select(Workout.id, Workout.started_at)
            .where(
                Workout.user_id == user_id,
                Workout.title == "Traditional Strength Training",
            )
            .order_by(Workout.started_at.desc())
        ).all()
        undetailed = [row for row in imported if row.id not in linked]

    return {
        "programme": programme,
        "lastSession": last_session,
        "nextPlanned": next_planned,
        "window": reporting.volume_summary(sets),
        "muscles": reporting.muscle_volume(sets)[:8],
        "warnings": reporting.programme_warnings(sets),
        "records": records.active_records(user_id)[:6],
        "proposals": progression.pending_proposals(user_id)[:5],
        "attention": _needs_attention(user_id, sets),
        "importedSessions": {
            "count": len(undetailed),
            "mostRecent": undetailed[0].started_at.date().isoformat() if undetailed else None,
            "firstRecorded": undetailed[-1].started_at.date().isoformat() if undetailed else None,
            "note": (
                f"{len(undetailed)} gym sessions came from Apple Health with no exercise "
                "detail. They count as training done, but cannot contribute to volume, "
                "records or progression."
            ) if undetailed else "",
        },
    }


def _needs_attention(user_id: int, sets: list) -> list[dict]:
    """Exercises that have gone quiet or stopped moving.

    Only reports what it can support: an exercise with too little history is
    left alone rather than described as "stalled".
    """
    by_exercise: dict[int, list] = defaultdict(list)
    for s_ in sets:
        by_exercise[s_.exercise_id].append(s_)

    all_sets = reporting._load_sets(user_id)
    out = []
    for exercise_id in {s_.exercise_id for s_ in all_sets}:
        trend = reporting.exercise_trend(all_sets, exercise_id=exercise_id)
        plateau = trend["plateau"]
        if plateau.get("plateaued") and plateau.get("confident"):
            out.append({
                "exerciseId": exercise_id,
                "name": trend["name"],
                "issue": "plateau",
                "detail": plateau["reason"],
            })
    return out[:5]


def _programme_week(programme: StrengthProgramme, today: date) -> int | None:
    if programme.start_date is None:
        return None
    return max(1, ((today - programme.start_date).days // 7) + 1)


def _planned_dict(p: StrengthPlannedSession, today: date) -> dict:
    delta = (p.planned_date - today).days
    return {
        "id": p.id,
        "date": p.planned_date.isoformat(),
        "name": p.name,
        "status": p.status,
        "templateId": p.template_id,
        "daysAway": delta,
        "label": "Today" if delta == 0 else ("Tomorrow" if delta == 1 else p.planned_date.strftime("%a %-d %b")),
        "rescheduledFrom": p.rescheduled_from.isoformat() if p.rescheduled_from else None,
        "rescheduleReason": p.reschedule_reason,
    }


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def upcoming(user_id: int, *, days: int = 28) -> dict:
    today = date.today()
    with session_scope() as s:
        rows = s.scalars(
            select(StrengthPlannedSession)
            .where(
                StrengthPlannedSession.user_id == user_id,
                StrengthPlannedSession.planned_date >= today - timedelta(days=days),
                StrengthPlannedSession.planned_date <= today + timedelta(days=days),
            )
            .order_by(StrengthPlannedSession.planned_date)
        ).all()
        return {"planned": [_planned_dict(p, today) for p in rows]}


def schedule_session(
    user_id: int, *, planned_date: date, name: str = "",
    template_id: int | None = None, programme_id: int | None = None,
    programme_day_id: int | None = None, target_duration_min: int | None = None,
    notes: str = "",
) -> int:
    """Schedule a session, freezing the prescription as it stands today.

    The freeze is the point: editing the template next week must change what
    happens next week, not retroactively change what this session was asked to
    do.
    """
    with session_scope() as s:
        prescription: list = []
        if template_id is not None:
            template = s.get(StrengthWorkoutTemplate, template_id)
            if template is None:
                raise ProgrammeError("That template does not exist.")
            name = name or template.name
            items = s.scalars(
                select(StrengthTemplateExercise)
                .where(StrengthTemplateExercise.template_id == template_id)
                .order_by(StrengthTemplateExercise.sort_order)
            ).all()
            for item in items:
                ex = s.get(StrengthExercise, item.exercise_id)
                prescription.append({
                    "exerciseId": item.exercise_id,
                    "name": (ex.display_name or ex.name) if ex else "",
                    "targetSets": item.target_sets,
                    "targetReps": item.target_reps,
                    "repMin": item.rep_min,
                    "repMax": item.rep_max,
                    "targetRpe": item.target_rpe,
                    "restSeconds": item.rest_seconds,
                    "progressionRule": item.progression_rule,
                })

        planned = StrengthPlannedSession(
            user_id=user_id,
            planned_date=planned_date,
            name=name or "Strength session",
            template_id=template_id,
            programme_id=programme_id,
            programme_day_id=programme_day_id,
            prescription=prescription,
            target_duration_min=target_duration_min,
            notes=notes,
            status="planned",
        )
        s.add(planned)
        s.flush()
        return planned.id


def reschedule(user_id: int, planned_id: int, new_date: date, *, reason: str = "") -> None:
    """Move a planned session, keeping where it came from.

    The original date is retained rather than overwritten: repeatedly pushing
    Friday to Saturday is a pattern worth being able to see, and it vanishes if
    a reschedule looks identical to having planned Saturday all along.
    """
    with session_scope() as s:
        planned = s.get(StrengthPlannedSession, planned_id)
        if planned is None or planned.user_id != user_id:
            raise ProgrammeError("That planned session does not exist.")
        if planned.rescheduled_from is None:
            planned.rescheduled_from = planned.planned_date
        planned.planned_date = new_date
        planned.reschedule_reason = reason
        planned.status = "planned"


def skip(user_id: int, planned_id: int, *, reason: str = "") -> None:
    with session_scope() as s:
        planned = s.get(StrengthPlannedSession, planned_id)
        if planned is None or planned.user_id != user_id:
            raise ProgrammeError("That planned session does not exist.")
        planned.status = "skipped"
        planned.reschedule_reason = reason or planned.reschedule_reason


# --------------------------------------------------------------------------- #
# Programmes
# --------------------------------------------------------------------------- #
def create_programme(
    user_id: int, *, name: str, description: str = "", goal: str = "",
    weeks: int = 4, days_per_week: int = 3, start_date: date | None = None,
    notes: str = "",
) -> int:
    if not name.strip():
        raise ProgrammeError("A programme needs a name.")
    with session_scope() as s:
        programme = StrengthProgramme(
            user_id=user_id, name=name.strip(), description=description,
            goal=goal, weeks=weeks, days_per_week=days_per_week,
            start_date=start_date, notes=notes, status="draft",
        )
        s.add(programme)
        s.flush()
        return programme.id


def list_programmes(user_id: int) -> dict:
    with session_scope() as s:
        rows = s.scalars(
            select(StrengthProgramme)
            .where(
                StrengthProgramme.user_id == user_id,
                StrengthProgramme.archived_at.is_(None),
            )
            .order_by(StrengthProgramme.created_at.desc())
        ).all()
        return {
            "programmes": [
                {
                    "id": p.id, "name": p.name, "description": p.description,
                    "goal": p.goal, "weeks": p.weeks, "daysPerWeek": p.days_per_week,
                    "status": p.status, "version": p.version,
                    "startDate": p.start_date.isoformat() if p.start_date else None,
                }
                for p in rows
            ]
        }


def programme_detail(user_id: int, programme_id: int) -> dict:
    with session_scope() as s:
        programme = s.get(StrengthProgramme, programme_id)
        if programme is None or programme.user_id != user_id:
            raise ProgrammeError("That programme does not exist.")
        days = s.scalars(
            select(StrengthProgrammeDay)
            .where(StrengthProgrammeDay.programme_id == programme_id)
            .order_by(StrengthProgrammeDay.week_number, StrengthProgrammeDay.day_number)
        ).all()
        return {
            "id": programme.id, "name": programme.name,
            "description": programme.description, "goal": programme.goal,
            "weeks": programme.weeks, "daysPerWeek": programme.days_per_week,
            "status": programme.status, "version": programme.version,
            "startDate": programme.start_date.isoformat() if programme.start_date else None,
            "days": [
                {
                    "id": d.id, "week": d.week_number, "day": d.day_number,
                    "name": d.name, "focus": d.focus, "weekday": d.weekday,
                    "targetDurationMin": d.target_duration_min,
                }
                for d in days
            ],
        }


# --------------------------------------------------------------------------- #
# Progression after a session
# --------------------------------------------------------------------------- #
def propose_after_session(user_id: int, workout_id: int) -> list[dict]:
    """Generate and store proposals for everything trained in a session.

    Runs after the session is finished rather than during it: nothing about
    logging a set should wait on this, and a proposal made mid-session would be
    based on half the evidence.
    """
    out: list[dict] = []
    with session_scope() as s:
        blocks = s.execute(
            select(StrengthWorkoutExercise, StrengthExercise)
            .join(StrengthExercise, StrengthWorkoutExercise.exercise_id == StrengthExercise.id)
            .where(StrengthWorkoutExercise.workout_id == workout_id)
        ).all()
        payload = []
        for block, exercise in blocks:
            entries = s.scalars(
                select(StrengthSetEntry).where(
                    StrengthSetEntry.workout_exercise_id == block.id,
                    StrengthSetEntry.completed.is_(True),
                    StrengthSetEntry.voided_at.is_(None),
                )
            ).all()
            if not entries:
                continue
            prescription = block.prescription or {}
            payload.append((
                exercise.id,
                exercise.display_name or exercise.name,
                prescription.get("progressionRule", "manual"),
                {
                    "repMin": prescription.get("repMin") or block.target_reps,
                    "repMax": prescription.get("repMax") or block.target_reps,
                    "targetReps": block.target_reps,
                    "targetRpe": prescription.get("targetRpe"),
                    "incrementKg": exercise.increment_kg,
                    **(prescription.get("progressionConfig") or {}),
                },
                [
                    progression.PerformedSet(
                        weight_kg=e.weight_kg or 0.0,
                        reps=e.reps or 0,
                        rpe=e.rpe,
                        rir=e.rir,
                        set_type=e.set_type,
                        to_failure=bool(e.to_failure),
                    )
                    for e in entries
                ],
            ))

    for exercise_id, name, rule, config, sets in payload:
        if rule == "manual":
            continue
        proposal = progression.propose(rule, sets, config=config,
                                       increment_kg=config.get("incrementKg", 2.5))
        if not proposal.conclusive:
            continue
        event_id = progression.record_proposal(
            user_id, exercise_id, proposal, workout_id=workout_id
        )
        out.append({"id": event_id, "exercise": name, **proposal.as_dict()})
    return out


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def session_history(user_id: int, *, limit: int = 40) -> list[dict]:
    sets = reporting._load_sets(user_id)
    by_workout: dict[int, list] = defaultdict(list)
    for s_ in sets:
        by_workout[s_.workout_id].append(s_)

    with session_scope() as s:
        rows = s.scalars(
            select(StrengthWorkout)
            .where(
                StrengthWorkout.user_id == user_id,
                StrengthWorkout.status.in_(reporting.COUNTED_STATUSES),
            )
            .order_by(StrengthWorkout.started_at.desc())
            .limit(limit)
        ).all()
        out = []
        for workout in rows:
            group = by_workout.get(workout.id, [])
            out.append({
                "id": workout.id,
                "name": workout.name,
                "day": workout.started_at.date().isoformat(),
                "status": workout.status,
                "volumeKg": round(sum(g.volume_kg for g in group), 1),
                "workingSets": len(group),
                "hardSets": sum(1 for g in group if g.is_hard),
                "exercises": len({g.exercise_id for g in group}),
                "sessionRpe": workout.session_rpe,
            })
        return out


def exercise_history(user_id: int, exercise_id: int, *, days: int = 365) -> dict:
    """One exercise's full picture: trend, sets, records and notes."""
    with session_scope() as s:
        exercise = s.get(StrengthExercise, exercise_id)
        if exercise is None:
            raise ProgrammeError("That exercise does not exist.")
        summary = _exercise_summary(exercise)

    since = date.today() - timedelta(days=days)
    sets = reporting._load_sets(user_id, since=since, exercise_id=exercise_id)
    trend = reporting.exercise_trend(sets, exercise_id=exercise_id)

    return {
        "exercise": summary,
        "trend": trend,
        "volume": reporting.volume_summary(sets),
        "intensity": reporting.intensity_summary(sets),
        "records": records.active_records(user_id, exercise_id),
        "sessions": trend["points"],
    }
