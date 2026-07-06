"""Training: the plan, the week, the run programme, quick logging."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domains import personal_os, strength
from app.domains.fitness import fitness_service as fitness
from app.web.context import apply_client_mutation, page, user_id, write_response

router = APIRouter()


@router.get("/training", response_class=HTMLResponse)
def training(request: Request):
    uid = user_id()
    recovery = personal_os.get_recovery_snapshot(uid)
    snapshot = personal_os.get_workout_tracker_snapshot(uid)
    plan = fitness.get_or_create_plan(uid)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    plan_days = [week_start + timedelta(days=offset) for offset in range(7)]
    planned_sessions = fitness.sessions_for_range(uid, week_start, week_start + timedelta(days=6))
    return page(
        request,
        "training.html",
        "training",
        snap=snapshot,
        strength=strength.dashboard(uid),
        run=personal_os.get_run_plan_snapshot(uid, recovery),
        recovery=recovery,
        categories=personal_os.WORKOUT_CATEGORIES,
        plan=plan,
        plan_today=today,
        plan_days=plan_days,
        planned_sessions=planned_sessions,
        palette=fitness.palette_cards(uid),
        plan_focuses=fitness.PLAN_FOCUS_LABELS,
    )


@router.post("/training/plan")
def training_plan_update(
    block_name: str = Form(""),
    purpose: str = Form(""),
    focus: str = Form("hybrid"),
    goal: str = Form(""),
    start_date: str = Form(""),
    weeks: str = Form("6"),
):
    uid = user_id()
    plan = fitness.get_or_create_plan(uid)
    parsed_start = None
    if start_date.strip():
        try:
            parsed_start = date.fromisoformat(start_date)
        except ValueError:
            parsed_start = None
    try:
        parsed_weeks = int(weeks)
    except ValueError:
        parsed_weeks = plan.weeks
    fitness.update_plan(
        plan.id,
        block_name=block_name,
        purpose=purpose,
        focus=focus,
        goal=goal,
        start_date=parsed_start,
        weeks=parsed_weeks,
    )
    return RedirectResponse("/training#training-plan", status_code=303)


@router.post("/training/plan/session")
def training_plan_session_add(
    day: str = Form(""),
    session_type: str = Form("ZONE 2 CARDIO"),
    label: str = Form(""),
    notes: str = Form(""),
):
    uid = user_id()
    try:
        parsed_day = date.fromisoformat(day)
    except ValueError:
        parsed_day = date.today()
    session_id = fitness.add_session(uid, parsed_day, session_type)
    fitness.update_session(session_id, label=label, notes=notes)
    return RedirectResponse("/training#training-plan", status_code=303)


@router.post("/training/plan/session/{session_id}/complete")
def training_plan_session_complete(session_id: int, completed: str = Form("")):
    fitness.mark_complete(session_id, complete=bool(completed))
    return RedirectResponse("/training#training-plan", status_code=303)


@router.post("/training/log")
def training_log(
    request: Request,
    title: str = Form(""),
    category: str = Form("custom"),
    exercises_text: str = Form(""),
    duration_minutes: str = Form(""),
    rpe: str = Form(""),
    notes: str = Form(""),
    completed: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        session_id = personal_os.log_workout_session(
            uid,
            title=title,
            category=category,
            exercises_text=exercises_text,
            duration_minutes=int(duration_minutes) if duration_minutes.strip() else None,
            rpe=float(rpe) if rpe.strip() else None,
            completed=bool(completed),
            notes=notes,
        )
        return {"record_id": session_id}

    result = apply_client_mutation(uid, client_mutation_id, "training.log", apply)
    return write_response(request, "/training", result)


@router.post("/training/repeat")
def training_repeat():
    personal_os.repeat_last_workout(user_id())
    return RedirectResponse("/training", status_code=303)


@router.post("/training/{session_id}/complete")
def training_complete(session_id: int, completed: str = Form("")):
    personal_os.mark_workout_complete(session_id, completed=bool(completed))
    return RedirectResponse("/training", status_code=303)


@router.get("/run", response_class=HTMLResponse)
def run_plan(request: Request):
    uid = user_id()
    recovery = personal_os.get_recovery_snapshot(uid)
    snapshot = personal_os.get_run_plan_snapshot(uid, recovery)
    # Saved routes within ±30% of the suggested distance, best-known first.
    from app.domains.fitness import route_service

    target_km = snapshot.next_run.distance_km or 0
    route_suggestions = [
        r for r in route_service.list_routes(uid)
        if r.distance_meters
        and target_km
        and abs(r.distance_meters / 1000 - target_km) <= target_km * 0.3
    ][:3]
    return page(
        request,
        "run.html",
        "training",
        snap=snapshot,
        recovery=recovery,
        route_suggestions=route_suggestions,
        format_duration=route_service.format_duration,
    )
