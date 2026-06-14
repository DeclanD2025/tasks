"""Coinbase connector (placeholder).

Real implementation will use the Coinbase API (API key + secret, or OAuth) to
read account balances. This placeholder emits a mock crypto balance series.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class CoinbaseConnector(Connector):
    key = "coinbase"
    name = "Coinbase"
    domain = Domain.finance
    is_mock = True

    def fetch_raw_data(self) -> list[dict]:
        # TODO(integration): call Coinbase /v2/accounts with signed requests.
        # TODO(security): load API key+secret from keyring; never log secrets.
        today = date.today()
        balance = 420_000
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            balance += random.randint(-60_000, 70_000)
            out.append(
                {"day": day.isoformat(), "balance_minor": max(0, balance), "currency": "GBP"}
            )
        return out
