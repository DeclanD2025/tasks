"""Fitness module service — local, hand-editable training planner.

Two halves:
  1. The planner: an editable training block + drag-and-drop sessions on a month
     calendar. Persisted to SQLite (FitnessPlan / FitnessSession). No external
     integration — purely a local, easily-editable feature.
  2. Inferred metrics: distance ran, VO2 max, etc. read from Apple Health (which
     already flows through HealthMetricDaily.extra).

Strength lifted is intentionally absent: the user logs strength in Bevel, which
does not export data, so ORION does not fabricate it — strength sessions are
*planned* on the calendar but volume is not inferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import FitnessPlan, FitnessSession, HealthMetricDaily


# The draggable session palette. Colour-coded by training stimulus.
SESSION_TYPES: list[tuple[str, str]] = [
    ("ZONE 2 CARDIO", "#3ad6a0"),
    ("UPPER STRENGTH", "#2ee6ff"),
    ("LOWER STRENGTH", "#a06bff"),
    ("ENGINE RUN", "#ff9d3d"),
    ("LONG RUN", "#ff6b8a"),
    ("INTERVALS", "#ffd166"),
    ("FULL BODY", "#6c8cff"),
    ("MOBILITY", "#7fa3b0"),
    ("REST", "#4a6b78"),
]
SESSION_COLOR = dict(SESSION_TYPES)


@dataclass
class PlanInfo:
    id: int
    block_name: str
    start_date: date
    weeks: int

    @property
    def current_week(self) -> int:
        delta_days = (date.today() - self.start_date).days
        if delta_days < 0:
            return 0
        return min(self.weeks, delta_days // 7 + 1)

    @property
    def week_label(self) -> str:
        wk = self.current_week
        if wk <= 0:
            return f"STARTS {self.start_date.isoformat()}"
        return f"WEEK {wk} OF {self.weeks}"


@dataclass
class SessionItem:
    id: int
    day: date
    session_type: str
    color: str


@dataclass
class FitnessSnapshot:
    plan: PlanInfo
    sessions_by_day: dict[date, list[SessionItem]] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def get_or_create_plan(user_id: int) -> PlanInfo:
    with session_scope() as s:
        plan = s.scalars(
            select(FitnessPlan).where(
                FitnessPlan.user_id == user_id, FitnessPlan.is_active.is_(True)
            )
        ).first()
        if plan is None:
            # Sensible default: a 6-week block starting this Monday.
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            plan = FitnessPlan(
                user_id=user_id, block_name="Base Build — Block 1",
                start_date=monday, weeks=6, is_active=True,
            )
            s.add(plan)
            s.flush()
        return PlanInfo(plan.id, plan.block_name, plan.start_date, plan.weeks)


def update_plan(plan_id: int, *, block_name: str | None = None,
                start_date: date | None = None, weeks: int | None = None) -> None:
    with session_scope() as s:
        plan = s.get(FitnessPlan, plan_id)
        if plan is None:
            return
        if block_name is not None:
            plan.block_name = block_name.strip() or plan.block_name
        if start_date is not None:
            plan.start_date = start_date
        if weeks is not None:
            plan.weeks = max(1, min(52, weeks))


# --------------------------------------------------------------------------- #
# Sessions (the drag-and-drop calendar contents)
# --------------------------------------------------------------------------- #
def sessions_for_month(user_id: int, year: int, month: int) -> dict[date, list[SessionItem]]:
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    out: dict[date, list[SessionItem]] = {}
    with session_scope() as s:
        rows = s.scalars(
            select(FitnessSession)
            .where(
                FitnessSession.user_id == user_id,
                FitnessSession.day >= first,
                FitnessSession.day <= last,
            )
            .order_by(FitnessSession.day, FitnessSession.sort_order)
        ).all()
        for r in rows:
            out.setdefault(r.day, []).append(
                SessionItem(r.id, r.day, r.session_type, r.color)
            )
    return out


def add_session(user_id: int, day: date, session_type: str) -> int:
    color = SESSION_COLOR.get(session_type, "#2ee6ff")
    with session_scope() as s:
        existing = s.scalars(
            select(FitnessSession).where(
                FitnessSession.user_id == user_id, FitnessSession.day == day
            )
        ).all()
        row = FitnessSession(
            user_id=user_id, day=day, session_type=session_type,
            color=color, sort_order=len(existing),
        )
        s.add(row)
        s.flush()
        return row.id


def move_session(session_id: int, new_day: date) -> None:
    with session_scope() as s:
        row = s.get(FitnessSession, session_id)
        if row is not None:
            row.day = new_day


def delete_session(session_id: int) -> None:
    with session_scope() as s:
        row = s.get(FitnessSession, session_id)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# Inferred metrics (Apple Health)
# --------------------------------------------------------------------------- #
def fitness_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    """Per-day running distance and VO2 max from HealthMetricDaily.extra.

    Empty / None where Apple Health has no data — never fabricated.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.resting_hr,
                   HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    records = []
    for day, rhr, extra in rows:
        extra = extra or {}
        records.append({
            "day": day,
            "distance_km": extra.get("distance_km"),
            "vo2max": extra.get("vo2max"),
            "resting_hr": rhr,
        })
    return pd.DataFrame(
        records, columns=["day", "distance_km", "vo2max", "resting_hr"]
    ).sort_values("day")


def get_snapshot(user_id: int, year: int, month: int) -> FitnessSnapshot:
    return FitnessSnapshot(
        plan=get_or_create_plan(user_id),
        sessions_by_day=sessions_for_month(user_id, year, month),
    )
