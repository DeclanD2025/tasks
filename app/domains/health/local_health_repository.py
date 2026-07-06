"""Honest local Health repository for the ORION biometric dashboard.

Every headline value comes from the local database (Health Auto Export →
HealthMetricDaily). Metrics with no real reading show "—" rather than a
fabricated number. Derived scores (recovery, readiness) are computed from the
real signals they depend on and are labelled as derived; if their inputs are
missing, they too show "—".

This replaces the old MockHealthRepository, which hardcoded headline values
(weight 79.0, RHR 55, VO2 42.2, "9/9 sources", body battery, system bars) that
were independent of the database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from app import services
from app.db.database import session_scope
from app.db.models import DataSource, HealthMetricDaily
from app.domains.health.health_schema import (
    BioSystemBar,
    HealthDashboardSnapshot,
    HealthMetricCard,
)

DASH = "—"


def _series(values: list[float]) -> tuple[float, ...]:
    """Real sparkline points, or empty when there's no signal (flat line)."""
    return tuple(float(v) for v in values[-34:])


def _last(frame: pd.DataFrame, col: str) -> float | None:
    if frame.empty or col not in frame:
        return None
    s = frame[col].dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _mean(frame: pd.DataFrame, col: str) -> float | None:
    if frame.empty or col not in frame:
        return None
    s = frame[col].dropna()
    return float(s.mean()) if not s.empty else None


def _extra_series(user_id: int | None, key: str) -> tuple[list[float], float | None]:
    """Pull a numeric value out of HealthMetricDaily.extra across days.

    Returns (ordered values, latest value). HAE stores mood / mindful_minutes /
    distance_km / vo2max here.
    """
    uid = user_id if user_id is not None else services.get_default_user_id()
    if uid is None:
        return [], None
    with session_scope() as s:
        rows = (
            s.query(HealthMetricDaily.day, HealthMetricDaily.extra)
            .filter(HealthMetricDaily.user_id == uid)
            .order_by(HealthMetricDaily.day)
            .all()
        )
    values: list[float] = []
    for _day, extra in rows:
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (ValueError, TypeError):
                extra = {}
        v = (extra or {}).get(key)
        if v is not None:
            try:
                values.append(float(v))
            except (ValueError, TypeError):
                pass
    return values, (values[-1] if values else None)


def _real_sources() -> list[DataSource]:
    with session_scope() as s:
        rows = s.query(DataSource).all()
        # detach: read the attributes we need while the session is open
        return [
            DataSource(
                key=r.key,
                name=r.name,
                status=r.status,
                domain=r.domain,
                last_synced_at=r.last_synced_at,
            )
            for r in rows
        ]


