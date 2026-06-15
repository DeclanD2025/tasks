"""Read-model services that the UI consumes.

This is the boundary between the UI and the database. UI screens never touch
the ORM directly — they call these functions, which return plain dicts /
dataclasses. That keeps the desktop UI decoupled and makes it trivial to swap
SQLite for PostgreSQL, or to move these onto a background thread.

All functions are read-only and operate on a single local user.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import desc, select

from app.db.database import session_scope
from app.db.models import (
    Account,
    ActivityMetricDaily,
    BalanceSnapshot,
    HealthMetricDaily,
    Insight,
    Project,
    ProjectMetricDaily,
    Transaction,
    User,
)


@dataclass
class Metric:
    """A compact metric card payload."""

    label: str
    value: str
    delta: str = ""  # e.g. "+4.2%"
    trend: str = "flat"  # up | down | flat
    series: list[float] | None = None  # optional sparkline data


def get_default_user_id() -> int | None:
    with session_scope() as s:
        user = s.scalars(select(User).limit(1)).first()
        return user.id if user else None


# --------------------------------------------------------------------------- #
# Finance
# --------------------------------------------------------------------------- #
def net_worth_series(user_id: int, days: int = 30) -> pd.DataFrame:
    """Total balance across all accounts per day."""
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(BalanceSnapshot.snapshot_date, BalanceSnapshot.balance_minor)
            .join(BalanceSnapshot.account)
            .where(BalanceSnapshot.snapshot_date >= since)
        ).all()
    if not rows:
        return pd.DataFrame(columns=["day", "value"])
    df = pd.DataFrame(rows, columns=["day", "balance_minor"])
    grouped = df.groupby("day", as_index=False)["balance_minor"].sum()
    grouped["value"] = grouped["balance_minor"] / 100.0
    return grouped[["day", "value"]].sort_values("day")


def monthly_spending(user_id: int) -> pd.DataFrame:
    """Spending (negative txns) grouped by calendar month, last ~3 months."""
    since = date.today() - timedelta(days=95)
    with session_scope() as s:
        rows = s.execute(
            select(Transaction.booked_at, Transaction.amount_minor, Transaction.category)
            .where(Transaction.booked_at >= since)
            .where(Transaction.amount_minor < 0)
        ).all()
    if not rows:
        return pd.DataFrame(columns=["month", "spend"])
    df = pd.DataFrame(rows, columns=["booked_at", "amount_minor", "category"])
    df["month"] = pd.to_datetime(df["booked_at"]).dt.to_period("M").astype(str)
    df["spend"] = -df["amount_minor"] / 100.0
    return df.groupby("month", as_index=False)["spend"].sum()


def account_snapshot_latest(user_id: int) -> list[dict]:
    """Latest balance per account, in major currency units."""
    with session_scope() as s:
        rows = s.execute(
            select(
                Account.name,
                Account.kind,
                Account.currency,
                BalanceSnapshot.snapshot_date,
                BalanceSnapshot.balance_minor,
            )
            .join(BalanceSnapshot, BalanceSnapshot.account_id == Account.id)
            .where(Account.user_id == user_id)
        ).all()
    if not rows:
        return []
    df = pd.DataFrame(
        rows,
        columns=["name", "kind", "currency", "snapshot_date", "balance_minor"],
    )
    latest = (
        df.sort_values("snapshot_date")
        .groupby(["name", "kind", "currency"], as_index=False)
        .tail(1)
        .copy()
    )
    latest["value"] = latest["balance_minor"] / 100.0
    return latest.sort_values("value", ascending=False)[
        ["name", "kind", "currency", "value", "snapshot_date"]
    ].to_dict("records")


def spending_by_category(user_id: int, days: int = 30) -> list[dict]:
    """Negative transactions grouped by category for the recent window."""
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(Transaction.category, Transaction.amount_minor)
            .join(Account, Transaction.account_id == Account.id)
            .where(Account.user_id == user_id)
            .where(Transaction.booked_at >= since)
            .where(Transaction.amount_minor < 0)
        ).all()
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["category", "amount_minor"])
    df["spend"] = -df["amount_minor"] / 100.0
    grouped = df.groupby("category", as_index=False)["spend"].sum()
    return grouped.sort_values("spend", ascending=False).to_dict("records")


def recent_transactions(user_id: int, limit: int = 6) -> list[dict]:
    """Most recent normalised transactions for the finance terminal."""
    with session_scope() as s:
        rows = s.execute(
            select(
                Transaction.booked_at,
                Transaction.description,
                Transaction.category,
                Transaction.amount_minor,
                Transaction.currency,
                Account.name,
            )
            .join(Account, Transaction.account_id == Account.id)
            .where(Account.user_id == user_id)
            .order_by(desc(Transaction.booked_at), desc(Transaction.id))
            .limit(limit)
        ).all()
    return [
        {
            "booked_at": booked_at,
            "description": description,
            "category": category,
            "amount": amount_minor / 100.0,
            "currency": currency,
            "account": account,
        }
        for booked_at, description, category, amount_minor, currency, account in rows
    ]


# --------------------------------------------------------------------------- #
# Health / activity
# --------------------------------------------------------------------------- #
def health_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(
                HealthMetricDaily.day,
                HealthMetricDaily.sleep_minutes,
                HealthMetricDaily.hrv_ms,
                HealthMetricDaily.resting_hr,
                HealthMetricDaily.weight_kg,
            )
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    return pd.DataFrame(
        rows,
        columns=["day", "sleep_minutes", "hrv_ms", "resting_hr", "weight_kg"],
    ).sort_values("day")


def mood_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    """Daily mood valence in [-1, 1], read from HealthMetricDaily.extra['mood'].

    Sourced from Apple Health 'State of Mind' logs (iOS 17+). Days without a
    mood entry are omitted, so an empty frame means 'no mood signal yet'.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    records = [
        {"day": day, "mood": (extra or {}).get("mood")}
        for day, extra in rows
        if (extra or {}).get("mood") is not None
    ]
    return pd.DataFrame(records, columns=["day", "mood"]).sort_values("day")


