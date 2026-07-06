"""Thin wrapper around macOS EventKit for reading iCloud/local calendar events.

This is the only place that touches the Objective-C bridge. It is import-safe on
non-macOS platforms (the import guard sets ``EVENTKIT_AVAILABLE = False``), so the
rest of the app — and the test suite — can run anywhere.

We read the same iCloud calendars synced to this Mac, which is the practical way
to reach the user's iOS calendar from Python (there is no direct iOS API). ORION
only ever *reads*; it never writes back to the system calendar.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.logging import get_logger

log = get_logger(__name__)

try:  # pragma: no cover - platform dependent
    import EventKit as _EK  # type: ignore
    from Foundation import NSDate  # type: ignore

    EVENTKIT_AVAILABLE = True
except Exception:  # pragma: no cover - non-macOS / framework missing
    _EK = None
    NSDate = None
    EVENTKIT_AVAILABLE = False


@dataclass
class CalendarEventDTO:
    ext_id: str
    title: str
    location: str | None
    calendar_name: str | None
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    notes: str | None


# EKAuthorizationStatus values (stable across versions):
#   0 notDetermined, 1 restricted, 2 denied, 3 authorized/fullAccess, 4 writeOnly
_AUTH_OK = {3}


def _nsdate(dt: datetime):
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _to_datetime(nsdate) -> datetime | None:
    if nsdate is None:
        return None
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970(), tz=timezone.utc)


class EventKitReader:
    """Reads events from the macOS EventKit store."""

    def __init__(self) -> None:
        self._store = None
        if EVENTKIT_AVAILABLE:
            self._store = _EK.EKEventStore.alloc().init()

    # --- access ----------------------------------------------------------- #
    def authorization_status(self) -> int:
        if not EVENTKIT_AVAILABLE:
            return -1
        return _EK.EKEventStore.authorizationStatusForEntityType_(_EK.EKEntityTypeEvent)

    def request_access(self, timeout: float = 30.0) -> bool:
        """Request calendar access, blocking until the user responds.

        Triggers the macOS permission prompt on first call. Returns True if the
        process is authorized to read events.
        """
        if not EVENTKIT_AVAILABLE:
            return False
        if self.authorization_status() in _AUTH_OK:
            return True

        done = threading.Event()
        result = {"granted": False}

        def _handler(granted, error):  # noqa: ANN001
            result["granted"] = bool(granted)
            if error is not None:
                log.warning("EventKit access error: %s", error)
            done.set()

        # macOS 14+ splits read access into a dedicated call; fall back to the
        # older combined request on earlier systems.
        if hasattr(self._store, "requestFullAccessToEventsWithCompletion_"):
            self._store.requestFullAccessToEventsWithCompletion_(_handler)
        else:  # pragma: no cover - older macOS
            self._store.requestAccessToEntityType_completion_(
                _EK.EKEntityTypeEvent, _handler
            )

        done.wait(timeout)
        granted = result["granted"] or self.authorization_status() in _AUTH_OK
        return granted

    # --- reads ------------------------------------------------------------ #
    def fetch_events(
        self, *, days_back: int = 30, days_forward: int = 60
    ) -> list[CalendarEventDTO]:
        """Return events in [now - days_back, now + days_forward]."""
        if not EVENTKIT_AVAILABLE or self.authorization_status() not in _AUTH_OK:
            return []

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_back)
        end = now + timedelta(days=days_forward)

        calendars = self._store.calendarsForEntityType_(_EK.EKEntityTypeEvent)
        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            _nsdate(start), _nsdate(end), calendars
        )
        ek_events = self._store.eventsMatchingPredicate_(predicate) or []

        out: list[CalendarEventDTO] = []
        for ev in ek_events:
            starts_at = _to_datetime(ev.startDate())
            if starts_at is None:
                continue
            cal = ev.calendar()
            out.append(
                CalendarEventDTO(
                    ext_id=str(ev.eventIdentifier() or ev.calendarItemIdentifier()),
                    title=str(ev.title() or "(untitled)"),
                    location=str(ev.location()) if ev.location() else None,
                    calendar_name=str(cal.title()) if cal else None,
                    starts_at=starts_at,
                    ends_at=_to_datetime(ev.endDate()),
                    all_day=bool(ev.isAllDay()),
                    notes=str(ev.notes()) if ev.notes() else None,
                )
            )
        return out