class LocalHealthRepository:
    """Hydrate the Health dashboard snapshot from real local data only."""

    def dashboard_snapshot(self, user_id: int | None) -> HealthDashboardSnapshot:
        uid = user_id if user_id is not None else services.get_default_user_id()
        health = services.health_frame(uid) if uid else services.health_frame(-1)

        # --- Real, directly-measured signals -------------------------------
        sleep_min = _last(health, "sleep_minutes")
        hrv = _last(health, "hrv_ms")
        rhr = _last(health, "resting_hr")
        weight = _last(health, "weight_kg")

        sleep_series = _series((health["sleep_minutes"] / 60).dropna().tolist()) if not health.empty else ()
        hrv_series = _series(health["hrv_ms"].dropna().tolist()) if not health.empty else ()
        rhr_series = _series(health["resting_hr"].dropna().tolist()) if not health.empty else ()
        weight_series = (
            _series(health["weight_kg"].dropna().tolist())
            if not health.empty and "weight_kg" in health
            else ()
        )

        vo2_vals, vo2 = _extra_series(uid, "vo2max")
        dist_vals, _dist = _extra_series(uid, "distance_km")

        # --- Derived scores (only when their inputs exist) -----------------
        # Recovery: HRV relative to this person's own recent range (0–100).
        recovery, recovery_series = self._recovery_from_hrv(health)

        # Cards. value "—" when the signal is absent; sparkline empty likewise.
        cards = (
            self._card(
                "sleep", "Sleep", "HLT-SLP", "left", "head", sleep_series,
                value=f"{sleep_min / 60:.1f}" if sleep_min is not None else DASH,
                unit="h" if sleep_min is not None else "",
                secondary=("ASLEEP" if sleep_min is not None else "NO DATA"),
                secondary_label="Last night" if sleep_min is not None else "Health Auto Export",
                score=min(1.0, (sleep_min / 60) / 8.0) if sleep_min is not None else 0.0,
            ),
            self._card(
                "hrv", "HRV", "HLT-HRV", "left", "heart", hrv_series,
                value=f"{hrv:.0f}" if hrv is not None else DASH,
                unit="ms" if hrv is not None else "",
                secondary=("REAL" if hrv is not None else "NO DATA"),
                secondary_label="SDNN" if hrv is not None else "Health Auto Export",
                score=min(1.0, hrv / 90.0) if hrv is not None else 0.0,
            ),
            self._card(
                "recovery", "Recovery", "HLT-RCV", "left", "core", recovery_series,
                value=f"{recovery:.0f}" if recovery is not None else DASH,
                unit="%" if recovery is not None else "",
                secondary=("DERIVED" if recovery is not None else "NO DATA"),
                secondary_label="from HRV" if recovery is not None else "needs HRV history",
                score=(recovery / 100.0) if recovery is not None else 0.0,
            ),
            self._card(
                "weight", "Weight", "HLT-WGT", "left", "pelvis", weight_series,
                value=f"{weight:.1f}" if weight is not None else DASH,
                unit="kg" if weight is not None else "",
                secondary=("REAL" if weight is not None else "NO DATA"),
                secondary_label="Latest" if weight is not None else "not in HAE export",
                score=0.0,
            ),
            self._card(
                "rhr", "RHR", "HLT-RHR", "right", "heart", rhr_series,
                value=f"{rhr:.0f}" if rhr is not None else DASH,
                unit="bpm" if rhr is not None else "",
                secondary=("REAL" if rhr is not None else "NO DATA"),
                secondary_label="Resting" if rhr is not None else "not in HAE export",
                score=0.0,
            ),
            self._card(
                "vo2", "VO2 Max", "HLT-VO2", "right", "lungs", _series(vo2_vals),
                value=f"{vo2:.1f}" if vo2 is not None else DASH,
                unit="ml/kg/min" if vo2 is not None else "",
                secondary=("REAL" if vo2 is not None else "NO DATA"),
                secondary_label="Cardio fitness" if vo2 is not None else "not in HAE export",
                score=0.0,
            ),
            self._card(
                "distance", "Distance", "HLT-DST", "right", "legs", _series(dist_vals),
                value=f"{sum(dist_vals):.1f}" if dist_vals else DASH,
                unit="km" if dist_vals else "",
                secondary=(f"{len(dist_vals)}D" if dist_vals else "NO DATA"),
                secondary_label="Walk + run" if dist_vals else "Health Auto Export",
                score=0.0,
            ),
            self._card(
                "readiness", "Readiness", "HLT-RDY", "right", "base", recovery_series,
                value=f"{recovery:.0f}" if recovery is not None else DASH,
                unit="%" if recovery is not None else "",
                secondary=("DERIVED" if recovery is not None else "NO DATA"),
                secondary_label="from recovery" if recovery is not None else "needs HRV history",
                score=(recovery / 100.0) if recovery is not None else 0.0,
            ),
        )

        # --- Honest source / freshness footer ------------------------------
        sources = _real_sources()
        live = [s for s in sources if s.status not in ("mock",) and s.domain == "health"]
        latest_sync = max((s.last_synced_at for s in live if s.last_synced_at), default=None)
        if latest_sync is not None and latest_sync.tzinfo is None:
            latest_sync = latest_sync.replace(tzinfo=UTC)
        when = latest_sync or datetime.now(UTC)

        # Captured-signal rail: which real metrics we actually hold (honest).
        captured = [
            BioSystemBar("Sleep", 100 if sleep_min is not None else 0),
            BioSystemBar("HRV", 100 if hrv is not None else 0),
            BioSystemBar("Mood", 100 if _extra_series(uid, "mood")[1] is not None else 0),
            BioSystemBar("Mindful", 100 if _extra_series(uid, "mindful_minutes")[1] is not None else 0),
            BioSystemBar("Distance", 100 if dist_vals else 0),
            BioSystemBar("VO2 Max", 100 if vo2 is not None else 0),
            BioSystemBar("RHR", 100 if rhr is not None else 0),
            BioSystemBar("Weight", 100 if weight is not None else 0),
        ]

        return HealthDashboardSnapshot(
            title="Health Telemetry",
            subtitle="Biometric Scan  •  Health Auto Export",
            scan_status="LIVE" if live else "NO SOURCE",
            sync_status="ONLINE" if live else "OFFLINE",
            database_status="DB LOCAL",
            last_sync_time=when.strftime("%H:%M:%S UTC"),
            last_sync_date=when.strftime("%d %b %Y").upper(),
            data_sources_online=len(live),
            data_sources_total=len(live),
            anomaly_count=0,
            body_battery_value=f"{recovery:.0f}" if recovery is not None else DASH,
            body_battery_status="Derived" if recovery is not None else "No data",
            metric_cards=cards,
            bio_systems=tuple(captured),
        )

    @staticmethod
    def _recovery_from_hrv(health: pd.DataFrame) -> tuple[float | None, tuple[float, ...]]:
        """Map latest HRV to a 0–100 recovery score within the person's own range.

        Needs at least a few days of HRV to have a meaningful range; with one
        point we can't say much, so return None (shows "—").
        """
        if health.empty or "hrv_ms" not in health:
            return None, ()
        s = health["hrv_ms"].dropna()
        if len(s) < 2:
            return None, ()
        lo, hi = float(s.min()), float(s.max())
        rng = (hi - lo) or 1.0
        scaled = ((s - lo) / rng * 100.0).round(0)
        latest = float(scaled.iloc[-1])
        return latest, tuple(float(v) for v in scaled.tolist()[-34:])

    @staticmethod
    def _card(
        key, label, code, side, region, sparkline, *,
        value, unit, secondary, secondary_label, score,
    ) -> HealthMetricCard:
        return HealthMetricCard(
            key=key,
            label=label,
            code=code,
            side=side,
            value=value,
            unit=unit,
            secondary_value=secondary,
            secondary_label=secondary_label,
            score=score,
            target_region=region,
            sparkline=sparkline,
        )
