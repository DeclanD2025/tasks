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
    CalendarEvent,
    CaptureInboxItem,
    HealthMetricDaily,
    Insight,
    Project,
    ProjectMetricDaily,
    Task,
    Transaction,
    User,
    utcnow,
)


@dataclass
class Metric:
    """A compact metric card payload."""

    label: str
    value: str
    delta: str = ""  # e.g. "+4.2%"
    trend: str = "flat"  # up | down | flat  (drives the arrow glyph)
    series: list[float] | None = None  # optional sparkline data
    # Optional semantic colour override. When set, the delta/sparkline colour
    # follows the tone (good/bad/neutral) instead of the arrow direction — so a
    # metric where "up is bad" (e.g. job jeopardy) can show a red rising arrow.
    tone: str | None = None  # good | bad | neutral | None


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
                HealthMetricDaily.extra,
            )
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    df = pd.DataFrame(
        rows,
        columns=["day", "sleep_minutes", "hrv_ms", "resting_hr", "weight_kg", "extra"],
    )
    for col in ("bp_systolic", "bp_diastolic"):
        df[col] = df["extra"].apply(lambda x: (x or {}).get(col))
    return df.drop(columns=["extra"]).sort_values("day")


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


def project_portfolio(user_id: int, days: int = 30) -> list[dict]:
    """Per-project operating readout for the Projects page."""
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        projects = s.scalars(
            select(Project).where(Project.user_id == user_id).order_by(Project.status, Project.name)
        ).all()
        project_ids = [p.id for p in projects]
        rows = []
        if project_ids:
            rows = s.execute(
                select(
                    ProjectMetricDaily.project_id,
                    ProjectMetricDaily.day,
                    ProjectMetricDaily.commits,
                    ProjectMetricDaily.words_written,
                    ProjectMetricDaily.tasks_done,
                    ProjectMetricDaily.momentum,
                )
                .where(ProjectMetricDaily.project_id.in_(project_ids))
                .where(ProjectMetricDaily.day >= since)
            ).all()
    if not projects:
        return []
    if rows:
        df = pd.DataFrame(
            rows,
            columns=["project_id", "day", "commits", "words", "tasks", "momentum"],
        )
    else:
        df = pd.DataFrame(columns=["project_id", "day", "commits", "words", "tasks", "momentum"])

    out: list[dict] = []
    today = date.today()
    for project in projects:
        pdf = df[df["project_id"] == project.id].sort_values("day")
        last = pdf.tail(1)
        prev = pdf.iloc[-8:-1] if len(pdf) > 1 else pdf.iloc[0:0]
        last_day = last["day"].iloc[0] if not last.empty else None
        latest_momentum = float(last["momentum"].iloc[0]) if not last.empty else 0.0
        prev_momentum = float(prev["momentum"].mean()) if not prev.empty else latest_momentum
        delta = latest_momentum - prev_momentum
        stale_days = (today - last_day).days if last_day else None
        out.append({
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "momentum": latest_momentum,
            "delta": delta,
            "trend": _trend(delta),
            "series": pdf["momentum"].fillna(0).tolist(),
            "commits": int(pdf["commits"].fillna(0).sum()) if not pdf.empty else 0,
            "words": int(pdf["words"].fillna(0).sum()) if not pdf.empty else 0,
            "tasks": int(pdf["tasks"].fillna(0).sum()) if not pdf.empty else 0,
            "stale_days": stale_days,
            "last_day": last_day,
        })
    return out


def add_project(user_id: int, name: str) -> int:
    with session_scope() as s:
        row = Project(user_id=user_id, name=name.strip() or "New project", status="active")
        s.add(row)
        s.flush()
        return row.id


