"""Notion connector (placeholder).

Real implementation will use the Notion API (integration token) to read pages /
databases tracking writing output, tasks, and learning. This placeholder emits
mock daily writing / task records.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class NotionConnector(Connector):
    key = "notion"
    name = "Notion"
    domain = Domain.creative
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): query Notion databases via the official API.
        # TODO(security): load NOTION_TOKEN from keyring.
        today = date.today()
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            out.append(
                {
                    "day": day.isoformat(),
                    "words_written": random.randint(0, 1800),
                    "tasks_done": random.randint(0, 9),
                }
            )
        return out
