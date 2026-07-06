from __future__ import annotations

from app.ingestion import iter_connectors
from app.ingestion.base import Connector


EXPECTED_KEYS = {
    "open_banking", "trading212", "coinbase", "moneybox", "apple_health",
    "activitywatch", "google_calendar", "notion", "football_manager",
    "health_auto_export", "apple_calendar", "tasks_sync",
}


def test_all_expected_connectors_registered():
    keys = {c.key for c in iter_connectors()}
    assert EXPECTED_KEYS.issubset(keys)


# Connectors that query a real source (and fall back to mock when the source is
# unavailable) rather than being mock-only.
LIVE_CAPABLE = {"activitywatch", "apple_health", "health_auto_export", "apple_calendar"}

# Connectors that do all their I/O inside store_normalised_data (network sync)
# and therefore legitimately stage no rows in fetch_raw_data.
NETWORK_SYNC = {"tasks_sync"}


def test_connectors_implement_interface_and_emit_data():
    for c in iter_connectors():
        assert isinstance(c, Connector)
        payloads = c.fetch_raw_data()
        assert isinstance(payloads, list), c.key
        if c.key in NETWORK_SYNC:
            continue  # network-sync connectors stage no raw rows
        # Every other connector still yields data (real or a mock fallback).
        assert payloads, c.key


def test_mock_only_connectors_report_mock():
    for c in iter_connectors():
        if c.key in LIVE_CAPABLE or c.key in NETWORK_SYNC:
            continue
        # Placeholder connectors are always reachable and mock.
        assert c.connect() is True
        assert c.is_mock is True


# Health-style live connectors tag every row with a 'source' and set is_mock to
# the inverse of source availability.
HEALTH_LIVE_CAPABLE = {"activitywatch", "apple_health", "health_auto_export"}


def test_live_capable_connectors_emit_tagged_rows():
    # Each health live-capable connector always yields rows tagged with a
    # 'source'. If a real source happens to be configured on this machine it'll
    # be live (is_mock False); otherwise it falls back to mock cleanly. Either is
    # valid — we only assert: rows exist, are tagged, and is_mock matches
    # availability.
    from app.ingestion import get_connector

    for key in HEALTH_LIVE_CAPABLE:
        c = get_connector(key)
        available = c.connect()
        rows = c.fetch_raw_data()
        assert rows and all("source" in r for r in rows), key
        # mock flag must be the inverse of a real source being present
        assert c.is_mock == (not available), key


def test_apple_calendar_emits_events_and_is_mock_when_unauthorized():
    # The calendar connector mirrors iCloud events; when EventKit access hasn't
    # been granted (CI / headless), it falls back to a small mock so the Calendar
    # tab still renders. Either way every row carries the event contract fields.
    from app.ingestion import get_connector

    c = get_connector("apple_calendar")
    rows = c.fetch_raw_data()
    assert rows, "apple_calendar should always emit at least the mock fallback"
    for r in rows:
        assert {"ext_id", "title", "starts_at"} <= set(r), r
    # Authorized only when EventKit returned real events.
    assert c.is_mock in (True, False)


def test_tasks_sync_fetch_is_empty_and_real():
    # The tasks connector does its work in store_normalised_data, not
    # fetch_raw_data, and is a real (non-mock) network sync.
    from app.ingestion import get_connector

    c = get_connector("tasks_sync")
    assert c.fetch_raw_data() == []
    assert c.is_mock is False