def practice_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    """Daily mindful minutes, read from HealthMetricDaily.extra['mindful_minutes'].

    Sourced from Apple Health Mindfulness sessions — which the Stoic app (and
    Mindfulness/Calm/etc.) write. Their presence is our no-double-entry evidence
    that a reflective practice happened that day. Empty frame => no signal yet.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    records = [
        {"day": day, "mindful_minutes": (extra or {}).get("mindful_minutes")}
        for day, extra in rows
        if (extra or {}).get("mindful_minutes") is not None
    ]
    return pd.DataFrame(records, columns=["day", "mindful_minutes"]).sort_values("day")


def activity_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(
                ActivityMetricDaily.day,
                ActivityMetricDaily.deep_work_minutes,
                ActivityMetricDaily.active_minutes,
                ActivityMetricDaily.training_load,
                ActivityMetricDaily.steps,
            )
            .where(ActivityMetricDaily.user_id == user_id)
            .where(ActivityMetricDaily.day >= since)
        ).all()
    return pd.DataFrame(
        rows,
        columns=["day", "deep_work_minutes", "active_minutes", "training_load", "steps"],
    ).sort_values("day")


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
def project_momentum(user_id: int) -> pd.DataFrame:
    with session_scope() as s:
        rows = s.execute(
            select(Project.name, ProjectMetricDaily.day, ProjectMetricDaily.momentum)
            .join(ProjectMetricDaily, ProjectMetricDaily.project_id == Project.id)
            .where(Project.user_id == user_id)
        ).all()
    return pd.DataFrame(rows, columns=["project", "day", "momentum"])


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #
def latest_insights(user_id: int, limit: int = 20) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(Insight)
            .where(Insight.user_id == user_id)
            .order_by(Insight.created_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "domain": r.domain.value,
                "severity": r.severity.value,
                "title": r.title,
                "body": r.body,
                "created_at": r.created_at,
            }
            for r in rows
        ]


# --------------------------------------------------------------------------- #
# Overview metric cards
# --------------------------------------------------------------------------- #
def _trend(delta: float) -> str:
    if delta > 0.5:
        return "up"
    if delta < -0.5:
        return "down"
    return "flat"


def overview_metrics(user_id: int) -> list[Metric]:
    """Build the placeholder Overview metric cards from real seeded data."""
    metrics: list[Metric] = []

    nw = net_worth_series(user_id)
    if not nw.empty:
        latest = nw["value"].iloc[-1]
        first = nw["value"].iloc[0]
        pct = (latest - first) / first * 100 if first else 0.0
        metrics.append(
            Metric(
                "Net Worth",
                f"£{latest:,.0f}",
                f"{pct:+.1f}%",
                _trend(pct),
                nw["value"].tolist(),
            )
        )

    ms = monthly_spending(user_id)
    if not ms.empty:
        latest = ms["spend"].iloc[-1]
        prev = ms["spend"].iloc[-2] if len(ms) > 1 else latest
        pct = (latest - prev) / prev * 100 if prev else 0.0
        metrics.append(Metric("Monthly Spending", f"£{latest:,.0f}", f"{pct:+.1f}%", _trend(pct)))

    hf = health_frame(user_id)
    if not hf.empty:
        avg_sleep = hf["sleep_minutes"].dropna().tail(7).mean()
        metrics.append(
            Metric(
                "Sleep Average",
                f"{avg_sleep / 60:.1f}h",
                trend="flat",
                series=(hf["sleep_minutes"] / 60).dropna().tolist(),
            )
        )
        hrv_recent = hf["hrv_ms"].dropna().tail(7).mean()
        hrv_prev = hf["hrv_ms"].dropna().head(7).mean()
        d = hrv_recent - hrv_prev
        metrics.append(
            Metric(
                "HRV Trend",
                f"{hrv_recent:.0f} ms",
                f"{d:+.0f} ms",
                _trend(d),
                hf["hrv_ms"].dropna().tolist(),
            )
        )

    af = activity_frame(user_id)
    if not af.empty:
        load = af["training_load"].dropna().tail(7).mean()
        metrics.append(
            Metric(
                "Training Load",
                f"{load:.0f}",
                trend="flat",
                series=af["training_load"].dropna().tolist(),
            )
        )
        dw = af["deep_work_minutes"].dropna().tail(7).sum() / 60
        metrics.append(
            Metric(
                "Deep Work Hours",
                f"{dw:.1f}h",
                trend="up",
                series=(af["deep_work_minutes"] / 60).dropna().tolist(),
            )
        )

    pm = project_momentum(user_id)
    if not pm.empty:
        mean_mom = pm["momentum"].dropna().mean()
        metrics.append(Metric("Project Momentum", f"{mean_mom:.0f}/100", trend="flat"))

    # Static placeholders for modules without seeded series yet.
    metrics.append(Metric("Writing Output", "—", trend="flat"))
    metrics.append(Metric("Calendar Load", "—", trend="flat"))

    insights = latest_insights(user_id, limit=1)
    weekly = insights[0]["title"] if insights else "No insights yet"
    metrics.append(Metric("Weekly Insight", weekly, trend="flat"))

    return metrics
