from __future__ import annotations

from app import services
from app.db.database import session_scope
from app.db.models import ActivityMetricDaily
from app.domains.health.health_service import get_health_dashboard_snapshot
from app.domains.personal_os import get_recovery_snapshot

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


def test_recovery_snapshot_limits_primary_signals_to_three():
    uid = services.get_default_user_id()
    recovery = get_recovery_snapshot(uid)
    assert len(recovery.metrics) >= 3
    primary_labels = {m.label for m in recovery.metrics[:3]}
    expected = {"Sleep", "HRV", "Resting HR"}
    assert expected <= primary_labels, primary_labels


def test_score_factor_delta_is_signed_deviation_from_neutral():
    from app.domains.personal_os import ScoreFactor

    factor = ScoreFactor("Sleep", "7h 30m", "personal need", 75.0)
    assert factor.delta == 25.0

    negative = ScoreFactor("Sleep", "5h", "personal need", 35.0)
    assert negative.delta == -15.0


def test_partial_day_metrics_are_flagged_for_today():
    """Metrics whose latest reading is today are flagged as partial."""
    from datetime import date

    uid = services.get_default_user_id()
    today = date.today()

    with session_scope() as s:
        existing = s.query(ActivityMetricDaily).filter_by(user_id=uid, day=today).first()
        if existing:
            existing.steps = 1000
        else:
            s.add(ActivityMetricDaily(user_id=uid, day=today, steps=1000))

    recovery = get_recovery_snapshot(uid)
    steps = next((m for m in recovery.metrics if m.label == "Steps"), None)
    assert steps is not None
    assert steps.is_partial_day is True
    assert "not over yet" in steps.interpretation


def test_blood_pressure_metric_combines_systolic_and_diastolic():
    from datetime import date

    from app.db.database import session_scope
    from app.db.models import HealthMetricDaily

    uid = services.get_default_user_id()
    with session_scope() as s:
        row = s.query(HealthMetricDaily).filter_by(user_id=uid, day=date.today()).first()
        if row is None:
            row = HealthMetricDaily(user_id=uid, day=date.today())
            s.add(row)
        row.extra = {**(row.extra or {}), "bp_systolic": 120, "bp_diastolic": 80}

    recovery = get_recovery_snapshot(uid)
    bp = next((m for m in recovery.metrics if m.label == "Blood Pressure"), None)
    assert bp is not None
    assert bp.value == "120/80 mmHg"
    assert bp.quality == "real"
