from __future__ import annotations

from app.ingestion import iter_connectors
from app.ingestion.base import Connector


EXPECTED_KEYS = {
    "open_banking", "trading212", "coinbase", "moneybox", "apple_health",
    "activitywatch", "google_calendar", "notion", "football_manager",
    "health_auto_export",
}


def test_all_expected_connectors_registered():
    keys = {c.key for c in iter_connectors()}
    assert EXPECTED_KEYS.issubset(keys)


# Connectors that now query a real source (and fall back to mock when the
# source is unavailable) rather than being mock-only.
LIVE_CAPABLE = {"activitywatch", "apple_health", "health_auto_export"}


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


def test_live_capable_connectors_emit_tagged_rows():
    # Each live-capable connector always yields rows tagged with a 'source'.
    # If a real source happens to be configured on this machine it'll be live
    # (is_mock False); otherwise it falls back to mock cleanly. Either is valid —
    # we only assert the contract: rows exist, are tagged, and is_mock matches
    # availability.
    from app.ingestion import get_connector

    for key in LIVE_CAPABLE:
        c = get_connector(key)
        available = c.connect()
        rows = c.fetch_raw_data()
        assert rows and all("source" in r for r in rows), key
        # mock flag must be the inverse of a real source being present
        assert c.is_mock == (not available), key
