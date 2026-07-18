"""Rule-based / statistical insight engine.

Each rule is a small pure function: given a user's recent data, it returns zero
or more `InsightDraft`s. The engine runs all rules and persists the results to
the `insights` table. Adding a new insight = adding a function to `RULES`.

NO LLM is involved. Phrasing is templated; numbers are computed with pandas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import Domain, Insight, InsightSeverity, Workout
from app.domains import settings_service
from app.services import (
    activity_frame,
    health_frame,
    mood_frame,
    monthly_spending,
    practice_frame,
    project_momentum,
)

log = get_logger(__name__)


@dataclass
class InsightDraft:
    domain: Domain
    severity: InsightSeverity
    title: str
    body: str
    rule_key: str
    metric_value: float | None = None


def _pct_change(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return (current - baseline) / baseline * 100.0


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def rule_spending_vs_last_month(user_id: int) -> list[InsightDraft]:
    df = monthly_spending(user_id)
    if len(df) < 2:
        return []
    current, prev = df["spend"].iloc[-1], df["spend"].iloc[-2]
    pct = _pct_change(current, prev)
    if abs(pct) < 5:
        return []
    direction = "higher" if pct > 0 else "lower"
    severity = InsightSeverity.warning if pct > 15 else InsightSeverity.info
    return [
        InsightDraft(
            Domain.finance,
            severity if pct > 0 else InsightSeverity.positive,
            f"Spending is {abs(pct):.0f}% {direction} than last month.",
            f"This month: £{current:,.0f} vs last month £{prev:,.0f}.",
            "spending_vs_last_month",
            round(pct, 1),
        )
    ]


def rule_sleep_week_over_week(user_id: int) -> list[InsightDraft]:
    df = health_frame(user_id).dropna(subset=["sleep_minutes"])
    if len(df) < 14:
        return []
    recent = df["sleep_minutes"].tail(7).mean()
    prior = df["sleep_minutes"].iloc[-14:-7].mean()
    diff = recent - prior  # minutes
    if abs(diff) < 15:
        return []
    if diff < 0:
        return [
            InsightDraft(
                Domain.health,
                InsightSeverity.warning,
                f"Average sleep is down {abs(diff):.0f} minutes this week.",
                f"7-day average {recent/60:.1f}h vs prior week {prior/60:.1f}h.",
                "sleep_week_over_week",
                round(diff, 1),
            )
        ]
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.positive,
            f"Average sleep is up {diff:.0f} minutes this week.",
            f"7-day average {recent/60:.1f}h vs prior week {prior/60:.1f}h.",
            "sleep_week_over_week",
            round(diff, 1),
        )
    ]


def rule_deep_work_week_over_week(user_id: int) -> list[InsightDraft]:
    df = activity_frame(user_id).dropna(subset=["deep_work_minutes"])
    if len(df) < 14:
        return []
    recent = df["deep_work_minutes"].tail(7).sum()
    prior = df["deep_work_minutes"].iloc[-14:-7].sum()
    pct = _pct_change(recent, prior)
    if abs(pct) < 8:
        return []
    if pct > 0:
        return [
            InsightDraft(
                Domain.productivity,
                InsightSeverity.positive,
                "Deep work increased compared to last week.",
                f"{recent/60:.1f}h this week vs {prior/60:.1f}h last week (+{pct:.0f}%).",
                "deep_work_week_over_week",
                round(pct, 1),
            )
        ]
    return [
        InsightDraft(
            Domain.productivity,
            InsightSeverity.warning,
            "Deep work is below last week.",
            f"{recent/60:.1f}h this week vs {prior/60:.1f}h last week ({pct:.0f}%).",
            "deep_work_week_over_week",
            round(pct, 1),
        )
    ]


def rule_training_consistency(user_id: int) -> list[InsightDraft]:
    df = activity_frame(user_id).dropna(subset=["training_load"])
    if len(df) < 14:
        return []
    recent_cv = df["training_load"].tail(7).std() / (df["training_load"].tail(7).mean() or 1)
    prior_cv = (
        df["training_load"].iloc[-14:-7].std()
        / (df["training_load"].iloc[-14:-7].mean() or 1)
    )
    if np.isnan(recent_cv) or np.isnan(prior_cv):
        return []
    if recent_cv < prior_cv - 0.05:
        return [
            InsightDraft(
                Domain.health,
                InsightSeverity.positive,
                "Training consistency improved.",
                "Day-to-day training load varied less than last week.",
                "training_consistency",
                round(float(recent_cv), 3),
            )
        ]
    return []


def rule_resting_hr_elevated(user_id: int) -> list[InsightDraft]:
    df = health_frame(user_id).dropna(subset=["resting_hr"])
    if len(df) < 8:
        return []
    latest = float(df["resting_hr"].iloc[-1])
    baseline = float(df["resting_hr"].iloc[-8:-1].mean())
    delta = latest - baseline
    if delta < 4:
        return []
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.warning,
            "Resting heart rate is elevated against baseline.",
            f"Latest {latest:.0f} bpm vs 7-day baseline {baseline:.0f} bpm.",
            "resting_hr_elevated",
            round(delta, 1),
        )
    ]


def rule_running_volume_spike(user_id: int) -> list[InsightDraft]:
    today = date.today()
    since = today - timedelta(days=14)
    with session_scope() as s:
        rows = s.execute(
            select(Workout.started_at, Workout.distance_meters)
            .where(Workout.user_id == user_id)
            .where(Workout.sport_type.in_(["run", "running"]))
            .where(Workout.started_at >= since)
        ).all()
    recent = 0.0
    prior = 0.0
    for started_at, meters in rows:
        km = float(meters or 0.0) / 1000.0
        if started_at.date() >= today - timedelta(days=7):
            recent += km
        else:
            prior += km
    if prior <= 0 or recent <= prior * 1.35:
        return []
    pct = _pct_change(recent, prior)
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.warning,
            "Running volume is up sharply this week.",
            f"{recent:.1f} km in the last 7 days vs {prior:.1f} km the prior week.",
            "running_volume_spike",
            round(pct, 1),
        )
    ]


def rule_mindfulness_consistency(user_id: int) -> list[InsightDraft]:
    df = practice_frame(user_id).dropna(subset=["mindful_minutes"])
    if len(df) < 10:
        return []
    recent_days = int((df["mindful_minutes"].tail(7) > 0).sum())
    prior_days = int((df["mindful_minutes"].iloc[-14:-7] > 0).sum())
    if recent_days <= prior_days:
        return []
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.positive,
            "Mindfulness consistency is improving.",
            f"{recent_days} practice days in the last week vs {prior_days} the prior week.",
            "mindfulness_consistency",
            float(recent_days),
        )
    ]


def rule_mood_lower_on_short_sleep(user_id: int) -> list[InsightDraft]:
    sleep = health_frame(user_id).dropna(subset=["sleep_minutes"])
    mood = mood_frame(user_id).dropna(subset=["mood"])
    if sleep.empty or mood.empty:
        return []
    merged = pd.merge(sleep[["day", "sleep_minutes"]], mood, on="day", how="inner")
    if len(merged) < 8:
        return []
    short = merged[merged["sleep_minutes"] < 420]["mood"]
    normal = merged[merged["sleep_minutes"] >= 420]["mood"]
    if len(short) < 3 or len(normal) < 3:
        return []
    gap = float(normal.mean() - short.mean())
    if gap < 0.25:
        return []
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.info,
            "Mood check-ins are lower on short-sleep days.",
            f"Average mood gap is {gap:.2f} valence points when sleep is under 7h.",
            "mood_short_sleep",
            round(gap, 2),
        )
    ]


def rule_project_output_vs_average(user_id: int) -> list[InsightDraft]:
    df = project_momentum(user_id).dropna(subset=["momentum"])
    if df.empty:
        return []
    df["day"] = pd.to_datetime(df["day"])
    daily = df.groupby("day")["momentum"].mean().sort_index()
    if len(daily) < 8:
        return []
    recent = daily.tail(3).mean()
    baseline = daily.mean()
    pct = _pct_change(recent, baseline)
    if pct < -8:
        return [
            InsightDraft(
                Domain.projects,
                InsightSeverity.warning,
                "Project output is below recent average.",
                f"Recent momentum {recent:.0f} vs average {baseline:.0f} ({pct:.0f}%).",
                "project_output_vs_average",
                round(pct, 1),
            )
        ]
    return []


def rule_blood_pressure_elevation(user_id: int) -> list[InsightDraft]:
    """Flag sustained BP elevation or an unusual jump over the last 7 days."""
    settings = settings_service.get_settings_snapshot(user_id)
    elevation_sys = float(settings.get("bp_elevation_systolic", 130))
    elevation_dia = float(settings.get("bp_elevation_diastolic", 80))
    delta_sys = float(settings.get("bp_delta_systolic", 10))
    delta_dia = float(settings.get("bp_delta_diastolic", 6))

    df = health_frame(user_id, days=30).dropna(subset=["bp_systolic", "bp_diastolic"])
    recent = df.tail(7)
    if len(recent) < 3:
        return []
    recent_sys = float(recent["bp_systolic"].mean())
    recent_dia = float(recent["bp_diastolic"].mean())

    # Compare the last 7 days against the previous 7 days when available,
    # otherwise fall back to all earlier readings.
    if len(df) >= 14:
        prior = df.iloc[-14:-7]
    elif len(df) > 7:
        prior = df.iloc[:-7]
    else:
        prior = df.iloc[:0]

    if len(prior) >= 3:
        prior_sys = float(prior["bp_systolic"].mean())
        prior_dia = float(prior["bp_diastolic"].mean())
    else:
        prior_sys, prior_dia = recent_sys, recent_dia

    sys_delta = recent_sys - prior_sys
    dia_delta = recent_dia - prior_dia

    # Sustained elevation: configured threshold (default hypertension stage 1).
    elevated = recent_sys >= elevation_sys or recent_dia >= elevation_dia
    # Unusual delta: sharp jump vs the user's own recent baseline.
    jumped = sys_delta >= delta_sys or dia_delta >= delta_dia

    if not elevated and not jumped:
        return []

    if elevated:
        body = f"Average {recent_sys:.0f}/{recent_dia:.0f} mmHg"
        if (prior_sys, prior_dia) != (recent_sys, recent_dia):
            body += f" (was {prior_sys:.0f}/{prior_dia:.0f})."
        return [
            InsightDraft(
                Domain.health,
                InsightSeverity.warning,
                "Blood pressure is elevated over the last 7 days.",
                body,
                "blood_pressure_elevated",
                round(recent_sys, 1),
            )
        ]
    return [
        InsightDraft(
            Domain.health,
            InsightSeverity.info,
            "Blood pressure jumped compared to your recent baseline.",
            f"Average {recent_sys:.0f}/{recent_dia:.0f} mmHg vs prior "
            f"{prior_sys:.0f}/{prior_dia:.0f} mmHg (+{sys_delta:.0f}/{dia_delta:.0f}).",
            "blood_pressure_jump",
            round(sys_delta, 1),
        )
    ]


RULES: list[Callable[[int], list[InsightDraft]]] = [
    rule_spending_vs_last_month,
    rule_sleep_week_over_week,
    rule_deep_work_week_over_week,
    rule_training_consistency,
    rule_resting_hr_elevated,
    rule_running_volume_spike,
    rule_mindfulness_consistency,
    rule_mood_lower_on_short_sleep,
    rule_project_output_vs_average,
    rule_blood_pressure_elevation,
]


def generate_insights(user_id: int, *, replace: bool = True) -> int:
    """Run all rules and persist insights. Returns count written."""
    drafts: list[InsightDraft] = []
    for rule in RULES:
        try:
            drafts.extend(rule(user_id))
        except Exception:  # pragma: no cover - one bad rule shouldn't kill the run
            log.exception("Insight rule failed: %s", rule.__name__)

    with session_scope() as s:
        if replace:
            s.execute(delete(Insight).where(Insight.user_id == user_id))
        for d in drafts:
            s.add(
                Insight(
                    user_id=user_id,
                    domain=d.domain,
                    severity=d.severity,
                    title=d.title,
                    body=d.body,
                    rule_key=d.rule_key,
                    metric_value=d.metric_value,
                )
            )
    log.info("Generated %d insights for user %s", len(drafts), user_id)
    return len(drafts)
