"""Mind: morning brief, evening debrief, mood, stoic practice, mindfulness."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.domains import personal_os
from app.domains.mental_health import mental_health_service
from app.domains.stoic import stoic_service
from app.web.context import apply_client_mutation, page, user_id, write_response

router = APIRouter()

MOOD_FACTORS = (
    "sleep", "training", "work", "people", "money", "health", "food", "weather",
)

# Human labels for the check-in scales: numbers alone explain nothing.
SCALE_LABELS = {
    "mood": {1: "depleted", 3: "low", 5: "neutral", 7: "good", 10: "excellent"},
    "energy": {1: "empty", 3: "flat", 5: "steady", 7: "charged", 10: "peak"},
    "anxiety": {1: "calm", 3: "background", 5: "present", 7: "heavy", 10: "overwhelming"},
    "sleep_quality": {1: "rough", 3: "broken", 5: "adequate", 7: "solid", 10: "deep"},
    "stress": {1: "calm", 3: "manageable", 5: "present", 7: "heavy", 10: "overwhelmed"},
    "day_rating": {1: "lost", 3: "hard", 5: "even", 7: "good", 10: "exceptional"},
}


def _mind_page(request: Request, *, phase: str = "", saved: str = ""):
    uid = user_id()
    snapshot = personal_os.get_mind_snapshot(uid)
    if phase not in {"morning", "evening"}:
        phase = "morning" if datetime.now().hour < 14 else "evening"
    # CBT feedback on the saved evening reflection: deterministic
    # distortion detection + ACT prompts + a regulation method.
    reflection = None
    today = snapshot.today or {}
    reflection_text = " ".join(
        part
        for part in (
            today.get("evening_note", ""),
            (today.get("thought_record") or {}).get("thought", ""),
        )
        if part
    ).strip()
    if phase == "evening" and reflection_text:
        reflection = mental_health_service.build_reflection(reflection_text)
    saved_notes = {
        "morning": "Morning brief logged.",
        "evening": "Evening debrief logged.",
        "mindfulness": "Session logged.",
        "stoic": "Practice logged.",
    }
    return page(
        request,
        "mind.html",
        "mind",
        snap=snapshot,
        stoic=stoic_service.get_stoic_snapshot(uid),
        phase=phase,
        reflection=reflection,
        saved_note=saved_notes.get(saved, ""),
        mindfulness_types=personal_os.MINDFULNESS_TYPES,
        mood_factors=MOOD_FACTORS,
        scale_labels=SCALE_LABELS,
    )


@router.get("/mind", response_class=HTMLResponse)
def mind(request: Request, phase: str = "", saved: str = ""):
    return _mind_page(request, phase=phase, saved=saved)


@router.post("/mind/morning")
def mind_morning(
    request: Request,
    mood: int = Form(5),
    energy: int = Form(5),
    anxiety: int = Form(3),
    sleep_quality: int = Form(5),
    intention: str = Form(""),
    factors: list[str] = Form([]),  # noqa: B008 - FastAPI form binding
    triggers: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        personal_os.upsert_mental_checkin(
            uid,
            mood=mood,
            energy=energy,
            anxiety=anxiety,
            sleep_quality=sleep_quality,
            intention=intention,
            factors=factors,
            triggers=triggers,
        )
        return {}

    result = apply_client_mutation(uid, client_mutation_id, "mind.morning", apply)
    return write_response(request, "/mind?phase=morning&saved=morning", result)


@router.post("/mind/evening")
def mind_evening(
    request: Request,
    stress: int = Form(3),
    day_rating: int = Form(5),
    intention_done: str = Form(""),
    evening_note: str = Form(""),
    situation: str = Form(""),
    thought: str = Form(""),
    balanced: str = Form(""),
    protective_actions: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        personal_os.upsert_mental_checkin(
            uid,
            stress=stress,
            day_rating=day_rating,
            intention_done=bool(intention_done),
            evening_note=evening_note,
            thought_record={"situation": situation, "thought": thought, "balanced": balanced},
            protective_actions=protective_actions,
        )
        return {}

    result = apply_client_mutation(uid, client_mutation_id, "mind.evening", apply)
    return write_response(request, "/mind?phase=evening&saved=evening", result)


@router.post("/mind/mindfulness")
def mind_mindfulness(
    request: Request,
    duration_minutes: int = Form(3),
    kind: str = Form("meditation"),
    note: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        session_id = personal_os.log_mindfulness_session(
            uid, duration_minutes=duration_minutes, kind=kind, note=note
        )
        return {"record_id": session_id}

    result = apply_client_mutation(uid, client_mutation_id, "mind.mindfulness", apply)
    return write_response(request, "/mind?saved=mindfulness", result)


@router.get("/stoic", response_class=HTMLResponse)
def stoic(request: Request, saved: str = ""):
    return _mind_page(request, phase="evening", saved="stoic" if saved else "")


@router.post("/stoic/entry")
def stoic_entry(
    request: Request,
    virtue_focus: str = Form("wisdom"),
    control_pct: int = Form(50),
    reflected: str = Form(""),
    served_others: str = Form(""),
    faced_hard_thing: str = Form(""),
    restrained_impulse: str = Form(""),
    study_minutes: int = Form(0),
    reflection: str = Form(""),
    client_mutation_id: str = Form(""),
):
    uid = user_id()

    def apply():
        stoic_service.upsert_today_entry(
            uid,
            virtue_focus=virtue_focus,
            control_pct=control_pct,
            reflected=bool(reflected),
            served_others=bool(served_others),
            faced_hard_thing=bool(faced_hard_thing),
            restrained_impulse=bool(restrained_impulse),
            study_minutes=study_minutes,
            reflection=reflection,
        )
        return {}

    result = apply_client_mutation(uid, client_mutation_id, "stoic.entry", apply)
    return write_response(request, "/mind?phase=evening&saved=stoic", result)
