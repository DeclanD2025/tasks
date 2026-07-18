"""Today: the command centre. Time-aware, action-first, no duplicate dashboards.

The page answers, in order: where am I, what matters, what's next, what can
wait. Everything deeper lives one tap away on its own tab or in a drawer.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import services
from app.domains import personal_os, strength
from app.domains.health import derived
from app.web import presentation
from app.web.context import page, user_id

router = APIRouter()


def _daypart(now: datetime) -> str:
    hour = now.hour
    if hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


_DAYPART_LINES = {
    "morning": "Set the day before it sets you.",
    "afternoon": "Mid-flight. Adjust, don't restart.",
    "evening": "Close the day deliberately.",
    "night": "Wind down. Tomorrow is built tonight.",
}


def _nutrition_summary(uid: int) -> dict | None:
    """Compact fuel status for the Today card; None hides the card body."""
    try:
        from app.domains.nutrition import service as nutrition
    except ImportError:
        return None
    snap = nutrition.day_snapshot(uid)
    return snap


def _calendar_summary(uid: int) -> dict:
    now = datetime.now()
    events = services.calendar_events(uid, days_back=0, days_forward=1)
    today_events = [
        e for e in events
        if e["starts_at"].date() == date.today() and not e["all_day"]
    ]
    upcoming = [e for e in today_events if (e["ends_at"] or e["starts_at"]) >= now]
    return {
        "count_today": len(today_events),
        "next_event": upcoming[0] if upcoming else None,
        "remaining": len(upcoming),
        "all_day": [e for e in events
                    if e["all_day"] and e["starts_at"].date() == date.today()],
    }


# Also served at /today: when the redesigned UI is built it takes over "/",
# and this stays the way back to the real-data Jinja pages.
@router.get("/", response_class=HTMLResponse)
@router.get("/today", response_class=HTMLResponse)
def today(request: Request):
    uid = user_id()
    now = datetime.now()
    snapshot = personal_os.get_today_snapshot(uid)
    strength_snapshot = strength.dashboard(uid)
    mind = personal_os.get_mind_snapshot(uid)
    checkin = mind.today or {}
    daypart = _daypart(now)
    return page(
        request,
        "today.html",
        "today",
        snap=snapshot,
        strength=strength_snapshot,
        signals=presentation.partition_metrics(snapshot.metrics),
        insights=presentation.sorted_insights(snapshot.insights),
        detail_key=presentation.detail_key,
        daypart=daypart,
        daypart_line=_DAYPART_LINES[daypart],
        now=now,
        sleep_debt=derived.get_sleep_debt(uid),
        nutrition=_nutrition_summary(uid),
        cal=_calendar_summary(uid),
        morning_done=bool(checkin.get("intention") or checkin.get("mood")),
        evening_done=bool((checkin.get("evening_note") or "").strip()
                          or checkin.get("day_rating")),
    )
