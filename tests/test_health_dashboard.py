from __future__ import annotations

from app import services
from app.domains.health.health_service import get_health_dashboard_snapshot


def test_health_dashboard_snapshot_shape():
    uid = services.get_default_user_id()
    snapshot = get_health_dashboard_snapshot(uid)

    assert snapshot.title == "Health Telemetry"
    assert snapshot.scan_status == "LIVE"
    assert snapshot.sync_status == "ONLINE"
    assert snapshot.database_status == "DB LOCAL"
    assert snapshot.anomaly_count == 0
    assert snapshot.data_sources_online == 9
    assert snapshot.data_sources_total == 9
    assert snapshot.body_battery_value == "72"
    assert len(snapshot.metric_cards) == 8
    assert len(snapshot.bio_systems) == 7

    labels = {card.label for card in snapshot.metric_cards}
    assert labels == {
        "Sleep",
        "HRV",
        "Recovery",
        "Weight",
        "RHR",
        "VO2 Max",
        "Training Load",
        "Readiness",
    }
    assert all(card.sparkline for card in snapshot.metric_cards)
