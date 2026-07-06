from __future__ import annotations

from datetime import date, timedelta

from app import services
from app.db.database import session_scope
from app.db.models import HealthMetricDaily, HealthStatus, SymptomSeverity
from app.domains.health import sickness_service as sk


def _uid() -> int:
    return services.get_default_user_id()


def _reset(uid: int) -> None:
    from app.db.models import HealthStatusLog, SymptomEntry

    with session_scope() as s:
        s.query(SymptomEntry).filter(SymptomEntry.user_id == uid).delete()
        s.query(HealthStatusLog).filter(HealthStatusLog.user_id == uid).delete()


def test_default_status_is_active_and_not_red():
    uid = _uid()
    _reset(uid)
    snap = sk.get_sickness_snapshot(uid)
    assert snap.status == HealthStatus.active
    assert snap.is_ill is False
    assert snap.illness_intensity == 0.0
    assert snap.needs_symptom_entry_today is False


def test_injured_stays_blue_with_note_but_no_prompt():
    uid = _uid()
    _reset(uid)
    sk.set_status(uid, HealthStatus.injured, note="tweaked hamstring")
    snap = sk.get_sickness_snapshot(uid)
    assert snap.status == HealthStatus.injured
    assert snap.status_note == "tweaked hamstring"
    # Injured = health not impacted: no red, no symptom prompt.
    assert snap.is_ill is False
    assert snap.illness_intensity == 0.0
    assert snap.needs_symptom_entry_today is False


def test_illness_turns_red_and_prompts_until_logged():
    uid = _uid()
    _reset(uid)
    sk.set_status(uid, HealthStatus.illness)
    snap = sk.get_sickness_snapshot(uid)
    assert snap.is_ill is True
    assert snap.illness_intensity > 0.0          # page goes red
    assert snap.needs_symptom_entry_today is True  # prompt due
    assert snap.days_ill == 1

    # Severity drives how red the page gets.
    sk.upsert_symptom_entry(
        uid, severity=SymptomSeverity.severe, symptoms=["fever", "cough"], note="rough"
    )
    snap = sk.get_sickness_snapshot(uid)
    assert snap.needs_symptom_entry_today is False
    assert snap.illness_intensity == 1.0         # severe -> full red
    assert snap.today_entry is not None
    assert snap.today_entry.symptom_labels == ["Fever", "Cough"]


def test_severity_modulates_intensity():
    uid = _uid()
    _reset(uid)
    sk.set_status(uid, HealthStatus.illness)
    sk.upsert_symptom_entry(uid, severity=SymptomSeverity.mild, symptoms=[])
    mild = sk.get_sickness_snapshot(uid).illness_intensity
    sk.upsert_symptom_entry(uid, severity=SymptomSeverity.moderate, symptoms=[])
    moderate = sk.get_sickness_snapshot(uid).illness_intensity
    assert 0.0 < mild < moderate <= 1.0


def test_symptom_log_joins_daily_vitals():
    uid = _uid()
    _reset(uid)
    day = date.today() - timedelta(days=1)
    with session_scope() as s:
        row = (
            s.query(HealthMetricDaily)
            .filter(HealthMetricDaily.user_id == uid, HealthMetricDaily.day == day)
            .one_or_none()
        )
        if row is None:
            row = HealthMetricDaily(user_id=uid, day=day)
            s.add(row)
        row.sleep_minutes = 372  # 6.2h
        row.resting_hr = 71
        row.hrv_ms = 38.0

    sk.set_status(uid, HealthStatus.illness, on=day)
    sk.upsert_symptom_entry(
        uid, severity=SymptomSeverity.moderate, symptoms=["fatigue"], day=day
    )
    log = sk.symptom_log(uid)
    entry = next(r for r in log if r.day == day)
    assert entry.sleep_hours == 6.2
    assert entry.resting_hr == 71
    assert entry.hrv_ms == 38.0


def test_recovery_clears_red():
    uid = _uid()
    _reset(uid)
    sk.set_status(uid, HealthStatus.illness)
    assert sk.get_sickness_snapshot(uid).illness_intensity > 0.0
    sk.set_status(uid, HealthStatus.active)
    snap = sk.get_sickness_snapshot(uid)
    assert snap.is_ill is False
    assert snap.illness_intensity == 0.0
