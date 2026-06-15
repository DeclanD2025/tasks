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


# Connectors that now query a real source (and fall back to mock when the
# source is unavailable) rather than being mock-only.
LIVE_CAPABLE = {"activitywatch"}


def test_connectors_implement_interface_and_emit_data():
    for c in iter_connectors():
        assert isinstance(c, Connector)
        # Every connector still yields data (real or, in dev, a mock fallback).
        payloads = c.fetch_raw_data()
        assert isinstance(payloads, list) and payloads, c.key


def test_mock_only_connectors_report_mock():
    for c in iter_connectors():
        if c.key in LIVE_CAPABLE:
            continue
        # Placeholder connectors are always reachable and mock.
        assert c.connect() is True
        assert c.is_mock is True


def test_live_capable_connector_falls_back_cleanly():
    # ActivityWatch isn't running in CI/dev: connect() is False, but it still
    # emits a mock fallback and flags itself as mock.
    from app.ingestion import get_connector

    aw = get_connector("activitywatch")
    aw.connect()  # probes localhost:5600; expected unavailable here
    rows = aw.fetch_raw_data()
    assert rows and all("source" in r for r in rows)
