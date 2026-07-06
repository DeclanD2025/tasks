"""Moneybox connector (placeholder).

Moneybox has no official public API; real implementation may rely on a
user-provided export or an unofficial endpoint. This placeholder emits a mock
savings balance series.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class MoneyboxConnector(Connector):
    key = "moneybox"
    name = "LISA / Moneybox"
    domain = Domain.finance
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): ingest a Moneybox export or supported endpoint.
        today = date.today()
        balance = 980_000
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            balance += random.randint(0, 8_000)  # round-ups + deposits trend up
            out.append(
                {"day": day.isoformat(), "balance_minor": balance, "currency": "GBP"}
            )
        return out
