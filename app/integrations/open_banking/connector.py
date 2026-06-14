"""Open Banking / GoCardless connector (placeholder).

IMPORTANT (security): Open Banking access uses OAuth + explicit user consent.
ORION must NEVER store bank login credentials. Real implementation will redirect
the user through the bank's consent flow and store only short-lived access
tokens in the OS keychain.

This placeholder emits mock current-account transactions and balances.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.db.models import Domain
from app.ingestion.base import Connector


class OpenBankingConnector(Connector):
    key = "open_banking"
    name = "Open Banking (GoCardless)"
    domain = Domain.finance
    is_mock = True

    def connect(self) -> bool:
        # TODO(integration): perform GoCardless Bank Account Data OAuth/consent.
        # TODO(security): load token via keyring, never persist credentials.
        return True

    def fetch_raw_data(self) -> list[dict]:
        today = date.today()
        merchants = [
            ("Tesco", "groceries", -3500),
            ("Pret", "eating_out", -650),
            ("Spotify", "subscriptions", -1199),
            ("Salary", "income", 250000),
            ("TfL", "transport", -540),
        ]
        out = []
        for i in range(30):
            day = today - timedelta(days=i)
            name, cat, base = random.choice(merchants)
            jitter = 0 if cat == "income" else random.randint(-300, 300)
            out.append(
                {
                    "date": day.isoformat(),
                    "merchant": name,
                    "category": cat,
                    "amount_minor": base + jitter,
                    "currency": "GBP",
                }
            )
        return out
