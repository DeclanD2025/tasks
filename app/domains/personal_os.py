"""Personal operating-system read models.

This module is the thin intelligence layer that turns ORION's local facts into
daily status, recovery, run planning, workout progression, finance oversight,
mindfulness, and data-coverage readouts. It is deterministic and transparent:
scores are estimates, factors are visible, and sparse data stays sparse.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from math import isnan
from statistics import mean

import pandas as pd
from sqlalchemy import delete, desc, func, select

from app import services
from app.db.database import session_scope
from app.db.models import (
    Account,
    ActivityMetricDaily,
    DataSource,
    ExerciseSet,
    HealthMetricDaily,
    MentalCheckIn,
    MindfulnessSession,
    Transaction,
    Workout,
    WorkoutSessionLog,
)
from app.domains.finance.finance_service import finance_intelligence_snapshot
from app.domains.fitness import route_service
from app.domains.health import derived
from app.domains.mental_health import prompts as mind_prompts


WORKOUT_CATEGORIES = (
    "push",
    "pull",
    "legs",
    "upper",
    "lower",
    "full body",
    "cardio",
    "custom",
)
MINDFULNESS_TYPES = (
    "breathwork",
    "meditation",
    "walk",
    "journaling",
    "body scan",
    "other",
)


@dataclass(frozen=True)
class ScoreFactor:
    label: str
    value: str
    impact: str
    contribution: float
    present: bool = True

    @property
    def delta(self) -> float:
        """Contribution expressed as a deviation from a neutral 50 baseline."""
        return self.contribution - 50.0


@dataclass(frozen=True)
class OperatingInsight:
    title: str
    explanation: str
    severity: str
    area: str
    action: str
    confidence: str


@dataclass(frozen=True)
class TodayMetric:
    label: str
    value: str
    trend: str
    interpretation: str
    quality: str
    series: list[float] = field(default_factory=list)
    is_partial_day: bool = False
    partial_note: str = ""


@dataclass(frozen=True)
class DailyPlanItem:
    area: str
    title: str
    detail: str
    priority: str = "normal"
    route_key: str = ""


@dataclass(frozen=True)
class RecoverySnapshot:
    score: float | None
    label: str
    estimated: bool
    factors: list[ScoreFactor]
    metrics: list[TodayMetric]
    changes: list[str]
    recommendation: str
    data_quality: str


@dataclass(frozen=True)
class FinanceOperatingSnapshot:
    monthly_income: float
    fixed_costs: float
    subscriptions: float
    debt_repayments: float
    savings: float
    discretionary_spend: float
    remaining_buffer: float
    weekly_spend: float
    weekly_pace_delta: float
    safe_to_spend: float
    upcoming_bills: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class RunSessionSuggestion:
    day_label: str
    session_type: str
    title: str
    detail: str
    distance_km: float
    intensity: str


@dataclass(frozen=True)
class RunPlanSnapshot:
    goal: str
    current_week: int
    weekly_target_km: float
    week_distance_km: float
    recent_frequency: int
    average_distance_km: float
    average_pace_label: str
    next_run: RunSessionSuggestion
    guardrail: str
    weekly_plan: list[RunSessionSuggestion]
    adherence_label: str


@dataclass(frozen=True)
class WorkoutSetReadout:
    exercise: str
    set_number: int
    reps: int | None
    weight_kg: float | None
    rpe: float | None
    volume: float


@dataclass(frozen=True)
class WorkoutLogReadout:
    id: int
    day: date
    title: str
    category: str
    completed: bool
    duration_minutes: int | None
    rpe: float | None
    notes: str
    sets: list[WorkoutSetReadout]

    @property
    def volume(self) -> float:
        return sum(row.volume for row in self.sets)

    @property
    def set_count(self) -> int:
        return len(self.sets)


@dataclass(frozen=True)
class WorkoutTrackerSnapshot:
    recent_sessions: list[WorkoutLogReadout]
    weekly_volume: float
    weekly_sessions: int
    personal_bests: list[str]
    exercise_history: list[str]
    progression_insight: str


@dataclass(frozen=True)
class MindSnapshot:
    today: dict | None
    mood_average: float | None
    stress_average: float | None
    trend_label: str
    protocol_title: str
    protocol_actions: list[str]
    mindfulness_week_minutes: int
    mindfulness_streak: int
    imported_mindful_week_minutes: int
    crisis_note: str | None
    checkin_streak: int = 0
    reflection_streak: int = 0
    evening_prompt: str = ""
    weekly_headline: str = ""
    weekly_subtitle: str = ""
    weekly_theme: str = ""
    idea_prompt: str = ""
    mood_calendar: list[dict] = field(default_factory=list)
    top_activities: list[tuple[str, int]] = field(default_factory=list)
    shine_tags: list[str] = field(default_factory=list)
    down_tags: list[str] = field(default_factory=list)
    recent_reflections: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class DataMetricInventory:
    metric: str
    count: int
    latest: date | None
    status: str
    use: str


@dataclass(frozen=True)
class DataInventorySnapshot:
    sources: list[str]
    last_import: datetime | None
    metrics: list[DataMetricInventory]
    imported_files: int
    workout_count: int
    parsing_notes: list[str]
    suggestions: list[str]


@dataclass(frozen=True)
class TodaySnapshot:
    status: str
    score: float | None
    score_label: str
    estimated: bool
    training_recommendation: str
    mental_nudge: str
    finance_nudge: str
    suggested_action: str
    metrics: list[TodayMetric]
    plan: list[DailyPlanItem]
    insights: list[OperatingInsight]
    freshness_label: str
    sleep_debt_label: str = ""
    checkin_streak: int = 0
    mind_phase_done: str = ""  # "", "morning", "evening" — furthest bookend done today


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if isnan(out) else out


def _values(frame: pd.DataFrame, column: str) -> list[float]:
    if frame.empty or column not in frame:
        return []
    return [_safe_float(v) for v in frame[column].dropna().tolist() if _safe_float(v) is not None]


def _latest(values: list[float]) -> float | None:
    return values[-1] if values else None


def _trend(values: list[float], *, lower_is_better: bool = False) -> tuple[str, str]:
    if len(values) < 4:
        return "flat", "baseline pending"
    latest = values[-1]
    baseline = mean(values[:-1][-7:]) if len(values) > 1 else latest
    delta = latest - baseline
    if abs(delta) < max(abs(baseline) * 0.04, 0.8):
        return "flat", "near baseline"
    up = delta > 0
    good = (not up) if lower_is_better else up
    direction = "up" if up else "down"
    return direction, "improving" if good else "watch"


def _duration_label(minutes: float | None) -> str:
    if minutes is None:
        return "-"
    total = max(0, int(round(minutes)))
    return f"{total // 60}h {total % 60:02d}"


def _extra_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
            .order_by(HealthMetricDaily.day)
        ).all()
    records = []
    for day, extra in rows:
        record = {"day": day}
        if isinstance(extra, dict):
            record.update(extra)
        records.append(record)
    return pd.DataFrame(records)


def _activity_extra_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(ActivityMetricDaily.day, ActivityMetricDaily.steps, ActivityMetricDaily.active_minutes, ActivityMetricDaily.extra)
            .where(ActivityMetricDaily.user_id == user_id)
            .where(ActivityMetricDaily.day >= since)
            .order_by(ActivityMetricDaily.day)
        ).all()
    records = []
    for day, steps, active_minutes, extra in rows:
        record = {"day": day, "steps": steps, "exercise_minutes": active_minutes}
        if isinstance(extra, dict):
            record.update(extra)
        records.append(record)
    return pd.DataFrame(records)


def get_recovery_snapshot(user_id: int) -> RecoverySnapshot:
    health = services.health_frame(user_id, days=35)
    activity = services.activity_frame(user_id, days=35)
    extra = _extra_frame(user_id, days=35)
    strain_days = derived.get_strain_days(user_id, days=35)
    sleep_debt = derived.get_sleep_debt(user_id)

    sleep = _values(health, "sleep_minutes")
    hrv = _values(health, "hrv_ms")
    rhr = _values(health, "resting_hr")
    # Prefer imported training load; fall back to TRIMP estimated from
    # workout heart rate so "recent strain" reflects reality, not a stub.
    load = _values(activity, "training_load") or [d.trimp for d in strain_days]
    mood = _values(extra, "mood")

    factors: list[ScoreFactor] = []
    scores: list[float] = []

    latest_sleep = _latest(sleep)
    if latest_sleep is not None:
        # Score against the calibrated personal need when it exists;
        # fall back to the generic 8h target only while calibrating.
        target = sleep_debt.need_minutes or 480.0
        score = clamp((latest_sleep / target) * 100.0)
        scores.append(score)
        impact = (
            f"need {_duration_label(sleep_debt.need_minutes)}"
            if sleep_debt.need_minutes is not None
            else "target 8h"
        )
        factors.append(ScoreFactor("Sleep", _duration_label(latest_sleep), impact, score))
    else:
        factors.append(ScoreFactor("Sleep", "missing", "needed for recovery", 0, False))

    latest_hrv = _latest(hrv)
    if latest_hrv is not None and len(hrv) >= 3:
        baseline = mean(hrv[-14:-1]) if len(hrv) >= 4 else mean(hrv)
        score = clamp(50.0 + ((latest_hrv - baseline) / max(baseline, 1.0)) * 120.0)
        scores.append(score)
        factors.append(ScoreFactor("HRV", f"{latest_hrv:.0f} ms", f"baseline {baseline:.0f}", score))
    elif latest_hrv is not None:
        factors.append(ScoreFactor("HRV", f"{latest_hrv:.0f} ms", "baseline pending", 50))
        scores.append(50)
    else:
        factors.append(ScoreFactor("HRV", "missing", "needed for readiness", 0, False))

    latest_rhr = _latest(rhr)
    if latest_rhr is not None and len(rhr) >= 3:
        baseline = mean(rhr[-14:-1]) if len(rhr) >= 4 else mean(rhr)
        score = clamp(70.0 - (latest_rhr - baseline) * 8.0)
        scores.append(score)
        factors.append(ScoreFactor("Resting HR", f"{latest_rhr:.0f} bpm", f"baseline {baseline:.0f}", score))
    elif latest_rhr is not None:
        scores.append(55)
        factors.append(ScoreFactor("Resting HR", f"{latest_rhr:.0f} bpm", "baseline pending", 55))
    else:
        factors.append(ScoreFactor("Resting HR", "missing", "needed for strain check", 0, False))

    recent_load = sum(load[-3:]) if load else 0.0
    if load and any(load):
        baseline = mean(load[-14:]) * 3 if len(load) >= 7 else max(recent_load, 1)
        strain_score = clamp(80.0 - max(0.0, recent_load - baseline) * 0.25)
        scores.append(strain_score)
        factors.append(
            ScoreFactor("Recent strain", f"{recent_load:.0f} TRIMP", "last 3 days", strain_score)
        )

    if not sleep_debt.calibrating and sleep_debt.debt_minutes is not None:
        debt_hours = sleep_debt.debt_minutes / 60.0
        debt_score = clamp(100.0 - debt_hours * 12.0)
        scores.append(debt_score)
        factors.append(
            ScoreFactor(
                "Sleep debt",
                sleep_debt.label,
                f"need {_duration_label(sleep_debt.need_minutes)}/night",
                debt_score,
            )
        )
    else:
        factors.append(
            ScoreFactor("Sleep debt", sleep_debt.label, "personal need calibrating", 0, False)
        )

    latest_mood = _latest(mood)
    if latest_mood is not None:
        mood_score = clamp((latest_mood + 1.0) * 50.0)
        scores.append(mood_score)
        factors.append(ScoreFactor("Mood", f"{latest_mood:+.2f}", "Apple Health State of Mind", mood_score))

    score = round(mean(scores), 0) if scores else None
    # Sort factors so the strongest drivers (by absolute delta) appear first.
    factors = sorted(factors, key=lambda f: abs(f.delta), reverse=True)
    estimated = len([f for f in factors if f.present]) < 4
    if score is None:
        label = "No recovery score"
        recommendation = "Import sleep, HRV and resting heart rate before trusting a readiness readout."
        data_quality = "missing"
    elif score >= 78:
        label = "Primed"
        recommendation = "Good day for controlled strength work or a quality run, assuming soreness agrees."
        data_quality = "estimated" if estimated else "solid"
    elif score >= 58:
        label = "Steady"
        recommendation = "Keep the plan, but avoid stacking intensity for the sake of it."
        data_quality = "estimated" if estimated else "solid"
    elif score >= 42:
        label = "Fragile"
        recommendation = "Recovery looks fragile. Keep intensity low and bias toward easy movement."
        data_quality = "estimated" if estimated else "solid"
    else:
        label = "Protect"
        recommendation = "Downshift today: mobility, walk, breathwork, or rest."
        data_quality = "estimated" if estimated else "solid"

    metrics = _health_metric_cards(user_id, health, activity, extra, strain_days, sleep_debt)
    changes = _what_changed(health, activity, extra)
    return RecoverySnapshot(score, label, estimated, factors, metrics, changes, recommendation, data_quality)


def _health_metric_cards(
    user_id: int,
    health: pd.DataFrame,
    activity: pd.DataFrame,
    extra: pd.DataFrame,
    strain_days: list[derived.StrainDay],
    sleep_debt: derived.SleepDebt,
) -> list[TodayMetric]:
    activity_extra = _activity_extra_frame(user_id, days=35)
    cards: list[TodayMetric] = []

    # Any metric whose latest point is today is flagged as partial, because
    # the day is not yet complete and comparing it to full-day averages is
    # misleading without intraday normalisation.
    today = date.today()
    latest_health_day = health["day"].max() if not health.empty and "day" in health else None
    latest_activity_day = activity["day"].max() if not activity.empty and "day" in activity else None
    latest_extra_day = extra["day"].max() if not extra.empty and "day" in extra else None

    def add(
        label: str,
        value: str,
        values: list[float],
        interpretation: str,
        quality: str,
        lower: bool = False,
        *,
        is_partial_day: bool = False,
        partial_note: str = "",
    ) -> None:
        trend, _trend_label = _trend(values, lower_is_better=lower)
        cards.append(
            TodayMetric(
                label,
                value,
                trend,
                interpretation,
                quality,
                values[-14:],
                is_partial_day=is_partial_day,
                partial_note=partial_note or ("incomplete day" if is_partial_day else ""),
            )
        )

    sleep = _values(health, "sleep_minutes")
    sleep_target = (
        f"your personal need is {_duration_label(sleep_debt.need_minutes)}"
        if sleep_debt.need_minutes is not None
        else "aim for 7.5-8 hours"
    )
    add("Sleep", _duration_label(_latest(sleep)), [v / 60 for v in sleep], sleep_target if sleep else "not imported yet", "real" if sleep else "missing")

    hrv = _values(health, "hrv_ms")
    add("HRV", f"{_latest(hrv):.0f} ms" if hrv else "-", hrv, "compared to your own baseline" if hrv else "not imported yet", "real" if hrv else "missing")

    rhr = _values(health, "resting_hr")
    add("Resting HR", f"{_latest(rhr):.0f} bpm" if rhr else "-", rhr, "lower than your baseline usually means better recovery" if rhr else "not imported yet", "real" if rhr else "missing", True)

    # Secondary signals: shown only after progressive disclosure.
    steps = _values(activity_extra, "steps") or _values(activity, "steps")
    steps_partial = latest_activity_day == today if latest_activity_day else False
    steps_interp = "movement so far today" if steps else "export steps from Health Auto Export"
    add(
        "Steps",
        f"{_latest(steps):,.0f}" if steps else "-",
        steps,
        f"{steps_interp}{' — the day is not over yet' if steps_partial else ''}",
        "real" if steps else "missing",
        is_partial_day=steps_partial,
        partial_note="today — still counting",
    )

    active_energy = _values(activity_extra, "active_energy_kcal") or _values(extra, "active_energy_kcal")
    energy_partial = latest_extra_day == today if latest_extra_day else False
    energy_interp = "energy burned so far today" if active_energy else "export active energy from Health Auto Export"
    add(
        "Active Energy",
        f"{_latest(active_energy):.0f} kcal" if active_energy else "-",
        active_energy,
        f"{energy_interp}{' — the day is not over yet' if energy_partial else ''}",
        "real" if active_energy else "missing",
        is_partial_day=energy_partial,
        partial_note="today — still counting",
    )

    load = _values(activity, "training_load")
    strain_series = [d.trimp for d in strain_days]
    if load:
        add("Workout Load", f"{_latest(load):.0f}", load, "imported training load", "estimated")
    elif any(strain_series):
        today_strain = strain_days[-1] if strain_days else None
        add(
            "Strain",
            f"{today_strain.trimp:.0f} · {today_strain.band}" if today_strain else "-",
            strain_series,
            "strain estimated from workout heart rate",
            "estimated",
        )
    else:
        add("Strain", "-", [], "needs workouts with heart rate", "missing")

    distance = _values(extra, "distance_km")
    distance_partial = latest_extra_day == today if latest_extra_day else False
    distance_interp = "walking and running distance so far today" if distance else "export distance from Health Auto Export"
    add(
        "Run/Walk Distance",
        f"{_latest(distance):.1f} km" if distance else "-",
        distance,
        f"{distance_interp}{' — the day is not over yet' if distance_partial else ''}",
        "real" if distance else "missing",
        is_partial_day=distance_partial,
        partial_note="today — still counting",
    )

    weight = _values(health, "weight_kg")
    add("Weight", f"{_latest(weight):.1f} kg" if weight else "-", weight, "latest body-mass reading" if weight else "optional export", "real" if weight else "missing")

    if sleep_debt.calibrating:
        add("Sleep Debt", "—", [], f"learning your baseline: {sleep_debt.nights_recorded} of {derived.CALIBRATION_NIGHTS} nights", "missing")
    else:
        trend_note = ""
        if sleep_debt.trend_minutes is not None and abs(sleep_debt.trend_minutes) >= 20:
            trend_note = ", growing" if sleep_debt.trend_minutes > 0 else ", repaying"
        add(
            "Sleep Debt",
            sleep_debt.label,
            [],
            f"net shortfall over the last 14 nights vs your personal need{trend_note}",
            "estimated",
        )

    mindful = _values(extra, "mindful_minutes")
    add("Mindfulness", f"{_latest(mindful):.0f} min" if mindful else "-", mindful, "mindful minutes imported from Apple Health" if mindful else "no imported sessions", "real" if mindful else "missing")

    mood = _values(extra, "mood")
    add("Mood", f"{_latest(mood):+.2f}" if mood else "-", mood, "State of Mind valence from Apple Health" if mood else "no State of Mind export", "real" if mood else "missing")

    respiratory = _values(extra, "respiratory_rate")
    add("Respiratory Rate", f"{_latest(respiratory):.1f}/min" if respiratory else "-", respiratory, "context for sleep and illness" if respiratory else "optional export", "real" if respiratory else "missing")

    return cards


def _what_changed(health: pd.DataFrame, activity: pd.DataFrame, extra: pd.DataFrame) -> list[str]:
    changes: list[str] = []
    checks = [
        ("sleep_minutes", health, "Sleep", False, "minutes"),
        ("hrv_ms", health, "HRV", False, "ms"),
        ("resting_hr", health, "Resting HR", True, "bpm"),
        ("training_load", activity, "Training load", True, ""),
        ("mood", extra, "Mood", False, ""),
    ]
    for column, frame, label, lower, unit in checks:
        values = _values(frame, column)
        if len(values) < 8:
            continue
        latest = values[-1]
        baseline = mean(values[-8:-1])
        delta = latest - baseline
        threshold = max(abs(baseline) * 0.08, 1.0)
        if abs(delta) < threshold:
            continue
        if lower:
            direction = "elevated" if delta > 0 else "lower"
        else:
            direction = "up" if delta > 0 else "down"
        suffix = f" {unit}" if unit else ""
        changes.append(f"{label} is {direction} vs 7-day baseline ({delta:+.1f}{suffix}).")
    return changes[:5] or ["No major drift detected in the available recent signals."]


def get_finance_operating_snapshot(user_id: int) -> FinanceOperatingSnapshot:
    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    fixed_categories = {
        "rent",
        "utilities",
        "bills",
        "subscription",
        "subscriptions",
        "insurance",
        "phone",
        "loan",
        "debt",
        "transport",
    }
    savings_categories = {"savings", "investment", "lisa", "isa"}

    with session_scope() as s:
        rows = s.execute(
            select(Transaction.booked_at, Transaction.amount_minor, Transaction.category, Transaction.description)
            .join(Account, Account.id == Transaction.account_id)
            .where(Account.user_id == user_id)
            .where(Transaction.booked_at >= month_start)
        ).all()

    income = 0.0
    fixed = 0.0
    savings = 0.0
    discretionary = 0.0
    week_spend = 0.0
    for booked_at, amount_minor, category, description in rows:
        amount = amount_minor / 100.0
        cat = str(category or "").lower()
        desc = str(description or "").lower()
        if amount > 0:
            income += amount
            continue
        spend = abs(amount)
        if booked_at >= week_start:
            week_spend += spend
        if any(token in cat or token in desc for token in savings_categories):
            savings += spend
        elif any(token in cat or token in desc for token in fixed_categories):
            fixed += spend
        else:
            discretionary += spend

    intel = finance_intelligence_snapshot(user_id)
    subscriptions = sum(line.monthly_estimate for line in intel.subscriptions)
    debt_repayments = sum(
        line.monthly_rate for line in intel.funding_flows if "debt" in line.destination.lower()
    )
    days_in_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - month_start
    elapsed_ratio = max(1, today.day) / max(1, days_in_month.days)
    monthly_spend_to_date = fixed + subscriptions + debt_repayments + savings + discretionary
    projected_spend = monthly_spend_to_date / elapsed_ratio
    remaining_buffer = income - monthly_spend_to_date
    safe_to_spend = max(0.0, remaining_buffer / max(1, days_in_month.days - today.day + 1))
    expected_week = projected_spend / 4.345 if projected_spend else 0.0
    weekly_pace_delta = week_spend - expected_week

    warnings: list[str] = []
    if income and projected_spend > income:
        warnings.append(f"Projected month is £{projected_spend - income:,.0f} over income.")
    if weekly_pace_delta > 25:
        warnings.append(f"Weekly spending is £{weekly_pace_delta:,.0f} ahead of pace.")
    if subscriptions > income * 0.12 and income:
        warnings.append("Subscriptions are taking a large share of income.")
    if not rows:
        warnings.append("No current-month transactions available; manual/imported data needed.")

    upcoming = []
    for line in intel.recurring:
        if line.next_due and line.next_due <= today + timedelta(days=14):
            upcoming.append(f"{line.merchant}: £{line.average:,.2f} around {line.next_due:%d %b}")

    return FinanceOperatingSnapshot(
        monthly_income=income,
        fixed_costs=fixed,
        subscriptions=subscriptions,
        debt_repayments=debt_repayments,
        savings=savings,
        discretionary_spend=discretionary,
        remaining_buffer=remaining_buffer,
        weekly_spend=week_spend,
        weekly_pace_delta=weekly_pace_delta,
        safe_to_spend=safe_to_spend,
        upcoming_bills=upcoming[:6],
        warnings=warnings[:5],
    )


def get_run_plan_snapshot(user_id: int, recovery: RecoverySnapshot | None = None) -> RunPlanSnapshot:
    workouts = [
        w for w in route_service.list_workouts(user_id, limit=120)
        if w.sport_type.lower() in {"run", "running"}
    ]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    recent = [w for w in workouts if w.started_at.date() >= today - timedelta(days=28)]
    week_runs = [w for w in workouts if w.started_at.date() >= week_start]
    distances = [float(w.distance_meters or 0) / 1000.0 for w in recent if w.distance_meters]
    week_distance = sum(float(w.distance_meters or 0) / 1000.0 for w in week_runs)
    avg_distance = mean(distances) if distances else 2.5
    freq = len(recent)
    paces = [
        route_service.calculate_pace(w.duration_seconds, w.distance_meters)
        for w in recent
        if w.duration_seconds and w.distance_meters
    ]
    paces = [p for p in paces if p is not None]
    avg_pace = mean(paces) if paces else None
    avg_pace_label = route_service.format_pace(avg_pace)

    score = recovery.score if recovery else None
    current_week = max(1, min(8, (today.toordinal() % 56) // 7 + 1))
    weekly_target = max(6.0, min(32.0, (sum(distances[-14:]) / 4.0 if distances else 6.0) * 1.10))
    if freq < 4:
        weekly_target = min(12.0, weekly_target)
    # Operator override from Settings; blank keeps the adaptive target above.
    from app.domains import settings_service

    override = settings_service.get_value(user_id, "run_weekly_target_km")
    if override:
        weekly_target = float(override)
    goal_setting = settings_service.get_value(user_id, "run_goal") or "5k base progression"
    if week_distance >= weekly_target * 0.85:
        next_type = "Recovery run"
        target = max(2.0, avg_distance * 0.65)
        detail = "Weekly target is nearly covered; keep this easy."
    elif score is not None and score < 52:
        next_type = "Easy run"
        target = max(2.0, avg_distance * 0.75)
        detail = "Recovery is not robust enough for intervals today."
    elif freq >= 6 and avg_distance >= 3.5:
        next_type = "Intervals"
        target = max(3.0, min(avg_distance * 0.9, 5.0))
        detail = "Warm up, then short controlled reps. Stop if HR feels sticky."
    elif freq >= 3:
        next_type = "Long run"
        target = min(max(avg_distance * 1.18, 4.0), avg_distance + 1.5)
        detail = "Small progression only; no heroic jump."
    else:
        next_type = "Walk-run"
        target = 2.5
        detail = "Return conservatively: alternate easy jog and walk blocks."

    next_run = RunSessionSuggestion(
        "Next",
        next_type,
        f"{next_type} - {target:.1f} km",
        detail,
        round(target, 1),
        "low" if next_type in {"Easy run", "Recovery run", "Walk-run"} else "moderate",
    )
    weekly_plan = _weekly_run_plan(next_run, weekly_target, score)
    adherence = "on track" if week_distance >= weekly_target * 0.65 else "behind plan" if week_distance else "not started"
    guardrail = "No jump above roughly 10-15% of recent weekly distance; recovery downgrades intensity."
    return RunPlanSnapshot(
        goal=goal_setting,
        current_week=current_week,
        weekly_target_km=round(weekly_target, 1),
        week_distance_km=round(week_distance, 1),
        recent_frequency=freq,
        average_distance_km=round(avg_distance, 1),
        average_pace_label=avg_pace_label,
        next_run=next_run,
        guardrail=guardrail,
        weekly_plan=weekly_plan,
        adherence_label=adherence,
    )


def _weekly_run_plan(next_run: RunSessionSuggestion, weekly_target: float, score: float | None) -> list[RunSessionSuggestion]:
    easy = max(2.0, min(weekly_target * 0.25, next_run.distance_km))
    quality_allowed = score is None or score >= 58
    quality_type = "Intervals" if quality_allowed else "Recovery run"
    quality_dist = max(2.5, weekly_target * 0.30)
    long_dist = max(3.0, weekly_target - easy - quality_dist)
    return [
        next_run,
        RunSessionSuggestion("Midweek", quality_type, f"{quality_type} - {quality_dist:.1f} km", "Quality only if legs and recovery agree.", round(quality_dist, 1), "moderate" if quality_allowed else "low"),
        RunSessionSuggestion("Weekend", "Long run", f"Long run - {long_dist:.1f} km", "Keep it conversational; this is the aerobic anchor.", round(long_dist, 1), "low"),
    ]


def parse_exercise_sets(text: str) -> list[dict]:
    """Parse quick workout lines into set dictionaries.

    Supported examples:
    - Bench press 3x5 60kg RPE 8
    - Squat 5 reps @ 80
    - Plank 3x45
    """
    rows: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        rpe = None
        rpe_match = re.search(r"\brpe\s*(\d+(?:\.\d+)?)", line, re.I)
        if rpe_match:
            rpe = float(rpe_match.group(1))
            line = line[: rpe_match.start()] + line[rpe_match.end() :]
        weight = None
        weight_match = re.search(r"(?:@|\b)(\d+(?:\.\d+)?)\s*(?:kg|kgs)?\b", line, re.I)
        if weight_match:
            weight = float(weight_match.group(1))
        scheme = re.search(r"(\d+)\s*x\s*(\d+)", line, re.I)
        if scheme:
            set_count = int(scheme.group(1))
            reps = int(scheme.group(2))
            name = line[: scheme.start()].strip(" -,:") or "Exercise"
        else:
            reps_match = re.search(r"(\d+)\s*(?:reps|rep)\b", line, re.I)
            set_count = 1
            reps = int(reps_match.group(1)) if reps_match else None
            stop = reps_match.start() if reps_match else (weight_match.start() if weight_match else len(line))
            name = line[:stop].strip(" -,:") or "Exercise"
        for idx in range(1, max(1, set_count) + 1):
            rows.append({
                "exercise_name": name[:120],
                "set_number": idx,
                "reps": reps,
                "weight_kg": weight,
                "rpe": rpe,
            })
    return rows


def log_workout_session(
    user_id: int,
    *,
    title: str,
    category: str,
    exercises_text: str,
    day: date | None = None,
    duration_minutes: int | None = None,
    rpe: float | None = None,
    completed: bool = True,
    notes: str = "",
    source_session_id: int | None = None,
) -> int:
    category = category.lower().strip()
    if category not in WORKOUT_CATEGORIES:
        category = "custom"
    parsed = parse_exercise_sets(exercises_text)
    with session_scope() as s:
        row = WorkoutSessionLog(
            user_id=user_id,
            day=day or date.today(),
            title=(title.strip() or "Workout")[:160],
            category=category,
            duration_minutes=duration_minutes,
            rpe=rpe,
            completed=completed,
            notes=notes.strip(),
            source_session_id=source_session_id,
        )
        s.add(row)
        s.flush()
        for item in parsed:
            s.add(ExerciseSet(session_id=row.id, **item))
        return row.id


def repeat_last_workout(user_id: int) -> int | None:
    last = get_workout_tracker_snapshot(user_id).recent_sessions[:1]
    if not last:
        return None
    source = last[0]
    lines = []
    groups: dict[str, list[WorkoutSetReadout]] = {}
    for row in source.sets:
        groups.setdefault(row.exercise, []).append(row)
    for name, sets in groups.items():
        reps = sets[0].reps or 0
        weight = sets[0].weight_kg
        line = f"{name} {len(sets)}x{reps}"
        if weight is not None:
            line += f" {weight:g}kg"
        lines.append(line)
    return log_workout_session(
        user_id,
        title=f"Repeat {source.title}",
        category=source.category,
        exercises_text="\n".join(lines),
        duration_minutes=source.duration_minutes,
        rpe=source.rpe,
        completed=False,
        notes="Repeated from previous session.",
        source_session_id=source.id,
    )


def mark_workout_complete(session_id: int, completed: bool = True) -> None:
    with session_scope() as s:
        row = s.get(WorkoutSessionLog, session_id)
        if row is not None:
            row.completed = completed
            row.updated_at = datetime.now()


def get_workout_tracker_snapshot(user_id: int, days: int = 30) -> WorkoutTrackerSnapshot:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        session_rows = s.scalars(
            select(WorkoutSessionLog)
            .where(WorkoutSessionLog.user_id == user_id)
            .order_by(desc(WorkoutSessionLog.day), desc(WorkoutSessionLog.id))
            .limit(24)
        ).all()
        ids = [row.id for row in session_rows]
        set_rows = s.scalars(
            select(ExerciseSet).where(ExerciseSet.session_id.in_(ids)).order_by(ExerciseSet.session_id, ExerciseSet.id)
        ).all() if ids else []
        week_rows = s.execute(
            select(WorkoutSessionLog.id)
            .where(WorkoutSessionLog.user_id == user_id)
            .where(WorkoutSessionLog.day >= since)
        ).all()

    sets_by_session: dict[int, list[WorkoutSetReadout]] = {}
    all_sets: list[WorkoutSetReadout] = []
    for row in set_rows:
        volume = float(row.reps or 0) * float(row.weight_kg or 0)
        readout = WorkoutSetReadout(row.exercise_name, row.set_number, row.reps, row.weight_kg, row.rpe, volume)
        sets_by_session.setdefault(row.session_id, []).append(readout)
        all_sets.append(readout)

    sessions = [
        WorkoutLogReadout(
            row.id,
            row.day,
            row.title,
            row.category,
            bool(row.completed),
            row.duration_minutes,
            row.rpe,
            row.notes,
            sets_by_session.get(row.id, []),
        )
        for row in session_rows
    ]
    weekly = [session for session in sessions if session.day >= since]
    weekly_volume = sum(session.volume for session in weekly)
    pbs = _personal_bests(all_sets)
    history = _exercise_history(sessions)
    progression = _progression_insight(sessions)
    return WorkoutTrackerSnapshot(sessions, weekly_volume, len(week_rows), pbs, history, progression)


def _personal_bests(sets: list[WorkoutSetReadout]) -> list[str]:
    best: dict[str, WorkoutSetReadout] = {}
    for row in sets:
        if row.weight_kg is None:
            continue
        cur = best.get(row.exercise)
        if cur is None or (row.weight_kg or 0) > (cur.weight_kg or 0):
            best[row.exercise] = row
    return [
        f"{name}: {row.weight_kg:g} kg x {row.reps or '-'}"
        for name, row in sorted(best.items(), key=lambda item: item[0].lower())[:8]
    ]


def _exercise_history(sessions: list[WorkoutLogReadout]) -> list[str]:
    seen: dict[str, tuple[date, float]] = {}
    for session in sessions:
        for row in session.sets:
            seen[row.exercise] = (session.day, seen.get(row.exercise, (session.day, 0))[1] + row.volume)
    return [
        f"{name}: last {day:%d %b}, volume {volume:.0f}"
        for name, (day, volume) in sorted(seen.items(), key=lambda item: item[1][0], reverse=True)[:8]
    ]


def _progression_insight(sessions: list[WorkoutLogReadout]) -> str:
    by_title: dict[str, list[WorkoutLogReadout]] = {}
    for session in sessions:
        by_title.setdefault(session.title.lower(), []).append(session)
    for title, rows in by_title.items():
        if len(rows) >= 2:
            latest, prev = rows[0], rows[1]
            if prev.volume > 0:
                pct = (latest.volume - prev.volume) / prev.volume * 100
                label = latest.title
                return f"{label} volume {pct:+.0f}% vs last matching session."
    if sessions:
        return "Log one more similar session to unlock progression deltas."
    return "No workout logs yet. Start with one compact session."


def upsert_mental_checkin(
    user_id: int,
    *,
    mood: int | None = None,
    anxiety: int | None = None,
    stress: int | None = None,
    energy: int | None = None,
    sleep_quality: int | None = None,
    triggers: str | None = None,
    protective_actions: str | None = None,
    note: str | None = None,
    intention: str | None = None,
    day_rating: int | None = None,
    evening_note: str | None = None,
    factors: list[str] | None = None,
    intention_done: bool | None = None,
    thought_record: dict | None = None,
    day: date | None = None,
) -> None:
    """Upsert today's check-in; None leaves an existing field untouched.

    One row carries both bookends, so the morning form and the evening form
    each update only their own fields without clobbering the other's.
    """
    target = day or date.today()

    def _scale(value: int) -> int:
        return max(1, min(10, int(value)))

    with session_scope() as s:
        row = s.scalars(
            select(MentalCheckIn).where(MentalCheckIn.user_id == user_id, MentalCheckIn.day == target)
        ).first()
        if row is None:
            row = MentalCheckIn(user_id=user_id, day=target)
            s.add(row)
        if mood is not None:
            row.mood = _scale(mood)
        if anxiety is not None:
            row.anxiety = _scale(anxiety)
        if stress is not None:
            row.stress = _scale(stress)
        if energy is not None:
            row.energy = _scale(energy)
        if sleep_quality is not None:
            row.sleep_quality = _scale(sleep_quality)
        if triggers is not None:
            row.triggers = triggers.strip()
        if protective_actions is not None:
            row.protective_actions = protective_actions.strip()
        if note is not None:
            row.note = note.strip()
        if intention is not None:
            row.intention = intention.strip()[:300]
        if day_rating is not None:
            row.day_rating = _scale(day_rating)
        if evening_note is not None:
            row.evening_note = evening_note.strip()
        extra = dict(row.extra or {})
        if factors is not None:
            extra["factors"] = [f.strip().lower() for f in factors if f.strip()][:12]
        if intention_done is not None:
            extra["intention_done"] = bool(intention_done)
        if thought_record is not None:
            cleaned = {
                key: str(thought_record.get(key, "")).strip()[:600]
                for key in ("situation", "thought", "balanced")
            }
            if any(cleaned.values()):
                extra["thought_record"] = cleaned
            else:
                extra.pop("thought_record", None)
        row.extra = extra


def log_mindfulness_session(
    user_id: int,
    *,
    duration_minutes: int,
    kind: str,
    note: str = "",
    day: date | None = None,
) -> int:
    kind = kind.lower().strip()
    if kind not in MINDFULNESS_TYPES:
        kind = "other"
    with session_scope() as s:
        row = MindfulnessSession(
            user_id=user_id,
            day=day or date.today(),
            duration_minutes=max(1, int(duration_minutes)),
            kind=kind,
            note=note.strip(),
        )
        s.add(row)
        s.flush()
        return row.id


_FACTOR_LABELS = {
    "sleep": "Sleep",
    "training": "Training",
    "work": "Work",
    "people": "People",
    "money": "Money",
    "health": "Health",
    "food": "Food",
    "weather": "Weather",
}


def _factor_label(value: str) -> str:
    key = str(value or "").strip().lower()
    return _FACTOR_LABELS.get(key, key.replace("_", " ").title())


def _mood_tone(value: int | None) -> str:
    if value is None:
        return "empty"
    if value <= 3:
        return "low"
    if value >= 7:
        return "high"
    return "mid"


def _mind_weekly_headline(mood_avg: float | None, trend: str) -> tuple[str, str]:
    if mood_avg is None:
        return "mind unmeasured.", "Run one honest check-in."
    word = "good" if mood_avg >= 7 else "low" if mood_avg <= 3.5 else "okay"
    movement = "rising" if trend == "improving" else "dipping" if trend == "dipping" else "steady"
    return f"{word} mood.", f"{mood_avg:.1f} average mood this week · {movement}"


def _mind_idea_prompt(today_row: MentalCheckIn | None, trend: str) -> str:
    if today_row and today_row.energy <= 3:
        return "What is the smallest useful step you can take before noon?"
    if today_row and today_row.anxiety >= 7:
        return "What can you remove, decide, or write down to reduce background load?"
    if trend == "dipping":
        return "What has been quietly draining you, and what boundary would make tomorrow lighter?"
    if today_row and today_row.mood >= 7:
        return "What helped today work, and how do you make it repeatable?"
    return "What are some small, manageable steps that would improve mood and energy this week?"


def _mind_calendar(rows: list[MentalCheckIn]) -> list[dict]:
    by_day = {row.day: row for row in rows}
    start = date.today() - timedelta(days=6)
    out: list[dict] = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        row = by_day.get(day)
        out.append({
            "day": day.strftime("%a")[:1],
            "date": day.isoformat(),
            "mood": row.mood if row else None,
            "tone": _mood_tone(row.mood if row else None),
            "done": bool(row),
        })
    return out


def _mind_factor_readouts(rows: list[MentalCheckIn]) -> tuple[list[tuple[str, int]], list[str], list[str]]:
    week_rows = [row for row in rows if row.day >= date.today() - timedelta(days=6)]
    all_counts: Counter[str] = Counter()
    shine: Counter[str] = Counter()
    down: Counter[str] = Counter()
    for row in week_rows:
        factors = [
            _factor_label(f)
            for f in ((row.extra or {}).get("factors") or [])
            if str(f).strip()
        ]
        all_counts.update(factors)
        if row.mood >= 7 or row.energy >= 7:
            shine.update(factors)
        if row.mood <= 4 or row.stress >= 6 or row.anxiety >= 6:
            down.update(factors)
    return (
        [(label, count) for label, count in all_counts.most_common(3)],
        [label for label, _ in shine.most_common(4)],
        [label for label, _ in down.most_common(4)],
    )


def _recent_mind_reflections(rows: list[MentalCheckIn]) -> list[dict]:
    out: list[dict] = []
    for row in reversed(rows[-10:]):
        if not ((row.evening_note or "").strip() or (row.intention or "").strip()):
            continue
        out.append({
            "day": row.day.strftime("%d %b"),
            "title": "evening" if (row.evening_note or "").strip() else "morning",
            "mood": row.mood,
            "body": (row.evening_note or row.intention or "").strip()[:220],
        })
        if len(out) >= 4:
            break
    return out


def get_mind_snapshot(user_id: int) -> MindSnapshot:
    since = date.today() - timedelta(days=30)
    week_start = date.today() - timedelta(days=6)
    with session_scope() as s:
        rows = s.scalars(
            select(MentalCheckIn)
            .where(MentalCheckIn.user_id == user_id)
            .where(MentalCheckIn.day >= since)
            .order_by(MentalCheckIn.day)
        ).all()
        sessions = s.scalars(
            select(MindfulnessSession)
            .where(MindfulnessSession.user_id == user_id)
            .where(MindfulnessSession.day >= since)
            .order_by(MindfulnessSession.day)
        ).all()

    today_row = next((row for row in rows if row.day == date.today()), None)
    mood_values = [row.mood for row in rows]
    stress_values = [row.stress for row in rows]
    mood_avg = mean(mood_values[-7:]) if mood_values else None
    stress_avg = mean(stress_values[-7:]) if stress_values else None
    trend = "no check-ins yet"
    if len(mood_values) >= 8:
        delta = mean(mood_values[-3:]) - mean(mood_values[-10:-3])
        trend = "improving" if delta > 0.5 else "dipping" if delta < -0.5 else "steady"

    if today_row and today_row.mood <= 2:
        protocol = "Low mood protocol"
        actions = ["Make the next action very small.", "Walk outside for 5 minutes.", "Message someone safe.", "Lower training intensity today."]
    elif today_row and today_row.anxiety >= 8:
        protocol = "High anxiety protocol"
        actions = ["Physiological sigh for 3 cycles.", "Name the next 10-minute action.", "Reduce checking and reassurance loops.", "Keep caffeine and intensity modest."]
    elif today_row and today_row.stress >= 8:
        protocol = "Overwhelm protocol"
        actions = ["Clear one small task.", "Write the top three open loops.", "Move or defer one nonessential demand.", "Add an early-night prompt."]
    else:
        protocol = "Good day maintenance"
        actions = ["3-minute minimum viable session.", "Keep training aligned with recovery.", "Do one protective action before evening.", "Journal for 3 minutes if mood shifts."]

    local_week = sum(s.duration_minutes for s in sessions if s.day >= week_start)
    imported_week = int(sum(_values(_extra_frame(user_id, days=7), "mindful_minutes")))
    streak = _mindfulness_streak(sessions)
    crisis = None
    if today_row and (today_row.mood <= 1 or today_row.stress >= 10):
        crisis = "If you feel at risk of harming yourself or someone else, call 999 now. For urgent UK mental health support, contact Samaritans on 116 123."

    today_payload = None
    if today_row:
        row_extra = today_row.extra or {}
        today_payload = {
            "mood": today_row.mood,
            "anxiety": today_row.anxiety,
            "stress": today_row.stress,
            "energy": today_row.energy,
            "sleep_quality": today_row.sleep_quality,
            "triggers": today_row.triggers,
            "protective_actions": today_row.protective_actions,
            "note": today_row.note,
            "intention": today_row.intention,
            "day_rating": today_row.day_rating,
            "evening_note": today_row.evening_note,
            "factors": row_extra.get("factors", []),
            "intention_done": row_extra.get("intention_done"),
            "thought_record": row_extra.get("thought_record"),
        }
    checkin_streak = _streak_from_days({row.day for row in rows})
    reflection_streak = _streak_from_days(
        {row.day for row in rows if (row.evening_note or "").strip() or (row.note or "").strip()}
    )
    prompt = mind_prompts.evening_prompt(
        date.today(),
        mood=today_row.mood if today_row else None,
        stress=today_row.stress if today_row else None,
    )
    weekly_headline, weekly_subtitle = _mind_weekly_headline(mood_avg, trend)
    top_activities, shine_tags, down_tags = _mind_factor_readouts(rows)
    return MindSnapshot(
        today_payload,
        mood_avg,
        stress_avg,
        trend,
        protocol,
        actions,
        local_week,
        streak,
        imported_week,
        crisis,
        checkin_streak=checkin_streak,
        reflection_streak=reflection_streak,
        evening_prompt=prompt,
        weekly_headline=weekly_headline,
        weekly_subtitle=weekly_subtitle,
        weekly_theme="on the domino effect.",
        idea_prompt=_mind_idea_prompt(today_row, trend),
        mood_calendar=_mind_calendar(rows),
        top_activities=top_activities,
        shine_tags=shine_tags,
        down_tags=down_tags,
        recent_reflections=_recent_mind_reflections(rows),
    )


def _streak_from_days(days: set[date]) -> int:
    """Consecutive-day streak ending today or yesterday (today still open)."""
    cursor = date.today()
    if cursor not in days:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _mindfulness_streak(sessions: list[MindfulnessSession]) -> int:
    days = {row.day for row in sessions if row.duration_minutes > 0}
    streak = 0
    cursor = date.today()
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_today_snapshot(user_id: int) -> TodaySnapshot:
    recovery = get_recovery_snapshot(user_id)
    finance = get_finance_operating_snapshot(user_id)
    run_plan = get_run_plan_snapshot(user_id, recovery)
    mind = get_mind_snapshot(user_id)
    workout = get_workout_tracker_snapshot(user_id)

    score = recovery.score
    if score is None:
        status = "Awaiting data"
        score_label = "No readiness score"
    elif score >= 78:
        status = "Primed"
        score_label = f"{score:.0f}/100"
    elif score >= 58:
        status = "Steady"
        score_label = f"{score:.0f}/100"
    elif score >= 42:
        status = "Fragile"
        score_label = f"{score:.0f}/100"
    else:
        status = "Protect"
        score_label = f"{score:.0f}/100"

    training = _training_recommendation(recovery, run_plan, workout)
    mental = _mental_nudge(mind)
    finance_nudge = _finance_nudge(finance)
    suggested = _suggested_action(recovery, finance, mind, run_plan)
    insights = build_operating_insights(user_id, recovery=recovery, finance=finance, mind=mind, run_plan=run_plan, workout=workout)
    plan = _daily_plan(recovery, finance, mind, run_plan, workout)
    freshness = _freshness_label(user_id)
    sleep_debt = derived.get_sleep_debt(user_id)
    phase_done = ""
    if mind.today is not None:
        phase_done = "evening" if (mind.today.get("evening_note") or "").strip() else "morning"
    return TodaySnapshot(
        status=status,
        score=score,
        score_label=score_label,
        estimated=recovery.estimated,
        training_recommendation=training,
        mental_nudge=mental,
        finance_nudge=finance_nudge,
        suggested_action=suggested,
        metrics=recovery.metrics[:12],
        plan=plan,
        insights=insights,
        freshness_label=freshness,
        sleep_debt_label=sleep_debt.label,
        checkin_streak=mind.checkin_streak,
        mind_phase_done=phase_done,
    )


def _training_recommendation(recovery: RecoverySnapshot, run_plan: RunPlanSnapshot, workout: WorkoutTrackerSnapshot) -> str:
    if recovery.score is not None and recovery.score < 50:
        return "Recovery looks fragile. Keep intensity low."
    if run_plan.week_distance_km < run_plan.weekly_target_km * 0.5:
        return f"Good day for {run_plan.next_run.title.lower()}."
    if workout.weekly_sessions == 0:
        return "Strength work is under-logged this week. Start controlled."
    return recovery.recommendation


def _mental_nudge(mind: MindSnapshot) -> str:
    if mind.today is None:
        return "Add a short check-in before bed."
    if mind.trend_label == "dipping":
        return "Mood trend is dipping. Use the low-friction protocol."
    if mind.today["anxiety"] >= 8:
        return "Anxiety is high. Downshift before hard decisions."
    return "Mental state logged. Keep the maintenance action small."


def _finance_nudge(finance: FinanceOperatingSnapshot) -> str:
    if finance.weekly_pace_delta > 25:
        return "Spending is tracking high this week. Tighten discretionary spend."
    if finance.remaining_buffer < 0:
        return "Monthly buffer is negative on current entries."
    if finance.safe_to_spend > 0:
        return f"Safe-to-spend estimate: £{finance.safe_to_spend:,.0f}/day."
    return "Finance data is sparse; import or add transactions."


def _suggested_action(recovery: RecoverySnapshot, finance: FinanceOperatingSnapshot, mind: MindSnapshot, run_plan: RunPlanSnapshot) -> str:
    if recovery.score is not None and recovery.score < 45:
        return "Replace intensity with recovery work today."
    if mind.today is None:
        return "Complete a 60-second mind check-in."
    if finance.weekly_pace_delta > 25:
        return "Review discretionary transactions before spending again."
    return f"Execute the next run plan: {run_plan.next_run.title}."


def _daily_plan(
    recovery: RecoverySnapshot,
    finance: FinanceOperatingSnapshot,
    mind: MindSnapshot,
    run_plan: RunPlanSnapshot,
    workout: WorkoutTrackerSnapshot,
) -> list[DailyPlanItem]:
    intensity = "low" if recovery.score is not None and recovery.score < 55 else "normal"
    return [
        DailyPlanItem("Training", "Strength", "Controlled full-body or repeat last workout." if workout.recent_sessions else "Start a simple push/pull/legs log.", intensity, "fitness"),
        DailyPlanItem("Running", run_plan.next_run.session_type, run_plan.next_run.detail, intensity, "run_plan"),
        DailyPlanItem("Mindfulness", "Minimum viable session", "3 minutes beats a perfect plan skipped.", "normal", "mental_health"),
        DailyPlanItem("Finance", "Spending pace", _finance_nudge(finance), "high" if finance.weekly_pace_delta > 25 else "normal", "finance"),
        DailyPlanItem("Recovery", recovery.label, recovery.recommendation, "high" if recovery.score is not None and recovery.score < 50 else "normal", "health"),
    ]


def build_operating_insights(
    user_id: int,
    *,
    recovery: RecoverySnapshot | None = None,
    finance: FinanceOperatingSnapshot | None = None,
    mind: MindSnapshot | None = None,
    run_plan: RunPlanSnapshot | None = None,
    workout: WorkoutTrackerSnapshot | None = None,
) -> list[OperatingInsight]:
    recovery = recovery or get_recovery_snapshot(user_id)
    finance = finance or get_finance_operating_snapshot(user_id)
    mind = mind or get_mind_snapshot(user_id)
    run_plan = run_plan or get_run_plan_snapshot(user_id, recovery)
    workout = workout or get_workout_tracker_snapshot(user_id)

    insights: list[OperatingInsight] = []
    for change in recovery.changes[:3]:
        # The direction words carry good/bad: "up"/"lower" are favourable moves,
        # "down"/"elevated" are adverse. Title, severity and action must match —
        # a positive change should never read as "Recovery drift · keep intensity low".
        adverse = " down " in change or "elevated" in change
        favourable = " up " in change or "lower" in change
        if adverse:
            title, severity = "Recovery drift", "warning"
            action = recovery.recommendation
        elif favourable:
            title, severity = "Recovery improving", "info"
            action = "A favourable shift — hold the habits that produced it."
        else:
            title, severity = "Recovery signal", "info"
            action = recovery.recommendation
        insights.append(OperatingInsight(title, change, severity, "Recovery", action, recovery.data_quality))
    if run_plan.week_distance_km > run_plan.weekly_target_km * 1.15:
        insights.append(OperatingInsight("Running volume jump", "This week's running distance is above the guardrail.", "warning", "Run Plan", "Make the next run easy or skip intensity.", "medium"))
    elif run_plan.week_distance_km < run_plan.weekly_target_km * 0.35:
        insights.append(OperatingInsight("Running adherence lag", "Weekly run volume is behind the current base plan.", "info", "Run Plan", run_plan.next_run.title, "medium"))
    if finance.weekly_pace_delta > 25:
        insights.append(OperatingInsight("Spending pace ahead", f"This week is £{finance.weekly_pace_delta:,.0f} ahead of expected pace.", "warning", "Money", "Pause discretionary spend and inspect recent transactions.", "medium"))
    if mind.trend_label == "dipping":
        insights.append(OperatingInsight("Mood trend dipping", "Recent check-ins are lower than the earlier baseline.", "warning", "Mind", "Use the low mood protocol and lower training pressure.", "medium"))
    if workout.weekly_sessions >= 3:
        insights.append(OperatingInsight("Training frequency high", f"{workout.weekly_sessions} logged sessions in the last 30 days.", "info", "Training", "Watch recovery before adding more intensity.", "medium"))
    sleep_debt = derived.get_sleep_debt(user_id)
    if sleep_debt.debt_minutes is not None and sleep_debt.debt_minutes >= 120:
        growing = sleep_debt.trend_minutes is not None and sleep_debt.trend_minutes > 20
        insights.append(
            OperatingInsight(
                "Sleep debt building" if growing else "Sleep debt open",
                f"{sleep_debt.label} short vs your personal need of "
                f"{_duration_label(sleep_debt.need_minutes)} over the last 14 nights.",
                "warning" if growing or sleep_debt.debt_minutes >= 240 else "info",
                "Recovery",
                "Bring bedtime forward; repay in 30-60 minute increments, not one long lie-in.",
                "medium",
            )
        )
    return insights[:8]


def _freshness_label(user_id: int) -> str:
    with session_scope() as s:
        latest = s.scalars(
            select(DataSource.last_synced_at)
            .where(DataSource.user_id == user_id)
            .where(DataSource.last_synced_at.is_not(None))
            .order_by(desc(DataSource.last_synced_at))
            .limit(1)
        ).first()
    if latest is None:
        return "No live source sync recorded"
    age = datetime.now() - latest.replace(tzinfo=None)
    if age.days == 0:
        return "Data refreshed today"
    return f"Last source refresh {age.days}d ago"


def get_data_inventory(user_id: int) -> DataInventorySnapshot:
    with session_scope() as s:
        sources = s.scalars(
            select(DataSource).where(DataSource.user_id == user_id).order_by(DataSource.domain, DataSource.name)
        ).all()
        health_rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.sleep_minutes, HealthMetricDaily.hrv_ms, HealthMetricDaily.resting_hr, HealthMetricDaily.weight_kg, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .order_by(HealthMetricDaily.day)
        ).all()
        activity_rows = s.execute(
            select(ActivityMetricDaily.day, ActivityMetricDaily.steps, ActivityMetricDaily.active_minutes, ActivityMetricDaily.training_load, ActivityMetricDaily.extra)
            .where(ActivityMetricDaily.user_id == user_id)
            .order_by(ActivityMetricDaily.day)
        ).all()
        workout_count = s.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user_id)) or 0

    source_lines = [
        f"{src.name}: {src.status.value if hasattr(src.status, 'value') else src.status}"
        + (f", synced {src.last_synced_at:%d %b %Y %H:%M}" if src.last_synced_at else ", never synced")
        for src in sources
    ]
    latest_import = max((src.last_synced_at for src in sources if src.last_synced_at), default=None)
    metrics: list[DataMetricInventory] = []

    def add_metric(metric: str, values: list[tuple[date, object]], use: str) -> None:
        present = [(day, value) for day, value in values if value is not None]
        metrics.append(
            DataMetricInventory(
                metric,
                len(present),
                present[-1][0] if present else None,
                "available" if present else "missing",
                use,
            )
        )

    add_metric("sleep_minutes", [(row[0], row[1]) for row in health_rows], "recovery score, Today metrics")
    add_metric("hrv_ms", [(row[0], row[2]) for row in health_rows], "readiness and recovery")
    add_metric("resting_hr", [(row[0], row[3]) for row in health_rows], "recovery watch")
    add_metric("weight_kg", [(row[0], row[4]) for row in health_rows], "body-state trend")
    for key, use in [
        ("mood", "mind trend"),
        ("mindful_minutes", "mindfulness consistency"),
        ("distance_km", "run plan and daily movement"),
        ("vo2max", "running/fitness context"),
        ("active_energy_kcal", "activity strain"),
        ("respiratory_rate", "sleep/illness context"),
    ]:
        add_metric(key, [(row[0], (row[5] or {}).get(key) if isinstance(row[5], dict) else None) for row in health_rows], use)
    add_metric("steps", [(row[0], row[1]) for row in activity_rows], "daily movement")
    add_metric("exercise_minutes", [(row[0], row[2]) for row in activity_rows], "activity minutes")
    add_metric("training_load", [(row[0], row[3]) for row in activity_rows], "strain proxy")

    imported_files = 0
    notes: list[str] = []
    try:
        from app.ingestion import get_connector
        from app.integrations.health_auto_export.parser import recent_export_files

        hae = get_connector("health_auto_export")
        folder = hae.folder()
        if folder:
            files = recent_export_files(folder, max_files=500)
            imported_files = len(files)
            notes.append(f"Health Auto Export folder: {folder}")
        else:
            notes.append("Health Auto Export folder is not configured.")
    except Exception as exc:
        notes.append(f"Inventory probe skipped: {exc}")

    suggestions = []
    missing = {m.metric for m in metrics if m.status == "missing"}
    if "steps" in missing:
        suggestions.append("Add Steps to Health Auto Export for daily movement cards.")
    if "active_energy_kcal" in missing:
        suggestions.append("Export Active Energy for better strain estimates.")
    if "mindful_minutes" in missing:
        suggestions.append("Export Mindfulness minutes or log local sessions.")
    if "respiratory_rate" in missing:
        suggestions.append("Respiratory Rate can improve sleep and illness context.")
    if workout_count == 0:
        suggestions.append("Export workouts from HAE to unlock route and run analysis.")

    return DataInventorySnapshot(source_lines, latest_import, metrics, imported_files, int(workout_count), notes, suggestions[:6])


def clear_today_mindfulness(user_id: int) -> None:
    """Test/helper hook: remove local mindfulness logs for today."""
    with session_scope() as s:
        s.execute(
            delete(MindfulnessSession).where(
                MindfulnessSession.user_id == user_id,
                MindfulnessSession.day == date.today(),
            )
        )
