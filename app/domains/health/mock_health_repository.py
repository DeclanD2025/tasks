"""Mock Health repository for the ORION biometric dashboard.

This uses the seeded local health/activity read models for signal shape, then
normalises the headline values to the current ORION demo telemetry contract.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app import services
from app.domains.health.health_schema import BioSystemBar, HealthDashboardSnapshot, HealthMetricCard


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _series_from(
    values: list[float], *, fallback_center: float, fallback_spread: float
) -> tuple[float, ...]:
    if values:
        return tuple(float(v) for v in values[-34:])
    return tuple(
        fallback_center
        + math.sin(i * 0.62) * fallback_spread
        + math.sin(i * 0.17 + 1.4) * fallback_spread * 0.42
        for i in range(34)
    )


def _scaled_series(series: tuple[float, ...], center: float, spread: float) -> tuple[float, ...]:
    if not series:
        return _series_from([], fallback_center=center, fallback_spread=spread)
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1.0
    return tuple(center + ((v - lo) / rng - 0.5) * spread for v in series)


class MockHealthRepository:
    """Return the current local mock biometric dashboard snapshot."""

    def dashboard_snapshot(self, user_id: int | None) -> HealthDashboardSnapshot:
        health = services.health_frame(user_id) if user_id else services.health_frame(-1)
        activity = services.activity_frame(user_id) if user_id else services.activity_frame(-1)

        sleep = (
            _series_from(
                (health["sleep_minutes"] / 60).dropna().tolist(),
                fallback_center=7.1,
                fallback_spread=0.28,
            )
            if not health.empty
            else _series_from([], fallback_center=7.1, fallback_spread=0.28)
        )
        hrv = (
            _series_from(
                health["hrv_ms"].dropna().tolist(), fallback_center=61, fallback_spread=5.5
            )
            if not health.empty
            else _series_from([], fallback_center=61, fallback_spread=5.5)
        )
        rhr = (
            _series_from(
                health["resting_hr"].dropna().tolist(), fallback_center=55, fallback_spread=3.2
            )
            if not health.empty
            else _series_from([], fallback_center=55, fallback_spread=3.2)
        )
        weight = (
            _series_from(
                health["weight_kg"].dropna().tolist(), fallback_center=79.0, fallback_spread=0.2
            )
            if not health.empty and "weight_kg" in health
            else _series_from([], fallback_center=79.0, fallback_spread=0.2)
        )
        load = (
            _series_from(
                activity["training_load"].dropna().tolist(), fallback_center=80, fallback_spread=9.0
            )
            if not activity.empty
            else _series_from([], fallback_center=80, fallback_spread=9.0)
        )
        active = (
            _series_from(
                activity["active_minutes"].dropna().tolist(), fallback_center=63, fallback_spread=15
            )
            if not activity.empty
            else _series_from([], fallback_center=63, fallback_spread=15)
        )

        recovery = _scaled_series(hrv, 81.0, 5.8)
        vo2 = _scaled_series(active, 42.2, 2.2)
        readiness = _scaled_series(recovery, 81.0, 4.8)
        live = tuple(
            0.48
            + math.sin(i * 1.7) * 0.15
            + math.sin(i * 0.39) * 0.08
            + (0.12 if i % 13 == 0 else 0.0)
            for i in range(96)
        )

        cards = (
            HealthMetricCard(
                "sleep",
                "Sleep",
                "HLT-SLP",
                "left",
                "7.1",
                "h",
                "89%",
                "Quality",
                0.89,
                "head",
                sleep,
            ),
            HealthMetricCard(
                "hrv", "HRV", "HLT-HRV", "left", "61", "ms", "77%", "Trend", 0.77, "heart", hrv
            ),
            HealthMetricCard(
                "recovery",
                "Recovery",
                "HLT-RCV",
                "left",
                "81",
                "%",
                "+6%",
                "vs yesterday",
                0.81,
                "core",
                recovery,
            ),
            HealthMetricCard(
                "weight",
                "Weight",
                "HLT-WGT",
                "left",
                "79.0",
                "kg",
                "100%",
                "Trend",
                1.0,
                "pelvis",
                weight,
            ),
            HealthMetricCard(
                "rhr", "RHR", "HLT-RHR", "right", "55", "bpm", "79%", "Trend", 0.79, "heart", rhr
            ),
            HealthMetricCard(
                "vo2",
                "VO2 Max",
                "HLT-VO2",
                "right",
                "42.2",
                "ml/kg/min",
                "42%",
                "Percentile",
                0.42,
                "lungs",
                vo2,
            ),
            HealthMetricCard(
                "training_load",
                "Training Load",
                "HLT-LOD",
                "right",
                "80",
                "",
                "High",
                "Status",
                0.80,
                "legs",
                load,
                warning=True,
            ),
            HealthMetricCard(
                "readiness",
                "Readiness",
                "HLT-RDY",
                "right",
                "81",
                "%",
                "Stable",
                "Trend",
                0.81,
                "base",
                readiness,
            ),
        )

        now = datetime.now(UTC)
        last_sync = now.replace(second=max(0, now.second - 26), microsecond=0)
        return HealthDashboardSnapshot(
            title="Health Telemetry",
            subtitle="Biometric Scan  •  Live Feed",
            scan_status="LIVE",
            sync_status="ONLINE",
            database_status="DB LOCAL",
            last_sync_time=last_sync.strftime("%H:%M:%S UTC"),
            last_sync_date=last_sync.strftime("%d %b %Y").upper(),
            data_sources_online=9,
            data_sources_total=9,
            anomaly_count=0,
            body_battery_value="72",
            body_battery_status="Good",
            metric_cards=cards,
            bio_systems=(
                BioSystemBar("Heart", 79),
                BioSystemBar("Respiratory", 72),
                BioSystemBar("Nervous", 82),
                BioSystemBar("Muscular", 76),
                BioSystemBar("Skeletal", 84),
                BioSystemBar("Hormonal", 71),
                BioSystemBar("Immune", 78),
            ),
            live_feed=live,
        )
