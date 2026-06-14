"""ActivityWatch connector (placeholder).

ActivityWatch runs a local REST server (default http://localhost:5600) exposing
window/AFK buckets. Real implementation will query that local API — fully
local-first, no cloud.

This placeholder emits mock daily deep-work / active-minute records.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class ActivityWatchConnector(Connector):
    key = "activitywatch"
    name = "ActivityWatch"
    domain = Domain.productivity
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): query local ActivityWatch buckets at :5600.
        today = date.today()
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            weekday = day.weekday() < 5
            out.append(
                {
                    "day": day.isoformat(),
                    "deep_work_minutes": random.randint(120, 300)
                    if weekday
                    else random.randint(0, 90),
                    "active_minutes": random.randint(20, 90),
                    "steps": random.randint(3000, 12000),
                }
            )
        return out
