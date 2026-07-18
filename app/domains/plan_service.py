"""Habits and goals: the operator's own intentions.

This is the one domain with no upstream connector — every row here is entered
by hand, so there is nothing to sync and nothing to reconcile. What that buys
us is that the data is never stale; what it costs is that an empty habits list
means "none created", not "none synced", and the UI must say so.

Streaks, completion rates and goal progress are **computed on read, never
stored**. A stored streak is a second source of truth that drifts the moment an
entry is backfilled or removed; deriving it from the entries means the number
shown is always the number the entries justify.

All reads go through :func:`get_plan_snapshot` so the Plan page is one query
pass rather than one per habit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import Goal, Habit, HabitEntry
from app.domains.health import metric_details


CADENCES = ("daily", "weekly")
DIRECTIONS = ("increase", "decrease")
GOAL_STATUSES = ("active", "achieved", "abandoned")
# Mirrors frontend/lib/domains.ts — a habit inherits its domain's colour.
DOMAINS = (
    "sleep", "recovery", "running", "strength",
    "cardio", "mind", "nutrition", "meds", "neutral",
)

_HISTORY_DAYS = 84  # 12 weeks: enough for a weekly streak to mean something.


class PlanError(ValueError):
    """Raised when a caller supplies a value the plan domain will not accept."""


# --------------------------------------------------------------------------- #
# Views (what the UI receives)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HabitView:
    id: int
    name: str
    detail: str | None
    domain: str
    cadence: str
    target_per_period: int
    streak: int
    best_streak: int
    period_done: int          # completions in the current day/week
    period_target: int
    completion_rate: float    # 0-1 over the history window, target-aware
    done_today: bool
    history: list[dict] = field(default_factory=list)  # [{day, count}] ascending
    archived: bool = False


@dataclass(frozen=True)
class GoalView:
    id: int
    title: str
    detail: str | None
    domain: str
    unit: str
    direction: str
    status: str
    target_value: float | None
    baseline_value: float | None
    current_value: float | None
    progress: float | None     # 0-1, or None when it cannot be computed honestly
    source: str                # "measured" | "manual" | "none"
    metric_kind: str | None
    start_date: date | None
    target_date: date | None
    days_remaining: int | None


# --------------------------------------------------------------------------- #
# Habits
# --------------------------------------------------------------------------- #
def _week_start(day: date) -> date:
    """Monday of the week containing ``day`` (ISO weeks, matching the UI grid)."""
    return day - timedelta(days=day.weekday())


def _daily_streak(days_done: set[date], today: date) -> int:
    """Consecutive days done, counting back from today.

    Today not being done yet does not break the streak — the day is still in
    progress — so counting starts at yesterday in that case. Missing yesterday
    *does* break it.
    """
    cursor = today if today in days_done else today - timedelta(days=1)
    streak = 0
    while cursor in days_done:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _weekly_streak(days_done: set[date], today: date, target: int) -> int:
    """Consecutive weeks that met the target, counting back from this week.

    The current week is only counted once it has met its target, but an unmet
    current week does not break the run — there may still be days left in it.
    """
    per_week: dict[date, int] = {}
    for day in days_done:
        per_week[_week_start(day)] = per_week.get(_week_start(day), 0) + 1

    this_week = _week_start(today)
    cursor = this_week
    streak = 0
    if per_week.get(this_week, 0) < target:
        cursor = this_week - timedelta(days=7)  # still in progress; look back
    while per_week.get(cursor, 0) >= target:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def _best_daily_streak(days_done: set[date]) -> int:
    if not days_done:
        return 0
    best = run = 1
    ordered = sorted(days_done)
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if cur - prev == timedelta(days=1) else 1
        best = max(best, run)
    return best


def _completion_rate(days_done: set[date], habit: Habit, today: date) -> float:
    """How much of the commitment was met over the history window.

    Judged against the habit's own target, so a "3x per week" habit done three
    times reads as 100%, not 43%. Only counts periods since the habit existed,
    so a habit created yesterday is not penalised for last month.
    """
    created = habit.created_at.date() if habit.created_at else today
    start = max(created, today - timedelta(days=_HISTORY_DAYS))
    if start > today:
        return 0.0

    if habit.cadence == "weekly":
        target = max(1, habit.target_per_period)
        weeks: dict[date, int] = {}
        cursor = _week_start(start)
        while cursor <= today:
            weeks[cursor] = 0
            cursor += timedelta(days=7)
        for day in days_done:
            ws = _week_start(day)
            if ws in weeks:
                weeks[ws] += 1
        if not weeks:
            return 0.0
        return mean(min(1.0, done / target) for done in weeks.values())

    span = (today - start).days + 1
    if span <= 0:
        return 0.0
    return min(1.0, len([d for d in days_done if d >= start]) / span)


def _habit_view(habit: Habit, entries: list[HabitEntry], today: date) -> HabitView:
    days_done = {e.day for e in entries}
    counts = {e.day: e.count for e in entries}
    target = max(1, habit.target_per_period)

    if habit.cadence == "weekly":
        streak = _weekly_streak(days_done, today, target)
        week_start = _week_start(today)
        period_done = len([d for d in days_done if _week_start(d) == week_start])
    else:
        streak = _daily_streak(days_done, today)
        period_done = counts.get(today, 0)

    window_start = today - timedelta(days=_HISTORY_DAYS)
    history = [
        {"day": d.isoformat(), "count": counts[d]}
        for d in sorted(days_done)
        if d >= window_start
    ]

    return HabitView(
        id=habit.id,
        name=habit.name,
        detail=habit.detail,
        domain=habit.domain,
        cadence=habit.cadence,
        target_per_period=target,
        streak=streak,
        best_streak=_best_daily_streak(days_done),
        period_done=period_done,
        period_target=target,
        completion_rate=round(_completion_rate(days_done, habit, today), 3),
        done_today=today in days_done,
        history=history,
        archived=habit.archived_at is not None,
    )


def list_habits(uid: int, *, include_archived: bool = False) -> list[HabitView]:
    today = date.today()
    with session_scope() as session:
        stmt = select(Habit).where(Habit.user_id == uid)
        if not include_archived:
            stmt = stmt.where(Habit.archived_at.is_(None))
        habits = list(session.scalars(stmt.order_by(Habit.sort_order, Habit.id)))
        if not habits:
            return []

        cutoff = today - timedelta(days=_HISTORY_DAYS)
        rows = list(
            session.scalars(
                select(HabitEntry).where(
                    HabitEntry.habit_id.in_([h.id for h in habits]),
                    HabitEntry.day >= cutoff,
                )
            )
        )
        by_habit: dict[int, list[HabitEntry]] = {h.id: [] for h in habits}
        for row in rows:
            by_habit[row.habit_id].append(row)

        return [_habit_view(h, by_habit[h.id], today) for h in habits]


def create_habit(
    uid: int,
    name: str,
    *,
    detail: str | None = None,
    domain: str = "neutral",
    cadence: str = "daily",
    target_per_period: int = 1,
) -> int:
    name = (name or "").strip()
    if not name:
        raise PlanError("A habit needs a name.")
    if cadence not in CADENCES:
        raise PlanError(f"Cadence must be one of {', '.join(CADENCES)}.")
    if domain not in DOMAINS:
        raise PlanError(f"Unknown domain '{domain}'.")
    target = max(1, int(target_per_period or 1))
    if cadence == "weekly" and target > 7:
        raise PlanError("A weekly target cannot exceed 7.")

    with session_scope() as session:
        highest = session.scalar(
            select(Habit.sort_order).where(Habit.user_id == uid)
            .order_by(Habit.sort_order.desc()).limit(1)
        )
        habit = Habit(
            user_id=uid,
            name=name[:160],
            detail=(detail or "").strip() or None,
            domain=domain,
            cadence=cadence,
            target_per_period=target,
            sort_order=(highest or 0) + 1,
        )
        session.add(habit)
        session.flush()
        return habit.id


def set_habit_day(uid: int, habit_id: int, day: date, done: bool) -> HabitView:
    """Record or clear one day for a habit, and return the habit's fresh view.

    Returning the recomputed view means the caller never has to guess what the
    streak became — it is derived from the entries that now exist.
    """
    today = date.today()
    if day > today:
        raise PlanError("A habit cannot be ticked for a future day.")

    with session_scope() as session:
        habit = session.scalar(
            select(Habit).where(Habit.id == habit_id, Habit.user_id == uid)
        )
        if habit is None:
            raise PlanError("Habit not found.")

        existing = session.scalar(
            select(HabitEntry).where(
                HabitEntry.habit_id == habit_id, HabitEntry.day == day
            )
        )
        if done and existing is None:
            session.add(HabitEntry(habit_id=habit_id, user_id=uid, day=day, count=1))
        elif not done and existing is not None:
            session.delete(existing)
        session.flush()

        cutoff = today - timedelta(days=_HISTORY_DAYS)
        entries = list(
            session.scalars(
                select(HabitEntry).where(
                    HabitEntry.habit_id == habit_id, HabitEntry.day >= cutoff
                )
            )
        )
        return _habit_view(habit, entries, today)


def archive_habit(uid: int, habit_id: int, *, archived: bool = True) -> None:
    with session_scope() as session:
        habit = session.scalar(
            select(Habit).where(Habit.id == habit_id, Habit.user_id == uid)
        )
        if habit is None:
            raise PlanError("Habit not found.")
        habit.archived_at = datetime.now(timezone.utc) if archived else None


def delete_habit(uid: int, habit_id: int) -> None:
    """Remove a habit and its entries outright.

    Prefer :func:`archive_habit` — deleting discards the record of what was
    actually done. This exists for genuine mistakes.
    """
    with session_scope() as session:
        habit = session.scalar(
            select(Habit).where(Habit.id == habit_id, Habit.user_id == uid)
        )
        if habit is None:
            raise PlanError("Habit not found.")
        session.delete(habit)


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #
def _measured_value(uid: int, kind: str, window_days: int) -> float | None:
    """Current value for a metric-backed goal: the mean of its recent window.

    A single day is too noisy to judge a goal against, so this averages the
    window. Returns None when the metric has no data, which the caller must
    surface as "not measured yet" rather than as zero progress.
    """
    if kind not in metric_details.METRIC_SPECS:
        return None
    window = max(1, min(int(window_days or 7), 90))
    series = metric_details._series_for(uid, kind, window)
    values = [p["value"] for p in series if p.get("value") is not None]
    return round(mean(values), 2) if values else None


def _progress(
    current: float | None, baseline: float | None, target: float | None, direction: str
) -> float | None:
    """Fraction of the way from baseline to target, clamped to 0-1.

    Without a target there is no progress to compute, and without a baseline we
    fall back to current/target — which is only meaningful for "increase" goals
    starting from nothing, so decrease goals return None rather than a number
    that looks precise and means nothing.
    """
    if current is None or target is None:
        return None
    if baseline is None:
        if direction == "decrease" or target == 0:
            return None
        return max(0.0, min(1.0, current / target))
    if baseline == target:
        return None
    span = target - baseline
    return max(0.0, min(1.0, (current - baseline) / span))


def _goal_view(goal: Goal, uid: int, today: date) -> GoalView:
    if goal.metric_kind:
        current = _measured_value(uid, goal.metric_kind, goal.metric_window_days)
        source = "measured" if current is not None else "none"
    elif goal.manual_value is not None:
        current = goal.manual_value
        source = "manual"
    else:
        current = None
        source = "none"

    days_remaining = (goal.target_date - today).days if goal.target_date else None

    return GoalView(
        id=goal.id,
        title=goal.title,
        detail=goal.detail,
        domain=goal.domain,
        unit=goal.unit,
        direction=goal.direction,
        status=goal.status,
        target_value=goal.target_value,
        baseline_value=goal.baseline_value,
        current_value=current,
        progress=_progress(current, goal.baseline_value, goal.target_value, goal.direction),
        source=source,
        metric_kind=goal.metric_kind,
        start_date=goal.start_date,
        target_date=goal.target_date,
        days_remaining=days_remaining,
    )


def list_goals(uid: int, *, include_closed: bool = False) -> list[GoalView]:
    today = date.today()
    with session_scope() as session:
        stmt = select(Goal).where(Goal.user_id == uid)
        if not include_closed:
            stmt = stmt.where(Goal.status == "active")
        goals = list(session.scalars(stmt.order_by(Goal.sort_order, Goal.id)))
        return [_goal_view(g, uid, today) for g in goals]


def create_goal(
    uid: int,
    title: str,
    *,
    detail: str | None = None,
    domain: str = "neutral",
    metric_kind: str | None = None,
    metric_window_days: int = 7,
    baseline_value: float | None = None,
    target_value: float | None = None,
    manual_value: float | None = None,
    unit: str = "",
    direction: str = "increase",
    start_date: date | None = None,
    target_date: date | None = None,
) -> int:
    title = (title or "").strip()
    if not title:
        raise PlanError("A goal needs a title.")
    if direction not in DIRECTIONS:
        raise PlanError(f"Direction must be one of {', '.join(DIRECTIONS)}.")
    if domain not in DOMAINS:
        raise PlanError(f"Unknown domain '{domain}'.")
    if metric_kind and metric_kind not in metric_details.METRIC_SPECS:
        raise PlanError(f"ORION does not measure '{metric_kind}'.")
    if target_date and start_date and target_date < start_date:
        raise PlanError("A goal cannot be due before it starts.")

    with session_scope() as session:
        highest = session.scalar(
            select(Goal.sort_order).where(Goal.user_id == uid)
            .order_by(Goal.sort_order.desc()).limit(1)
        )
        goal = Goal(
            user_id=uid,
            title=title[:200],
            detail=(detail or "").strip() or None,
            domain=domain,
            metric_kind=metric_kind,
            metric_window_days=max(1, min(int(metric_window_days or 7), 90)),
            baseline_value=baseline_value,
            target_value=target_value,
            manual_value=manual_value,
            unit=(unit or "").strip()[:24],
            direction=direction,
            start_date=start_date or date.today(),
            target_date=target_date,
            sort_order=(highest or 0) + 1,
        )
        session.add(goal)
        session.flush()
        return goal.id


def update_goal(uid: int, goal_id: int, **changes) -> GoalView:
    """Apply a partial update. Only known, validated fields are accepted."""
    allowed = {
        "title", "detail", "domain", "metric_kind", "metric_window_days",
        "baseline_value", "target_value", "manual_value", "unit", "direction",
        "start_date", "target_date", "status",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise PlanError(f"Cannot set {', '.join(sorted(unknown))} on a goal.")
    if "direction" in changes and changes["direction"] not in DIRECTIONS:
        raise PlanError(f"Direction must be one of {', '.join(DIRECTIONS)}.")
    if "status" in changes and changes["status"] not in GOAL_STATUSES:
        raise PlanError(f"Status must be one of {', '.join(GOAL_STATUSES)}.")
    if "domain" in changes and changes["domain"] not in DOMAINS:
        raise PlanError(f"Unknown domain '{changes['domain']}'.")
    if changes.get("metric_kind") and changes["metric_kind"] not in metric_details.METRIC_SPECS:
        raise PlanError(f"ORION does not measure '{changes['metric_kind']}'.")

    with session_scope() as session:
        goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == uid))
        if goal is None:
            raise PlanError("Goal not found.")
        for key, value in changes.items():
            setattr(goal, key, value)
        session.flush()
        return _goal_view(goal, uid, date.today())


def delete_goal(uid: int, goal_id: int) -> None:
    with session_scope() as session:
        goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == uid))
        if goal is None:
            raise PlanError("Goal not found.")
        session.delete(goal)


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #
def get_plan_snapshot(uid: int) -> dict:
    """Everything the Plan page needs for habits and goals, in one pass."""
    habits = list_habits(uid)
    goals = list_goals(uid)
    return {
        "habits": habits,
        "goals": goals,
        "habits_tracked": len(habits),
        "habits_done_today": len([h for h in habits if h.done_today]),
        "goals_active": len(goals),
    }
