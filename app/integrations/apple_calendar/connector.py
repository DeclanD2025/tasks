"""Apple Calendar connector — reads iCloud/local calendars via macOS EventKit.

This is the practical way to keep ORION's calendar in sync with your iPhone:
the same iCloud calendars sync to this Mac, and EventKit exposes them. ORION
mirrors events read-only into ``calendar_events`` (it never writes back), upserts
by EventKit identifier, and prunes events that have left the sync window.

First sync triggers the macOS calendar-access prompt. If access is denied or the
framework is unavailable (non-macOS), the connector reports unavailable and — in
development — falls back to the Google Calendar mock so the Calendar module still
renders.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import CalendarEvent, Domain
from app.ingestion.base import Connector
from app.integrations.apple_calendar.eventkit import (
    EVENTKIT_AVAILABLE,
    EventKitReader,
)

log = get_logger(__name__)


class AppleCalendarConnector(Connector):
    key = "apple_calendar"
    name = "Apple Calendar (iCloud)"
    domain = Domain.calendar
    is_mock = True  # flips to False once EventKit returns real events

    DAYS_BACK = 30
    DAYS_FORWARD = 60

    def __init__(self) -> None:
        self._reader = EventKitReader() if EVENTKIT_AVAILABLE else None

    # --- access ----------------------------------------------------------- #
    @property
    def available(self) -> bool:
        return EVENTKIT_AVAILABLE and self._reader is not None

    def authorization_status(self) -> int:
        return self._reader.authorization_status() if self._reader else -1

    def request_access(self) -> bool:
        """Trigger the macOS prompt and return whether access was granted."""
        return bool(self._reader and self._reader.request_access())

    def connect(self) -> bool:
        # Always "connected": fetch_raw_data decides real vs mock. This keeps the
        # Calendar module populated (mock) before access is granted, and never
        # forces the macOS prompt on a background sync — the Settings UI calls
        # request_access() explicitly when the user opts in.
        return True

    # --- pipeline --------------------------------------------------------- #
    def fetch_raw_data(self) -> list[dict]:
        if self.available and self._reader.authorization_status() in {3}:
            events = self._reader.fetch_events(
                days_back=self.DAYS_BACK, days_forward=self.DAYS_FORWARD
            )
            if events:
                self.is_mock = False
            return [
                {
                    "ext_id": e.ext_id,
                    "title": e.title,
                    "location": e.location,
                    "calendar_name": e.calendar_name,
                    "starts_at": e.starts_at.isoformat(),
                    "ends_at": e.ends_at.isoformat() if e.ends_at else None,
                    "all_day": e.all_day,
                    "notes": e.notes,
                }
                for e in events
            ]
        # Unavailable / not yet authorised.
        self.is_mock = True
        if get_settings().is_production:
            return []
        return self._mock_events()

    def store_normalised_data(self, session, user_id, source_id, records) -> int:
        seen: set[str] = set()
        written = 0
        for r in records:
            ext_id = r["ext_id"]
            seen.add(ext_id)
            row = session.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.ext_id == ext_id,
                )
            ).first()
            if row is None:
                row = CalendarEvent(user_id=user_id, ext_id=ext_id)
                session.add(row)
            row.title = r["title"]
            row.location = r.get("location")
            row.calendar_name = r.get("calendar_name")
            row.starts_at = _parse_dt(r["starts_at"])
            row.ends_at = _parse_dt(r.get("ends_at"))
            row.all_day = 1 if r.get("all_day") else 0
            row.notes = r.get("notes")
            row.synced_at = datetime.now(timezone.utc)
            written += 1

        # Prune events that fell out of the source window (only on a real sync;
        # never wipe the mirror when the source was simply unavailable).
        if not self.is_mock and seen:
            existing = session.scalars(
                select(CalendarEvent).where(CalendarEvent.user_id == user_id)
            ).all()
            for row in existing:
                if row.ext_id not in seen:
                    session.delete(row)

        session.flush()
        return written

    # --- dev fallback ----------------------------------------------------- #
    def _mock_events(self) -> list[dict]:
        from datetime import timedelta

        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        samples = [
            ("Morning stand-up", "Work", 1, 0.5),
            ("Design review", "Work", 2, 1.0),
            ("Gym", "Personal", -1, 1.0),
            ("Dinner with family", "Personal", 0, 2.0),
            ("Dentist", "Personal", 3, 0.75),
        ]
        out = []
        for i, (title, cal, day_off, hours) in enumerate(samples):
            start = now + timedelta(days=day_off, hours=9 + i)
            out.append(
                {
                    "ext_id": f"mock-{i}",
                    "title": title,
                    "location": None,
                    "calendar_name": cal,
                    "starts_at": start.isoformat(),
                    "ends_at": (start + timedelta(hours=hours)).isoformat(),
                    "all_day": False,
                    "notes": None,
                }
            )
        return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
