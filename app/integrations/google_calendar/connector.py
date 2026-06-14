"""Google Calendar connector (placeholder).

Real implementation will use the Google Calendar API via OAuth. This
placeholder emits mock daily calendar-load records (meeting minutes / event
counts) for the Calendar module.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class GoogleCalendarConnector(Connector):
    key = "google_calendar"
    name = "Google Calendar"
    domain = Domain.calendar
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): OAuth + Calendar API events.list.
        # TODO(security): store OAuth credentials in keyring, never in the DB.
        today = date.today()
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            weekday = day.weekday() < 5
            out.append(
                {
                    "day": day.isoformat(),
                    "events": random.randint(2, 8) if weekday else random.randint(0, 2),
                    "meeting_minutes": random.randint(60, 300)
                    if weekday
                    else random.randint(0, 60),
                }
            )
        return out
