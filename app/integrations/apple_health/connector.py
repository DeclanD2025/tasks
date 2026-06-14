"""Apple Health connector (placeholder).

Apple Health has no cloud API; data arrives as an `export.xml` the user shares
from the Health app. Real implementation will parse that export locally.

This placeholder emits mock daily sleep / HRV / resting-HR records.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class AppleHealthConnector(Connector):
    key = "apple_health"
    name = "Apple Health"
    domain = Domain.health
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): parse a user-provided Health export.xml locally.
        today = date.today()
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            out.append(
                {
                    "day": day.isoformat(),
                    "sleep_minutes": random.randint(360, 510),
                    "hrv_ms": round(random.uniform(38, 78), 1),
                    "resting_hr": random.randint(48, 62),
                    "weight_kg": round(random.uniform(78.0, 80.5), 1),
                }
            )
        return out
