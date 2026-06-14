"""Trading 212 connector (placeholder).

Real implementation will call the Trading 212 REST API with a user API key
loaded from the OS keychain. This placeholder emits a mock investment-account
balance series.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class Trading212Connector(Connector):
    key = "trading212"
    name = "Trading 212"
    domain = Domain.finance
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): GET /api/v0/equity/account/cash with API key.
        # TODO(security): load TRADING212_API_KEY from keyring, never log it.
        today = date.today()
        balance = 1_850_000  # minor units, GBP
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            balance += random.randint(-40_000, 55_000)
            out.append(
                {"day": day.isoformat(), "balance_minor": balance, "currency": "GBP"}
            )
        return out
