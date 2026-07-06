from __future__ import annotations

from app import services
from app.domains.health.health_service import get_health_dashboard_snapshot

DASH = "—"


def test_health_dashboard_snapshot_shape():
    uid = services.get_default_user_id()
    snapshot = get_health_dashboard_snapshot(uid)

    assert snapshot.title == "Health Telemetry"
    assert snapshot.database_status == "DB LOCAL"
    assert snapshot.anomaly_count == 0
    # Source count reflects REAL health sources only (never the 9 mock seeds).
    assert snapshot.data_sources_online == snapshot.data_sources_total
    assert snapshot.data_sources_online <= 1
    assert len(snapshot.metric_cards) == 8
    assert len(snapshot.bio_systems) == 8

    labels = {card.label for card in snapshot.metric_cards}
    assert labels == {
        "Sleep",
        "HRV",
        "Recovery",
        "Weight",
        "RHR",
        "VO2 Max",
        "Distance",
        "Readiness",
    }


def test_values_track_the_database_not_constants():
    """Headline values are derived from the DB: a metric with no stored reading
    shows "—" with an empty sparkline, never an invented number."""
    uid = services.get_default_user_id()
    snapshot = get_health_dashboard_snapshot(uid)
    health = services.health_frame(uid)

    cards = {c.label: c for c in snapshot.metric_cards}

    def has(col: str) -> bool:
        return not health.empty and col in health and not health[col].dropna().empty

    # If the DB lacks a column entirely, the card must be NO DATA.
    for label, col in (("Weight", "weight_kg"), ("RHR", "resting_hr")):
        c = cards[label]
        if not has(col):
            assert c.value == DASH, label
            assert c.secondary_value == "NO DATA"
            assert c.sparkline == ()

    # When sleep IS present, the value matches the latest stored reading.
    if has("sleep_minutes"):
        latest = float(health["sleep_minutes"].dropna().iloc[-1])
        assert cards["Sleep"].value == f"{latest / 60:.1f}"
