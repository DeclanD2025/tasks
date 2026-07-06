"""Strength cockpit: templates, active workout, set logging, analytics."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domains import strength
from app.web.context import page, user_id

router = APIRouter()


@router.get("/strength", response_class=HTMLResponse)
def strength_dashboard(request: Request):
    snap = strength.dashboard(user_id())
    return page(request, "strength.html", "training", snap=snap)


@router.get("/strength/start", response_class=HTMLResponse)
def strength_start(request: Request):
    uid = user_id()
    return page(
        request,
        "strength_start.html",
        "training",
        active_workout=strength.active_workout(uid),
        templates=strength.templates(),
    )


@router.post("/strength/start")
def strength_start_post(template_id: str = Form(""), name: str = Form("")):
    workout_id = strength.start_workout(
        user_id(),
        template_id=int(template_id) if template_id.strip() else None,
        name=name,
    )
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.get("/strength/templates", response_class=HTMLResponse)
def strength_templates(request: Request):
    return page(request, "strength_templates.html", "training", templates=strength.templates())


@router.get("/strength/templates/{template_id}", response_class=HTMLResponse)
def strength_template_detail(request: Request, template_id: int):
    return page(
        request,
        "strength_template.html",
        "training",
        tpl=strength.template_detail(template_id),
    )


@router.get("/strength/workout/{workout_id}", response_class=HTMLResponse)
def strength_workout(request: Request, workout_id: int):
    return page(
        request,
        "strength_workout.html",
        "training",
        workout=strength.workout_detail(user_id(), workout_id),
        set_types=strength.SET_TYPES,
    )


@router.post("/strength/workout/{workout_id}/finish")
def strength_finish(workout_id: int, notes: str = Form("")):
    strength.finish_workout(user_id(), workout_id, notes=notes)
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.post("/strength/workout/{workout_id}/discard")
def strength_discard(workout_id: int):
    strength.discard_workout(user_id(), workout_id)
    return RedirectResponse("/strength", status_code=303)


@router.get("/strength/workout/{workout_id}/exercises", response_class=HTMLResponse)
def strength_exercise_picker(
    request: Request,
    workout_id: int,
    q: str = "",
    muscle: str = "",
    equipment: str = "",
    favorites: str = "",
):
    workout = strength.workout_detail(user_id(), workout_id)
    return page(
        request,
        "strength_picker.html",
        "training",
        workout=workout,
        picker=strength.exercise_picker(
            user_id(),
            q=q,
            muscle=muscle,
            equipment=equipment,
            favorites=bool(favorites),
            template_id=workout.get("template_id"),
        ),
    )


@router.post("/strength/workout/{workout_id}/exercises")
def strength_add_exercise(workout_id: int, exercise_id: int = Form(...)):
    strength.add_exercise_to_workout(user_id(), workout_id, exercise_id)
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.post("/strength/workout/{workout_id}/custom-exercise")
def strength_custom_exercise(
    workout_id: int,
    name: str = Form(""),
    primary_muscle: str = Form("Full body"),
    equipment: str = Form("Dumbbell"),
    default_sets: int = Form(3),
    default_reps: int = Form(8),
):
    if name.strip():
        exercise_id = strength.create_custom_exercise(
            name=name,
            primary_muscle=primary_muscle,
            equipment=equipment,
            default_sets=default_sets,
            default_reps=default_reps,
        )
        strength.add_exercise_to_workout(user_id(), workout_id, exercise_id)
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.post("/strength/sets/{set_id}")
def strength_update_set(
    set_id: int,
    workout_id: int = Form(...),
    weight: str = Form(""),
    reps: str = Form(""),
    rpe: str = Form(""),
    set_type: str = Form("working"),
    completed: str = Form(""),
):
    strength.update_set(
        user_id(),
        set_id,
        weight=weight,
        reps=reps,
        rpe=rpe,
        set_type=set_type,
        completed=bool(completed),
    )
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.post("/strength/exercise-blocks/{workout_exercise_id}/sets")
def strength_add_set(workout_exercise_id: int, workout_id: int = Form(...)):
    strength.add_set(user_id(), workout_exercise_id)
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.post("/strength/exercise-blocks/{workout_exercise_id}/apply-last")
def strength_apply_last(workout_exercise_id: int, workout_id: int = Form(...)):
    strength.apply_last_workout(user_id(), workout_exercise_id)
    return RedirectResponse(f"/strength/workout/{workout_id}", status_code=303)


@router.get("/strength/exercises/{exercise_id}", response_class=HTMLResponse)
def strength_exercise_detail(request: Request, exercise_id: int):
    return page(
        request,
        "strength_exercise.html",
        "training",
        detail=strength.exercise_detail(user_id(), exercise_id),
    )


@router.post("/strength/exercises/{exercise_id}/favorite")
def strength_favorite(exercise_id: int):
    strength.toggle_favorite(exercise_id)
    return RedirectResponse(f"/strength/exercises/{exercise_id}", status_code=303)


@router.get("/strength/history", response_class=HTMLResponse)
def strength_history(request: Request):
    return page(request, "strength_history.html", "training", workouts=strength.history(user_id()))


@router.get("/strength/analytics", response_class=HTMLResponse)
def strength_analytics(request: Request):
    return page(request, "strength_analytics.html", "training", snap=strength.analytics(user_id()))
