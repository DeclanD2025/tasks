"""JSON API for the strength system.

Split out of ``api_v2.py`` because strength is the one module with a real
write surface — a live workout is a stream of small mutations from a phone,
which is a different shape of API from the read-only screen payloads next
door, and mixing them would make both harder to reason about.

Two conventions specific to this router:

**Every write is user-scoped through ``user_id()``.** The service layer
re-checks ownership on every call rather than trusting the route, so a bug
here cannot expose another user's training. There is one user today; that is
not a reason to write code that breaks when there are two.

**Set creation is idempotent.** ``POST /sets`` accepts a ``clientKey`` minted
by the device. A retry after a dropped connection returns the original set
rather than writing a second one, which is what makes optimistic UI safe on gym
wifi.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domains.strength import (
    catalog,
    programmes,
    progression,
    records,
    reporting,
    sessions,
    tracker,
)
from app.domains.strength import export as strength_export
from app.web.context import user_id

router = APIRouter(prefix="/api/v2/strength")


def _json(payload) -> JSONResponse:
    return JSONResponse(jsonable_encoder(payload))


def _error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class StartSessionIn(BaseModel):
    templateId: int | None = None
    plannedSessionId: int | None = None
    name: str = ""
    location: str = ""


class AddExerciseIn(BaseModel):
    exerciseId: int
    substitutedFromId: int | None = None
    substitutionReason: str = ""


class SubstituteIn(BaseModel):
    exerciseId: int
    reason: str = ""


class LogSetIn(BaseModel):
    #: Device-minted idempotency key. Optional so a curl call still works, but
    #: the client always sends one.
    clientKey: str | None = None
    weightKg: float | None = None
    reps: int | None = None
    setType: str = "working"
    rpe: float | None = None
    rir: float | None = None
    durationSeconds: float | None = None
    distanceM: float | None = None
    assistanceKg: float | None = None
    leftReps: int | None = None
    rightReps: int | None = None
    restSeconds: float | None = None
    toFailure: bool = False
    hasPartials: bool = False
    notes: str = ""
    unit: str = "kg"


class UpdateSetIn(BaseModel):
    weightKg: float | None = None
    reps: int | None = None
    setType: str | None = None
    rpe: float | None = None
    rir: float | None = None
    durationSeconds: float | None = None
    notes: str | None = None
    toFailure: bool | None = None


class VoidSetIn(BaseModel):
    reason: str = ""


class FinishSessionIn(BaseModel):
    notes: str = ""
    sessionRpe: float | None = None
    painNotes: str = ""


class AbandonIn(BaseModel):
    reason: str = ""


class DecisionIn(BaseModel):
    accepted: bool
    applied: dict | None = None


class PlannedSessionIn(BaseModel):
    plannedDate: date
    name: str = ""
    templateId: int | None = None
    programmeId: int | None = None
    programmeDayId: int | None = None
    targetDurationMin: int | None = None
    notes: str = ""


class ReschedulePlanIn(BaseModel):
    plannedDate: date
    reason: str = ""


class ProgrammeIn(BaseModel):
    name: str
    description: str = ""
    goal: str = ""
    weeks: int = 4
    daysPerWeek: int = 3
    startDate: date | None = None
    notes: str = ""


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
@router.get("/exercises")
def v2_exercises(q: str = "", muscle: str = "", equipment: str = "", limit: int = 200):
    return _json(programmes.list_exercises(q=q, muscle=muscle, equipment=equipment, limit=limit))


@router.get("/exercises/{exercise_id}")
def v2_exercise_detail(exercise_id: int, days: int = 365):
    try:
        return _json(programmes.exercise_history(user_id(), exercise_id, days=days))
    except programmes.ProgrammeError as exc:
        return _error(exc, 404)


@router.get("/templates")
def v2_templates():
    tracker.ensure_seeded()
    return _json(programmes.list_templates())


@router.get("/templates/{template_id}")
def v2_template_detail(template_id: int):
    try:
        return _json(programmes.template_detail(template_id))
    except programmes.ProgrammeError as exc:
        return _error(exc, 404)


# --------------------------------------------------------------------------- #
# The training home screen
# --------------------------------------------------------------------------- #
@router.get("/home")
def v2_strength_home():
    return _json(programmes.training_home(user_id()))


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
@router.get("/session/active")
def v2_active_session():
    """The live session, or null. Backs resume-after-crash on every load."""
    return _json({"session": sessions.active_session(user_id())})


@router.post("/session")
def v2_start_session(body: StartSessionIn):
    try:
        workout_id = sessions.start_session(
            user_id(),
            template_id=body.templateId,
            planned_session_id=body.plannedSessionId,
            name=body.name,
            location=body.location,
        )
    except sessions.SessionError as exc:
        return _error(exc, 409)
    return _json(sessions.session_detail(user_id(), workout_id))


@router.get("/session/{workout_id}")
def v2_session(workout_id: int):
    try:
        return _json(sessions.session_detail(user_id(), workout_id))
    except sessions.SessionError as exc:
        return _error(exc, 404)


@router.get("/session/{workout_id}/summary")
def v2_session_summary(workout_id: int):
    try:
        return _json(sessions.session_summary(user_id(), workout_id))
    except sessions.SessionError as exc:
        return _error(exc, 404)


@router.post("/session/{workout_id}/exercises")
def v2_add_exercise(workout_id: int, body: AddExerciseIn):
    try:
        block_id = sessions.add_exercise(
            user_id(), workout_id, body.exerciseId,
            substituted_from_id=body.substitutedFromId,
            substitution_reason=body.substitutionReason,
        )
    except sessions.SessionError as exc:
        return _error(exc)
    return _json({"id": block_id, "session": sessions.session_detail(user_id(), workout_id)})


@router.post("/session/{workout_id}/finish")
def v2_finish_session(workout_id: int, body: FinishSessionIn):
    try:
        summary = sessions.finish_session(
            user_id(), workout_id,
            notes=body.notes, session_rpe=body.sessionRpe, pain_notes=body.painNotes,
        )
    except sessions.SessionError as exc:
        return _error(exc)
    # Proposals are generated after the session, from what was actually done.
    summary["proposals"] = programmes.propose_after_session(user_id(), workout_id)
    return _json(summary)


@router.post("/session/{workout_id}/abandon")
def v2_abandon_session(workout_id: int, body: AbandonIn):
    try:
        sessions.abandon_session(user_id(), workout_id, reason=body.reason)
    except sessions.SessionError as exc:
        return _error(exc)
    return _json({"ok": True})


@router.delete("/session/{workout_id}")
def v2_discard_session(workout_id: int):
    try:
        sessions.discard_session(user_id(), workout_id)
    except sessions.SessionError as exc:
        return _error(exc)
    return _json({"ok": True})


# --------------------------------------------------------------------------- #
# Exercise blocks and sets
# --------------------------------------------------------------------------- #
@router.post("/blocks/{block_id}/substitute")
def v2_substitute(block_id: int, body: SubstituteIn):
    try:
        sessions.substitute_exercise(user_id(), block_id, body.exerciseId, reason=body.reason)
    except sessions.SessionError as exc:
        return _error(exc)
    return _json({"ok": True})


@router.post("/blocks/{block_id}/sets")
def v2_log_set(block_id: int, body: LogSetIn):
    """Log one set. Idempotent on ``clientKey``."""
    try:
        result = sessions.log_set(
            user_id(), block_id,
            client_key=body.clientKey,
            weight_kg=body.weightKg,
            reps=body.reps,
            set_type=body.setType,
            rpe=body.rpe,
            rir=body.rir,
            duration_seconds=body.durationSeconds,
            distance_m=body.distanceM,
            assistance_kg=body.assistanceKg,
            left_reps=body.leftReps,
            right_reps=body.rightReps,
            rest_seconds=body.restSeconds,
            to_failure=body.toFailure,
            has_partials=body.hasPartials,
            notes=body.notes,
            unit=body.unit,
        )
    except sessions.SessionError as exc:
        return _error(exc)
    return _json(result)


@router.patch("/sets/{set_id}")
def v2_update_set(set_id: int, body: UpdateSetIn):
    changes = {
        key: value
        for key, value in {
            "weight_kg": body.weightKg,
            "reps": body.reps,
            "set_type": body.setType,
            "rpe": body.rpe,
            "rir": body.rir,
            "duration_seconds": body.durationSeconds,
            "notes": body.notes,
            "to_failure": body.toFailure,
        }.items()
        if value is not None
    }
    if not changes:
        return _error(ValueError("No changes supplied."))
    try:
        return _json(sessions.update_set(user_id(), set_id, **changes))
    except sessions.SessionError as exc:
        return _error(exc)


@router.delete("/sets/{set_id}")
def v2_void_set(set_id: int, reason: str = ""):
    """Void, not delete — the row stays readable and leaves the statistics."""
    try:
        sessions.void_set(user_id(), set_id, reason=reason)
    except sessions.SessionError as exc:
        return _error(exc)
    return _json({"ok": True})


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
@router.get("/planned")
def v2_planned(days: int = 28):
    return _json(programmes.upcoming(user_id(), days=days))


@router.post("/planned")
def v2_create_planned(body: PlannedSessionIn):
    try:
        planned_id = programmes.schedule_session(
            user_id(),
            planned_date=body.plannedDate,
            name=body.name,
            template_id=body.templateId,
            programme_id=body.programmeId,
            programme_day_id=body.programmeDayId,
            target_duration_min=body.targetDurationMin,
            notes=body.notes,
        )
    except programmes.ProgrammeError as exc:
        return _error(exc)
    return _json({"id": planned_id})


@router.post("/planned/{planned_id}/reschedule")
def v2_reschedule(planned_id: int, body: ReschedulePlanIn):
    try:
        programmes.reschedule(user_id(), planned_id, body.plannedDate, reason=body.reason)
    except programmes.ProgrammeError as exc:
        return _error(exc)
    return _json({"ok": True})


@router.delete("/planned/{planned_id}")
def v2_skip_planned(planned_id: int, reason: str = ""):
    try:
        programmes.skip(user_id(), planned_id, reason=reason)
    except programmes.ProgrammeError as exc:
        return _error(exc)
    return _json({"ok": True})


@router.get("/programmes")
def v2_programmes():
    return _json(programmes.list_programmes(user_id()))


@router.post("/programmes")
def v2_create_programme(body: ProgrammeIn):
    try:
        programme_id = programmes.create_programme(
            user_id(),
            name=body.name, description=body.description, goal=body.goal,
            weeks=body.weeks, days_per_week=body.daysPerWeek,
            start_date=body.startDate, notes=body.notes,
        )
    except programmes.ProgrammeError as exc:
        return _error(exc)
    return _json({"id": programme_id})


@router.get("/programmes/{programme_id}")
def v2_programme(programme_id: int):
    try:
        return _json(programmes.programme_detail(user_id(), programme_id))
    except programmes.ProgrammeError as exc:
        return _error(exc, 404)


# --------------------------------------------------------------------------- #
# Records, progression and analytics
# --------------------------------------------------------------------------- #
@router.get("/records")
def v2_records(exerciseId: int | None = None):
    return _json({"records": records.active_records(user_id(), exerciseId)})


@router.get("/proposals")
def v2_proposals():
    return _json({"proposals": progression.pending_proposals(user_id())})


@router.post("/proposals/{event_id}")
def v2_decide_proposal(event_id: int, body: DecisionIn):
    progression.decide(event_id, accepted=body.accepted, applied=body.applied)
    return _json({"ok": True})


@router.get("/analytics")
def v2_analytics(days: int = 28):
    return _json(reporting.overview(user_id(), days=days))


@router.get("/history")
def v2_history(limit: int = 40):
    return _json({"sessions": programmes.session_history(user_id(), limit=limit)})


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
@router.get("/export.json")
def v2_export_json():
    """Full backup. An explicit user action, never a background push."""
    return _json(strength_export.export_all(user_id()))


@router.get("/export.csv")
def v2_export_csv(table: str = "sets"):
    try:
        body = strength_export.export_csv(user_id(), table=table)
    except ValueError as exc:
        return _error(exc)
    return JSONResponse(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="orion-strength-{table}.csv"'},
    )
