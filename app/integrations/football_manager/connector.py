"""Football Manager connector (placeholder).

Real implementation will parse exported FM data (e.g. RTF/HTML squad & match
exports) locally. This placeholder emits mock match/training records for the
Football module.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class FootballManagerConnector(Connector):
    key = "football_manager"
    name = "Football Manager"
    domain = Domain.football
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): parse FM export files (RTF/HTML) locally.
        today = date.today()
        results = ["W", "W", "D", "L", "W", "D"]
        out = []
        for i in range(0, 30, 4):  # roughly twice a week
            day = today - timedelta(days=i)
            out.append(
                {
                    "day": day.isoformat(),
                    "result": random.choice(results),
                    "goals_for": random.randint(0, 4),
                    "goals_against": random.randint(0, 3),
                    "training_load": round(random.uniform(40, 95), 1),
                }
            )
        return out
