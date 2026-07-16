"""Shared web-layer plumbing: templates, navigation, auth, write protocol.

Every router imports from here; ``server.py`` only assembles the app. Keeping
this module free of domain logic preserves the architecture rule that the web
layer renders read models and forwards writes — it never scores or interprets.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app import services
from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import ClientMutation, ExternalSignalCache, User
from app.web import presentation
from app.web.auth import SESSION_COOKIE, verify_token

log = get_logger(__name__)

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# Dock: the five daily surfaces. More-sheet: everything else, one tap away.
NAV_DOCK = [
    ("today", "/", "Today"),
    ("training", "/training", "Train"),
    ("health", "/health", "Health"),
    ("nutrition", "/nutrition", "Fuel"),
    ("mind", "/mind", "Mind"),
]
NAV_MORE = [
    # Route Atlas (/routes) is a running sub-view, reached from Train → Run Plan,
    # not a top-level tab — intentionally omitted here. The page still exists.
    ("calendar", "/calendar", "Calendar", "Week orbit, load, holidays"),
    ("tasks", "/tasks", "Tasks", "Open loops, synced"),
    ("money", "/money", "Money", "Position, runway, currency"),
    ("data", "/data", "Data Vault", "Imports, exports, signal status"),
    ("settings", "/settings", "Settings", "Targets, location, theme"),
]
MODULE_CODES = {
    "today": "TDY-00", "training": "TRN-01", "health": "BIO-02",
    "nutrition": "FUE-03", "mind": "MND-04", "routes": "ATL-05",
    "calendar": "ORB-06", "tasks": "TSK-07", "money": "MNY-08",
    "data": "VLT-09", "settings": "CFG-10",
}

def _dayname(iso_day: str) -> str:
    """Weekday abbreviation for an ISO date string ('2026-07-06' -> 'Mon')."""
    try:
        return date.fromisoformat(str(iso_day)).strftime("%a")
    except ValueError:
        return str(iso_day)


SIGNAL_GLYPHS = {
    "Sleep": "◌",
    "HRV": "♡",
    "Resting HR": "♥",
    "Steps": "⏱",
    "Active Energy": "⚡",
    "Workout Load": "⚑",
    "Strain": "⚑",
    "Run/Walk Distance": "⌖",
    "Weight": "◯",
    "Sleep Debt": "☾",
    "Mindfulness": "◉",
    "Mood": "◎",
    "Respiratory Rate": "≈",
}

FACTOR_DETAIL_KEYS = {
    "Sleep": "sleep",
    "HRV": "hrv",
    "Resting HR": "resting_hr",
    "Recent strain": "training_load",
    "Sleep debt": "sleep_debt",
    "Mood": "mood",
}


templates.env.globals.update(
    NAV_DOCK=NAV_DOCK,
    NAV_MORE=NAV_MORE,
    spark=presentation.spark,
    delta=presentation.delta,
    SIGNAL_GLYPHS=SIGNAL_GLYPHS,
    FACTOR_DETAIL_KEYS=FACTOR_DETAIL_KEYS,
)
templates.env.filters["money"] = presentation.money
templates.env.filters["dayname"] = _dayname


def user_id() -> int:
    uid = services.get_default_user_id()
    if uid is None:
        # First run against an empty database: create a bare local profile.
        # No mock data is seeded here — real imports stay the only data path.
        with session_scope() as s:
            user = User(email="operator@orion.local", display_name="Operator")
            s.add(user)
            s.flush()
            uid = user.id
        log.info("Created local web profile (user %s).", uid)
    return uid


def authed(request: Request) -> bool:
    return verify_token(request.cookies.get(SESSION_COOKIE))


def weather_pill_cached() -> dict | None:
    """Masthead weather from the cache table only — never the network.

    Page renders must not block on an upstream; the client refreshes the pill
    through ``/api/signals/weather`` after load when the cache is stale.
    """
    from app.integrations.external_signals.service import describe_wmo

    with session_scope() as s:
        row = s.scalars(
            select(ExternalSignalCache).where(ExternalSignalCache.kind == "weather")
        ).first()
        if row is None or not row.ok or not row.payload:
            return None
        current = row.payload.get("current") or {}
        if current.get("temperature_2m") is None:
            return None
        label, glyph = describe_wmo(current.get("weather_code"))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return {
            "temp": round(current["temperature_2m"]),
            "label": label,
            "glyph": glyph,
            "stale": bool(row.expires_at and row.expires_at < now),
        }


def page(request: Request, template: str, active: str, **context) -> HTMLResponse:
    theme = "cinematic"
    if active != "login":
        from app.domains import settings_service

        theme = settings_service.get_value(user_id(), "theme_intensity") or "cinematic"
    context.update(
        {
            "request": request,
            "active": active,
            "today_date": date.today(),
            "module_code": MODULE_CODES.get(active, ""),
            "weather_pill": weather_pill_cached() if active != "login" else None,
            "theme_intensity": theme,
        }
    )
    return templates.TemplateResponse(request, template, context)


def parse_form_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ------------------------------------------------------- offline write protocol
def queued_request(request: Request) -> bool:
    return request.headers.get("X-Orion-Queue", "") == "1"


def _mutation_key(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_:")[:96]


def apply_client_mutation(user_id_: int, mutation_id: str, action: str, apply) -> dict:
    """Idempotent write: a replayed mutation returns its original receipt."""
    key = _mutation_key(mutation_id)
    if not key:
        return apply()
    with session_scope() as s:
        existing = s.scalars(
            select(ClientMutation).where(
                ClientMutation.user_id == user_id_,
                ClientMutation.mutation_id == key,
            )
        ).first()
        if existing is not None:
            return dict(existing.result or {})
    result = apply()
    with session_scope() as s:
        # A duplicate arriving after the write but before the receipt is rare,
        # but the unique constraint still protects future replays.
        existing = s.scalars(
            select(ClientMutation).where(
                ClientMutation.user_id == user_id_,
                ClientMutation.mutation_id == key,
            )
        ).first()
        if existing is None:
            s.add(
                ClientMutation(
                    user_id=user_id_,
                    mutation_id=key,
                    action=action,
                    result=dict(result or {}),
                )
            )
    return result


def write_response(request: Request, location: str, result: dict | None = None):
    if queued_request(request):
        payload = {"status": "ok", "location": location}
        if result:
            payload.update(result)
        return JSONResponse(payload)
    return RedirectResponse(location, status_code=303)
