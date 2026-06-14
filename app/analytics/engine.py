"""Rule-based / statistical insight engine.

Each rule is a small pure function: given a user's recent data, it returns zero
or more `InsightDraft`s. The engine runs all rules and persists the results to
the `insights` table. Adding a new insight = adding a function to `RULES`.

NO LLM is involved. Phrasing is templated; numbers are computed with pandas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import delete

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import Domain, Insight, InsightSeverity
from app.services import (
    activity_frame,
    health_frame,
    monthly_spending,
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


RULES: list[Callable[[int], list[InsightDraft]]] = [
    rule_spending_vs_last_month,
    rule_sleep_week_over_week,
    rule_deep_work_week_over_week,
    rule_training_consistency,
    rule_project_output_vs_average,
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
