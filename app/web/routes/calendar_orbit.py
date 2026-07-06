"""Calendar: the week orbit — events, load, holidays, protected windows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app import services
from app.db.database import session_scope
from app.db.models import CalendarEvent
from app.domains import settings_service
from app.integrations.external_signals import get_holidays
from app.web.context import page, user_id

router = APIRouter()

MANUAL_PREFIX = "orion-manual-"


def _day_load(events: list[dict]) -> dict:
    """Transparent load score for one day's events.

    Score = scheduled hours (capped 10) + 0.5 per event over three. Bands:
    <2 clear, <5 light, <8 loaded, else heavy. Shown with its inputs so the
    number never has to be trusted blind.
    """
    timed = [e for e in events if not e["all_day"] and e.get("ends_at")]
    hours = sum(
        min(max((e["ends_at"] - e["starts_at"]).total_seconds() / 3600.0, 0.25), 10)
        for e in timed
    )
    score = min(hours, 10) + max(len(timed) - 3, 0) * 0.5
    if score < 2:
        band = "clear"
    elif score < 5:
        band = "light"
    elif score < 8:
        band = "loaded"
    else:
        band = "heavy"
    return {"hours": round(hours, 1), "events": len(timed), "score": round(score, 1),
            "band": band}


def _free_evening(events: list[dict], day: date) -> bool:
    evening_start = datetime.combine(day, time(18, 0))
    evening_end = datetime.combine(day, time(22, 0))
    for e in events:
        if e["all_day"] or not e.get("ends_at"):
            continue
        if e["starts_at"] < evening_end and e["ends_at"] > evening_start:
            return False
    return True


@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request):
    uid = user_id()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    events = services.calendar_events(uid, days_back=1, days_forward=21)

    days = []
    for offset in range(14):
        day = week_start + timedelta(days=offset)
        day_events = sorted(
            (e for e in events if e["starts_at"].date() == day),
            key=lambda e: (not e["all_day"], e["starts_at"]),
        )
        days.append({
            "day": day,
            "is_today": day == today,
            "events": day_events,
            "load": _day_load(day_events),
            "free_evening": _free_evening(day_events, day),
        })

    country = settings_service.get_value(uid, "holiday_country") or "GB"
    holidays_signal = get_holidays(country)
    horizon = today + timedelta(days=60)
    holidays = []
    if holidays_signal.ok:
        for item in holidays_signal.payload.get("items", []):
            try:
                holiday_date = date.fromisoformat(item.get("date", ""))
            except ValueError:
                continue
            if today <= holiday_date <= horizon:
                holidays.append({"date": holiday_date, "name": item.get("localName")
                                 or item.get("name", "")})

    week_load = sum(d["load"]["score"] for d in days[:7])
    return page(
        request,
        "calendar.html",
        "calendar",
        days=days,
        this_week=days[:7],
        next_week=days[7:],
        week_load=round(week_load, 1),
        holidays=holidays,
        holidays_ok=holidays_signal.ok,
        now=datetime.now(),
    )


@router.post("/calendar/event")
def calendar_event_add(
    title: str = Form(""),
    day: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    location: str = Form(""),
    all_day: str = Form(""),
    notes: str = Form(""),
):
    uid = user_id()
    title = title.strip()
    if not title:
        return RedirectResponse("/calendar", status_code=303)
    try:
        event_day = date.fromisoformat(day)
    except ValueError:
        event_day = date.today()
    if all_day or not start_time:
        starts = datetime.combine(event_day, time(0, 0))
        ends = datetime.combine(event_day, time(23, 59))
    else:
        try:
            starts = datetime.combine(event_day, time.fromisoformat(start_time))
        except ValueError:
            starts = datetime.combine(event_day, time(9, 0))
        try:
            ends = datetime.combine(event_day, time.fromisoformat(end_time))
        except ValueError:
            ends = starts + timedelta(hours=1)
        if ends <= starts:
            ends = starts + timedelta(hours=1)
    with session_scope() as s:
        s.add(CalendarEvent(
            user_id=uid,
            ext_id=f"{MANUAL_PREFIX}{datetime.now().timestamp():.0f}",
            title=title[:400],
            location=location.strip()[:400] or None,
            calendar_name="ORION",
            starts_at=starts,
            ends_at=ends,
            all_day=bool(all_day),
            notes=notes.strip() or None,
        ))
    return RedirectResponse("/calendar", status_code=303)


@router.post("/calendar/event/{event_id}/delete")
def calendar_event_delete(event_id: int):
    uid = user_id()
    with session_scope() as s:
        event = s.scalars(
            select(CalendarEvent).where(
                CalendarEvent.id == event_id, CalendarEvent.user_id == uid
            )
        ).first()
        # Only manual events are deletable; synced ones belong to their source.
        if event is not None and event.ext_id.startswith(MANUAL_PREFIX):
            s.delete(event)
    return RedirectResponse("/calendar", status_code=303)
