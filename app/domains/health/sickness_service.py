"""Sickness protocol — wellbeing status + daily symptom log.

The user sets a wellbeing status (Active / Injured / Illness). When ill, ORION
prompts for a daily symptom entry (severity + checklist + note) and the Health
page accent shifts toward red. The symptom log can be reviewed alongside the
day's vitals (sleep, resting HR, HRV) to see how the body tracked the illness.

This module owns the read/write models; the UI and the biometric canvas read
``current_status`` and ``illness_intensity`` to drive their colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import desc, select

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import (
    HealthMetricDaily,
    HealthStatus,
    HealthStatusLog,
    SymptomEntry,
    SymptomSeverity,
)

log = get_logger(__name__)


# The daily symptom checklist. Stable keys (stored) + display labels.
SYMPTOM_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("sore_throat", "Sore throat"),
    ("cough", "Cough"),
    ("fever", "Fever"),
    ("fatigue", "Fatigue"),
    ("headache", "Headache"),
    ("congestion", "Congestion"),
    ("body_aches", "Body aches"),
    ("nausea", "Nausea"),
)
_SYMPTOM_LABELS = dict(SYMPTOM_CHECKLIST)

# How red the page gets per severity (0.0 = full blue, 1.0 = full red).
_SEVERITY_INTENSITY = {
    SymptomSeverity.mild: 0.45,
    SymptomSeverity.moderate: 0.72,
    SymptomSeverity.severe: 1.0,
}


@dataclass(frozen=True)
class SymptomLogRow:
    day: date
    severity: SymptomSeverity
    symptoms: list[str]
    note: str | None
    # The day's vitals, shown beside the entry.
    sleep_hours: float | None
    resting_hr: int | None
    hrv_ms: float | None

    @property
    def symptom_labels(self) -> list[str]:
        return [_SYMPTOM_LABELS.get(k, k) for k in self.symptoms]


@dataclass(frozen=True)
class SicknessSnapshot:
    status: HealthStatus
    status_note: str | None
    is_ill: bool
    # 0.0 (blue) .. 1.0 (full red). Only non-zero when ill.
    illness_intensity: float
    days_ill: int
    needs_symptom_entry_today: bool
    today_entry: SymptomLogRow | None
    log: list[SymptomLogRow] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def current_status(user_id: int) -> tuple[HealthStatus, str | None]:
    """Return the user's most recent status and its note (default Active)."""
    with session_scope() as s:
        row = s.scalars(
            select(HealthStatusLog)
            .where(HealthStatusLog.user_id == user_id)
            .order_by(desc(HealthStatusLog.effective_from), desc(HealthStatusLog.id))
            .limit(1)
        ).first()
        if row is None:
            return HealthStatus.active, None
        return row.status, row.note


def set_status(
    user_id: int,
    status: HealthStatus,
    *,
    note: str | None = None,
    on: date | None = None,
) -> None:
    """Set today's status (idempotent per day — updates the day's row)."""
    on = on or date.today()
    with session_scope() as s:
        row = s.scalars(
            select(HealthStatusLog).where(
                HealthStatusLog.user_id == user_id,
                HealthStatusLog.effective_from == on,
            )
        ).first()
        if row is None:
            row = HealthStatusLog(user_id=user_id, effective_from=on)
            s.add(row)
        row.status = status
        row.note = note
    log.info("Health status set to %s for user %s", status.value, user_id)


def days_ill(user_id: int) -> int:
    """Consecutive days (including today) the current illness has run."""
    with session_scope() as s:
        rows = s.scalars(
            select(HealthStatusLog)
            .where(HealthStatusLog.user_id == user_id)
            .order_by(desc(HealthStatusLog.effective_from), desc(HealthStatusLog.id))
        ).all()
    if not rows or rows[0].status != HealthStatus.illness:
        return 0
    count = 0
    for r in rows:
        if r.status == HealthStatus.illness:
            count += 1
        else:
            break
    return count


# --------------------------------------------------------------------------- #
# Symptoms
# --------------------------------------------------------------------------- #
def upsert_symptom_entry(
    user_id: int,
    *,
    severity: SymptomSeverity,
    symptoms: list[str],
    note: str | None = None,
    day: date | None = None,
) -> None:
    """Record (or update) today's symptom entry."""
    day = day or date.today()
    clean = [k for k in symptoms if k in _SYMPTOM_LABELS]
    with session_scope() as s:
        row = s.scalars(
            select(SymptomEntry).where(
                SymptomEntry.user_id == user_id, SymptomEntry.day == day
            )
        ).first()
        if row is None:
            row = SymptomEntry(user_id=user_id, day=day)
            s.add(row)
        row.severity = severity
        row.symptoms = clean
        row.note = (note or "").strip() or None


def _vitals_by_day(user_id: int) -> dict[date, tuple[float | None, int | None, float | None]]:
    with session_scope() as s:
        rows = s.execute(
            select(
                HealthMetricDaily.day,
                HealthMetricDaily.sleep_minutes,
                HealthMetricDaily.resting_hr,
                HealthMetricDaily.hrv_ms,
            ).where(HealthMetricDaily.user_id == user_id)
        ).all()
    out: dict[date, tuple[float | None, int | None, float | None]] = {}
    for day, sleep_min, rhr, hrv in rows:
        sleep_hours = round(sleep_min / 60.0, 1) if sleep_min is not None else None
        out[day] = (sleep_hours, rhr, hrv)
    return out


def symptom_log(user_id: int, *, limit: int = 30) -> list[SymptomLogRow]:
    """The symptom log, newest first, each joined to that day's vitals."""
    vitals = _vitals_by_day(user_id)
    with session_scope() as s:
        rows = s.scalars(
            select(SymptomEntry)
            .where(SymptomEntry.user_id == user_id)
            .order_by(desc(SymptomEntry.day))
            .limit(limit)
        ).all()
        entries = [
            (r.day, r.severity, list(r.symptoms or []), r.note) for r in rows
        ]
    out: list[SymptomLogRow] = []
    for day, severity, symptoms, note in entries:
        sleep_h, rhr, hrv = vitals.get(day, (None, None, None))
        out.append(
            SymptomLogRow(
                day=day,
                severity=severity,
                symptoms=symptoms,
                note=note,
                sleep_hours=sleep_h,
                resting_hr=rhr,
                hrv_ms=hrv,
            )
        )
    return out


def get_sickness_snapshot(user_id: int) -> SicknessSnapshot:
    """Everything the Health page needs to drive the sickness protocol."""
    status, note = current_status(user_id)
    is_ill = status == HealthStatus.illness
    full_log = symptom_log(user_id)
    today = date.today()
    today_entry = next((r for r in full_log if r.day == today), None)

    intensity = 0.0
    if is_ill:
        # Status drives the red ON; severity of today's entry modulates how deep
        # the wash goes. No entry yet today -> a sensible default lean-red.
        if today_entry is not None:
            intensity = _SEVERITY_INTENSITY.get(today_entry.severity, 0.6)
        else:
            intensity = 0.6

    return SicknessSnapshot(
        status=status,
        status_note=note,
        is_ill=is_ill,
        illness_intensity=intensity,
        days_ill=days_ill(user_id) if is_ill else 0,
        needs_symptom_entry_today=is_ill and today_entry is None,
        today_entry=today_entry,
        log=full_log,
    )