def update_project(project_id: int, *, name: str | None = None, status: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(Project, project_id)
        if row is None:
            return
        if name is not None and name.strip():
            row.name = name.strip()
        if status is not None:
            row.status = status.strip() or row.status


# --------------------------------------------------------------------------- #
# Calendar (iOS / iCloud mirror via EventKit)
# --------------------------------------------------------------------------- #
def calendar_events(
    user_id: int, *, days_back: int = 1, days_forward: int = 30
) -> list[dict]:
    """Upcoming (and lightly back-dated) calendar events for the Calendar page."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    lo = now - timedelta(days=days_back)
    hi = now + timedelta(days=days_forward)
    with session_scope() as s:
        rows = s.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.user_id == user_id)
            .where(CalendarEvent.starts_at >= lo)
            .where(CalendarEvent.starts_at <= hi)
            .order_by(CalendarEvent.starts_at.asc())
        ).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "location": r.location,
                "calendar_name": r.calendar_name,
                "starts_at": r.starts_at,
                "ends_at": r.ends_at,
                "all_day": bool(r.all_day),
            }
            for r in rows
        ]


def calendar_event_count(user_id: int) -> int:
    with session_scope() as s:
        return s.query(CalendarEvent).filter_by(user_id=user_id).count()


# --------------------------------------------------------------------------- #
# Tasks (two-way sync with the companion tasks app)
# --------------------------------------------------------------------------- #
def get_tasks(user_id: int, *, include_done: bool = True) -> list[dict]:
    """All locally-mirrored tasks, grouped-friendly order (area, sort, due)."""
    with session_scope() as s:
        q = (
            select(Task)
            .where(Task.user_id == user_id)
            .where(Task.pending_delete == 0)
            .order_by(Task.area.asc(), Task.sort_order.asc(), Task.due_date.asc())
        )
        if not include_done:
            q = q.where(Task.status != "done")
        rows = s.scalars(q).all()
        return [
            {
                "id": r.id,
                "ext_id": r.ext_id,
                "title": r.title,
                "area": r.area or "Unsorted",
                "category": r.category,
                "priority": r.priority,
                "status": r.status,
                "notes": r.notes,
                "due_date": r.due_date,
                "recurrence": r.recurrence,
                "completed_at": r.completed_at,
                "dirty": bool(r.dirty),
            }
            for r in rows
        ]


def task_counts(user_id: int) -> dict:
    with session_scope() as s:
        rows = s.scalars(
            select(Task).where(
                Task.user_id == user_id, Task.pending_delete == 0
            )
        ).all()
        open_n = sum(1 for r in rows if r.status != "done")
        done_n = sum(1 for r in rows if r.status == "done")
        return {"open": open_n, "done": done_n, "total": len(rows)}


def set_task_done(task_id: int, done: bool = True) -> None:
    """Mark a task done/open locally and queue it for push to Supabase."""
    with session_scope() as s:
        row = s.get(Task, task_id)
        if row is None:
            return
        row.status = "done" if done else "open"
        row.completed_at = utcnow() if done else None
        row.dirty = 1


def update_task(
    task_id: int,
    *,
    title: str | None = None,
    area: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    notes: str | None = None,
) -> None:
    """Edit a task locally and queue it for push to Supabase."""
    with session_scope() as s:
        row = s.get(Task, task_id)
        if row is None:
            return
        if title is not None and title.strip():
            row.title = title.strip()
        if area is not None:
            row.area = area.strip() or None
        if category is not None:
            row.category = category.strip() or None
        if priority is not None:
            row.priority = priority
        if notes is not None:
            row.notes = notes
        row.dirty = 1


def add_task(
    user_id: int,
    title: str,
    *,
    area: str | None = None,
    category: str | None = None,
    priority: str = "medium",
    notes: str | None = None,
    due_date: date | None = None,
) -> int:
    """Create a task locally; first sync pushes it to Supabase (assigns ext_id)."""
    with session_scope() as s:
        row = Task(
            user_id=user_id,
            title=title.strip() or "New task",
            area=area,
            category=category,
            priority=priority,
            notes=notes,
            due_date=due_date,
            status="open",
            dirty=1,
        )
        s.add(row)
        s.flush()
        return row.id


def delete_task(task_id: int) -> None:
    """Queue a task for deletion (removed remotely + locally on next sync)."""
    with session_scope() as s:
        row = s.get(Task, task_id)
        if row is None:
            return
        if row.ext_id:
            row.pending_delete = 1
            row.dirty = 1
        else:
            # Never pushed — safe to drop immediately.
            s.delete(row)


# --------------------------------------------------------------------------- #
# Capture inbox
# --------------------------------------------------------------------------- #
def add_capture_inbox_item(
    user_id: int,
    text: str,
    *,
    source: str = "desktop",
    extra: dict | None = None,
) -> int:
    """Create a quick-capture item for later triage and CloudKit sync."""
    with session_scope() as s:
        row = CaptureInboxItem(
            user_id=user_id,
            text=text.strip(),
            source=source,
            status="new",
            extra=extra or {},
            dirty=1,
        )
        s.add(row)
        s.flush()
        return row.id


def capture_inbox_items(user_id: int, *, limit: int = 50) -> list[dict]:
    """Recent untriaged quick-capture items."""
    with session_scope() as s:
        rows = s.scalars(
            select(CaptureInboxItem)
            .where(CaptureInboxItem.user_id == user_id)
            .where(CaptureInboxItem.pending_delete == 0)
            .order_by(CaptureInboxItem.created_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "text": row.text,
                "source": row.source,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]


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
