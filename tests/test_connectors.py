from __future__ import annotations

from app.ingestion import iter_connectors
from app.ingestion.base import Connector


EXPECTED_KEYS = {
    "open_banking", "trading212", "coinbase", "moneybox", "apple_health",
    "activitywatch", "google_calendar", "notion", "football_manager",
}


def test_all_expected_connectors_registered():
    keys = {c.key for c in iter_connectors()}
    assert EXPECTED_KEYS.issubset(keys)


def test_connectors_implement_interface_and_emit_mock_data():
    for c in iter_connectors():
        assert isinstance(c, Connector)
        assert c.connect() is True
        payloads = c.fetch_raw_data()
        assert isinstance(payloads, list) and payloads, c.key
        assert c.is_mock is True  # scaffold phase: mock only, no live calls
