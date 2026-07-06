"""Fitness module service — local, hand-editable training planner.

Two halves:
  1. The planner: an editable training block + drag-and-drop sessions on a
     three-week planner. Persisted to SQLite (FitnessPlan / FitnessSession). No external
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
from app.db.models import (
    FitnessCardTemplate,
    FitnessPlan,
    FitnessSession,
    HealthMetricDaily,
)


# Training categories used for strength/cardio breakdowns and plan focus.
CATEGORY_STRENGTH = "strength"
CATEGORY_CARDIO = "cardio"
CATEGORY_MOBILITY = "mobility"
CATEGORY_RECOVERY = "recovery"
CATEGORIES = (CATEGORY_STRENGTH, CATEGORY_CARDIO, CATEGORY_MOBILITY, CATEGORY_RECOVERY)
CATEGORY_LABELS = {
    CATEGORY_STRENGTH: "Strength",
    CATEGORY_CARDIO: "Cardio",
    CATEGORY_MOBILITY: "Mobility",
    CATEGORY_RECOVERY: "Recovery",
}
CATEGORY_COLORS = {
    CATEGORY_STRENGTH: "#2ee6ff",
    CATEGORY_CARDIO: "#ff9d3d",
    CATEGORY_MOBILITY: "#7fa3b0",
    CATEGORY_RECOVERY: "#4a6b78",
}

# Training-block focus presets (bias the block toward a goal type).
PLAN_FOCUSES = ("strength", "cardio", "hybrid")
PLAN_FOCUS_LABELS = {
    "strength": "Strength",
    "cardio": "Cardio / Engine",
    "hybrid": "Hybrid",
}


@dataclass(frozen=True)
class SessionDefinition:
    key: str
    title: str
    color: str
    intensity: str
    duration_min: int
    recovery_cost: int
    goal: str
    category: str = CATEGORY_CARDIO


# The draggable session palette. Colour-coded by training stimulus:
# green=endurance base, cyan/violet/blue=strength, orange/yellow=high output,
# coral=long aerobic stress, grey=recovery/rest.
SESSION_LIBRARY: tuple[SessionDefinition, ...] = (
    SessionDefinition("ZONE 2 CARDIO", "Zone 2 Cardio", "#3ad6a0", "LOW", 45, 2,
                      "Aerobic base without fatigue spillover", CATEGORY_CARDIO),
    SessionDefinition("UPPER STRENGTH", "Upper Strength", "#2ee6ff", "MOD", 55, 3,
                      "Press, pull and trunk control", CATEGORY_STRENGTH),
    SessionDefinition("LOWER STRENGTH", "Lower Strength", "#a06bff", "HIGH", 60, 4,
                      "Leg strength with controlled eccentric load", CATEGORY_STRENGTH),
    SessionDefinition("ENGINE RUN", "Engine Run", "#ff9d3d", "MOD+", 40, 3,
                      "Steady threshold-adjacent conditioning", CATEGORY_CARDIO),
    SessionDefinition("LONG RUN", "Long Run", "#ff6b8a", "HIGH", 85, 5,
                      "Durable aerobic volume and glycogen management", CATEGORY_CARDIO),
    SessionDefinition("INTERVALS", "Intervals", "#ffd166", "MAX", 35, 5,
                      "Speed, power and high-end oxygen uptake", CATEGORY_CARDIO),
    SessionDefinition("FULL BODY", "Full Body", "#6c8cff", "MOD", 50, 3,
                      "Balanced strength stimulus across major patterns", CATEGORY_STRENGTH),
    SessionDefinition("MOBILITY", "Mobility", "#7fa3b0", "LOW", 25, 1,
                      "Range, tissue quality and movement prep", CATEGORY_MOBILITY),
    SessionDefinition("REST", "Rest", "#4a6b78", "OFF", 0, 0,
                      "Protect adaptation; no training load planned", CATEGORY_RECOVERY),
)
SESSION_DEFS = {d.key: d for d in SESSION_LIBRARY}
SESSION_TYPES: list[tuple[str, str]] = [(d.key, d.color) for d in SESSION_LIBRARY]
SESSION_COLOR = dict(SESSION_TYPES)

# Custom, user-created cards. Cached per process so SessionItem.definition can
# resolve them without a DB round-trip. Refreshed by ``custom_cards``.
_CUSTOM_DEFS: dict[str, SessionDefinition] = {}


def _template_def(row: FitnessCardTemplate) -> SessionDefinition:
    return SessionDefinition(
        key=row.key,
        title=row.title,
        color=row.color,
        intensity=row.intensity,
        duration_min=row.duration_min,
        recovery_cost=row.recovery_cost,
        goal=row.goal,
        category=(row.category or CATEGORY_CARDIO),
    )


def custom_cards(user_id: int) -> list[SessionDefinition]:
    """User-created palette cards, newest sort_order last. Refreshes the cache."""
    with session_scope() as s:
        rows = s.scalars(
            select(FitnessCardTemplate)
            .where(FitnessCardTemplate.user_id == user_id)
            .order_by(FitnessCardTemplate.sort_order, FitnessCardTemplate.id)
        ).all()
        defs = [_template_def(r) for r in rows]
    for d in defs:
        _CUSTOM_DEFS[d.key] = d
    return defs


def palette_cards(user_id: int) -> list[SessionDefinition]:
    """Built-in library plus the user's custom cards, in palette order."""
    return [*SESSION_LIBRARY, *custom_cards(user_id)]


def resolve_def(session_type: str, color: str = "#2ee6ff") -> SessionDefinition:
    """Resolve a session type to a definition (built-in or custom)."""
    if session_type in SESSION_DEFS:
        return SESSION_DEFS[session_type]
    if session_type in _CUSTOM_DEFS:
        return _CUSTOM_DEFS[session_type]
    return SessionDefinition(
        session_type, session_type.title(), color, "MOD", 45, 3,
        "Planned training stimulus",
    )


def create_custom_card(
    user_id: int,
    *,
    title: str,
    color: str = "#2ee6ff",
    category: str = CATEGORY_CARDIO,
    intensity: str = "MOD",
    duration_min: int = 45,
    recovery_cost: int = 3,
    goal: str = "",
) -> str:
    """Persist a new custom palette card and return its stable key."""
    import uuid

    key = f"CUSTOM-{uuid.uuid4().hex[:6].upper()}"
    with session_scope() as s:
        count = (
            s.query(FitnessCardTemplate)
            .filter(FitnessCardTemplate.user_id == user_id)
            .count()
        )
        s.add(
            FitnessCardTemplate(
                user_id=user_id,
                key=key,
                title=(title.strip() or "Custom Session")[:60],
                color=color,
                category=category if category in CATEGORIES else CATEGORY_CARDIO,
                intensity=(intensity.strip() or "MOD")[:8],
                duration_min=max(0, int(duration_min)),
                recovery_cost=max(0, min(5, int(recovery_cost))),
                goal=goal.strip(),
                sort_order=count,
            )
        )
    custom_cards(user_id)  # refresh cache
    return key


def update_custom_card(
    user_id: int,
    key: str,
    *,
    title: str | None = None,
    color: str | None = None,
    category: str | None = None,
    intensity: str | None = None,
    duration_min: int | None = None,
    recovery_cost: int | None = None,
    goal: str | None = None,
) -> None:
    """Edit an existing custom card. Placed sessions reflect changes live."""
    with session_scope() as s:
        row = s.scalars(
            select(FitnessCardTemplate).where(
                FitnessCardTemplate.user_id == user_id,
                FitnessCardTemplate.key == key,
            )
        ).first()
        if row is None:
            return
        if title is not None:
            row.title = (title.strip() or row.title)[:60]
        if color is not None:
            row.color = color
        if category is not None and category in CATEGORIES:
            row.category = category
        if intensity is not None:
            row.intensity = (intensity.strip() or row.intensity)[:8]
        if duration_min is not None:
            row.duration_min = max(0, int(duration_min))
        if recovery_cost is not None:
            row.recovery_cost = max(0, min(5, int(recovery_cost)))
        if goal is not None:
            row.goal = goal.strip()
        new_color = row.color
        # Keep already-placed sessions of this type colour-synced.
        placed = s.scalars(
            select(FitnessSession).where(
                FitnessSession.user_id == user_id,
                FitnessSession.session_type == key,
            )
        ).all()
        for p in placed:
            p.color = new_color
    custom_cards(user_id)  # refresh cache


def delete_custom_card(user_id: int, key: str) -> None:
    """Remove a custom card from the palette. Placed sessions are kept.

    Placed sessions that have no explicit label inherit the card's title so they
    keep a readable name once the template is gone.
    """
    with session_scope() as s:
        row = s.scalars(
            select(FitnessCardTemplate).where(
                FitnessCardTemplate.user_id == user_id,
                FitnessCardTemplate.key == key,
            )
        ).first()
        if row is None:
            return
        title = row.title
        placed = s.scalars(
            select(FitnessSession).where(
                FitnessSession.user_id == user_id,
                FitnessSession.session_type == key,
            )
        ).all()
        for p in placed:
            if not (p.label or "").strip():
                p.label = title[:60]
        s.delete(row)
    _CUSTOM_DEFS.pop(key, None)


@dataclass
class PlanInfo:
    id: int
    block_name: str
    start_date: date
    weeks: int
    purpose: str = ""
    focus: str = "hybrid"
    goal: str = ""

    @property
    def current_week(self) -> int:
        delta_days = (date.today() - self.start_date).days
        if delta_days < 0:
            return 0
        return min(self.weeks, delta_days // 7 + 1)

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(weeks=self.weeks) - timedelta(days=1)

    @property
    def days_remaining(self) -> int:
        return max(0, (self.end_date - date.today()).days)

    @property
    def progress(self) -> float:
        """Fraction of the block elapsed, 0.0–1.0."""
        total = max(1, self.weeks * 7)
        elapsed = (date.today() - self.start_date).days
        return max(0.0, min(1.0, elapsed / total))

    @property
    def focus_label(self) -> str:
        return PLAN_FOCUS_LABELS.get(self.focus, "Hybrid")

    @property
    def timeline_label(self) -> str:
        return (f"{self.start_date.strftime('%d %b').upper()} → "
                f"{self.end_date.strftime('%d %b %Y').upper()}")

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
    label: str = ""
    notes: str = ""
    completed: bool = False

    @property
    def definition(self) -> SessionDefinition:
        return resolve_def(self.session_type, self.color)

    @property
    def title(self) -> str:
        return self.label.strip() or self.definition.title

    @property
    def category(self) -> str:
        return self.definition.category

    @property
    def duration_label(self) -> str:
        minutes = self.definition.duration_min
        return "Rest day" if minutes <= 0 else f"{minutes} min"

    @property
    def recovery_label(self) -> str:
        cost = self.definition.recovery_cost
        return "R0" if cost <= 0 else f"R{cost}"


@dataclass
class FitnessSnapshot:
    plan: PlanInfo
    sessions_by_day: dict[date, list[SessionItem]] = field(default_factory=dict)


@dataclass(frozen=True)
class BodyMetric:
    key: str
    label: str
    value: float | None
    unit: str
    baseline_7d: float | None
    delta_7d: float | None
    series: list[float] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class BodyStateSnapshot:
    resting_hr: BodyMetric
    weight: BodyMetric

    @property
    def has_data(self) -> bool:
        return self.resting_hr.has_data or self.weight.has_data

    @property
    def readiness_label(self) -> str:
        if not self.has_data:
            return "SYNC NEEDED"
        rhr = self.resting_hr
        if rhr.value is not None and rhr.baseline_7d is not None:
            if rhr.value >= rhr.baseline_7d + 4:
                return "RECOVERY WATCH"
            if rhr.value <= rhr.baseline_7d - 2:
                return "PRIMED"
        return "STEADY"


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def _plan_info(plan: FitnessPlan) -> PlanInfo:
    return PlanInfo(
        plan.id, plan.block_name, plan.start_date, plan.weeks,
        purpose=plan.purpose or "", focus=plan.focus or "hybrid",
        goal=plan.goal or "",
    )


def get_or_create_plan(user_id: int) -> PlanInfo:
    with session_scope() as s:
        plan = s.scalars(
            select(FitnessPlan).where(
                FitnessPlan.user_id == user_id, FitnessPlan.is_active.is_(True)
            )
        ).first()
        if plan is None:
            # Sensible default: a 6-week base block starting this Monday.
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            plan = FitnessPlan(
                user_id=user_id, block_name="Base Build — Block 1",
                purpose="Build aerobic base", focus="hybrid",
                goal="Consistent weekly volume without flare-ups",
                start_date=monday, weeks=6, is_active=True,
            )
            s.add(plan)
            s.flush()
        return _plan_info(plan)


def list_plans(user_id: int) -> list[PlanInfo]:
    """All training blocks for a user, active first then most recent."""
    with session_scope() as s:
        rows = s.scalars(
            select(FitnessPlan)
            .where(FitnessPlan.user_id == user_id)
            .order_by(FitnessPlan.is_active.desc(), FitnessPlan.start_date.desc())
        ).all()
        return [_plan_info(p) for p in rows]


def create_plan(
    user_id: int,
    *,
    block_name: str,
    purpose: str = "",
    focus: str = "hybrid",
    goal: str = "",
    start_date: date | None = None,
    weeks: int = 6,
    activate: bool = True,
) -> int:
    """Create a new training block. If ``activate``, it becomes the active plan."""
    start = start_date or (date.today() - timedelta(days=date.today().weekday()))
    with session_scope() as s:
        if activate:
            for other in s.scalars(
                select(FitnessPlan).where(
                    FitnessPlan.user_id == user_id, FitnessPlan.is_active.is_(True)
                )
            ).all():
                other.is_active = False
        plan = FitnessPlan(
            user_id=user_id,
            block_name=(block_name.strip() or "Training Block")[:120],
            purpose=purpose.strip()[:120],
            focus=focus if focus in PLAN_FOCUSES else "hybrid",
            goal=goal.strip(),
            start_date=start,
            weeks=max(1, min(52, int(weeks))),
            is_active=activate,
        )
        s.add(plan)
        s.flush()
        return plan.id


def activate_plan(user_id: int, plan_id: int) -> None:
    """Make ``plan_id`` the single active block for this user."""
    with session_scope() as s:
        for p in s.scalars(
            select(FitnessPlan).where(FitnessPlan.user_id == user_id)
        ).all():
            p.is_active = (p.id == plan_id)


def delete_plan(user_id: int, plan_id: int) -> None:
    """Delete a plan. If it was active, the next most recent becomes active."""
    with session_scope() as s:
        plan = s.get(FitnessPlan, plan_id)
        if plan is None or plan.user_id != user_id:
            return
        was_active = plan.is_active
        s.delete(plan)
        s.flush()
        if was_active:
            nxt = s.scalars(
                select(FitnessPlan)
                .where(FitnessPlan.user_id == user_id)
                .order_by(FitnessPlan.start_date.desc())
            ).first()
            if nxt is not None:
                nxt.is_active = True


def update_plan(plan_id: int, *, block_name: str | None = None,
                purpose: str | None = None, focus: str | None = None,
                goal: str | None = None, start_date: date | None = None,
                weeks: int | None = None) -> None:
    with session_scope() as s:
        plan = s.get(FitnessPlan, plan_id)
        if plan is None:
            return
        if block_name is not None:
            plan.block_name = block_name.strip() or plan.block_name
        if purpose is not None:
            plan.purpose = purpose.strip()[:120]
        if focus is not None and focus in PLAN_FOCUSES:
            plan.focus = focus
        if goal is not None:
            plan.goal = goal.strip()
        if start_date is not None:
            plan.start_date = start_date
        if weeks is not None:
            plan.weeks = max(1, min(52, weeks))


# --------------------------------------------------------------------------- #
# Sessions (the drag-and-drop calendar contents)
# --------------------------------------------------------------------------- #
def sessions_for_range(user_id: int, start: date, end: date) -> dict[date, list[SessionItem]]:
    out: dict[date, list[SessionItem]] = {}
    with session_scope() as s:
        rows = s.scalars(
            select(FitnessSession)
            .where(
                FitnessSession.user_id == user_id,
                FitnessSession.day >= start,
                FitnessSession.day <= end,
            )
            .order_by(FitnessSession.day, FitnessSession.sort_order)
        ).all()
        for r in rows:
            out.setdefault(r.day, []).append(_session_item(r))
    return out


def _session_item(row: FitnessSession) -> SessionItem:
    return SessionItem(
        row.id,
        row.day,
        row.session_type,
        row.color,
        row.label,
        row.notes,
        bool(row.completed),
    )


def sessions_for_month(user_id: int, year: int, month: int) -> dict[date, list[SessionItem]]:
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return sessions_for_range(user_id, first, last)


def sessions_for_day(user_id: int, day: date) -> list[SessionItem]:
    return sessions_for_range(user_id, day, day).get(day, [])


def get_session(session_id: int) -> SessionItem | None:
    with session_scope() as s:
        row = s.get(FitnessSession, session_id)
        return _session_item(row) if row is not None else None


def add_session(user_id: int, day: date, session_type: str) -> int:
    if session_type in SESSION_COLOR:
        color = SESSION_COLOR[session_type]
    else:
        color = resolve_def(session_type).color
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


def update_session(
    session_id: int,
    *,
    session_type: str | None = None,
    label: str | None = None,
    notes: str | None = None,
    completed: bool | None = None,
) -> None:
    with session_scope() as s:
        row = s.get(FitnessSession, session_id)
        if row is None:
            return
        if session_type is not None:
            row.session_type = session_type
            if session_type in SESSION_COLOR:
                row.color = SESSION_COLOR[session_type]
            else:
                row.color = resolve_def(session_type).color
        if label is not None:
            row.label = label.strip()[:60]
        if notes is not None:
            row.notes = notes
        if completed is not None:
            row.completed = completed


def mark_complete(session_id: int, complete: bool = True) -> None:
    update_session(session_id, completed=complete)


def swap_session(session_id: int) -> str | None:
    """Cycle a session to the next palette item and return the new type."""
    with session_scope() as s:
        row = s.get(FitnessSession, session_id)
        if row is None:
            return None
        keys = [d.key for d in SESSION_LIBRARY]
        try:
            idx = keys.index(row.session_type)
        except ValueError:
            idx = -1
        new_type = keys[(idx + 1) % len(keys)]
        row.session_type = new_type
        row.color = SESSION_COLOR[new_type]
        return new_type


# --------------------------------------------------------------------------- #
# Inferred metrics (Apple Health)
# --------------------------------------------------------------------------- #
def fitness_frame(user_id: int, days: int = 30) -> pd.DataFrame:
    """Per-day training/body signals from Apple Health.

    Empty / None where Apple Health has no data — never fabricated.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.resting_hr,
                   HealthMetricDaily.weight_kg, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
        ).all()
    records = []
    for day, rhr, weight_kg, extra in rows:
        extra = extra or {}
        records.append({
            "day": day,
            "distance_km": extra.get("distance_km"),
            "vo2max": extra.get("vo2max"),
            "resting_hr": rhr,
            "weight_kg": weight_kg,
        })
    return pd.DataFrame(
        records, columns=["day", "distance_km", "vo2max", "resting_hr", "weight_kg"]
    ).sort_values("day")


def body_state_snapshot(user_id: int, days: int = 30) -> BodyStateSnapshot:
    frame = fitness_frame(user_id, days=days)
    return BodyStateSnapshot(
        resting_hr=_body_metric(frame, "resting_hr", "Resting HR", "bpm"),
        weight=_body_metric(frame, "weight_kg", "Weight", "kg"),
    )


def _body_metric(frame: pd.DataFrame, column: str, label: str, unit: str) -> BodyMetric:
    if frame.empty or column not in frame:
        return BodyMetric(column, label, None, unit, None, None, [])
    values = frame[column].dropna().astype(float)
    if values.empty:
        return BodyMetric(column, label, None, unit, None, None, [])
    recent = values.tail(7)
    baseline = float(recent.mean()) if not recent.empty else None
    latest = float(values.iloc[-1])
    delta = latest - baseline if baseline is not None else None
    return BodyMetric(
        key=column,
        label=label,
        value=latest,
        unit=unit,
        baseline_7d=baseline,
        delta_7d=delta,
        series=values.tolist(),
    )


def get_snapshot(user_id: int, year: int, month: int) -> FitnessSnapshot:
    return FitnessSnapshot(
        plan=get_or_create_plan(user_id),
        sessions_by_day=sessions_for_month(user_id, year, month),
    )


# --------------------------------------------------------------------------- #
# Strength / cardio breakdown
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CategoryStat:
    category: str
    label: str
    color: str
    sessions: int
    minutes: int
    load: int  # sum of recovery_cost across sessions (a coarse training-load index)
    completed: int

    @property
    def share(self) -> float:
        return 0.0  # set by TrainingBreakdown.shares()


@dataclass(frozen=True)
class TrainingBreakdown:
    start: date
    end: date
    stats: tuple[CategoryStat, ...]

    @property
    def total_sessions(self) -> int:
        return sum(s.sessions for s in self.stats)

    @property
    def total_minutes(self) -> int:
        return sum(s.minutes for s in self.stats)

    @property
    def total_load(self) -> int:
        return sum(s.load for s in self.stats)

    @property
    def completed(self) -> int:
        return sum(s.completed for s in self.stats)

    def minute_share(self, category: str) -> float:
        if self.total_minutes <= 0:
            return 0.0
        for s in self.stats:
            if s.category == category:
                return s.minutes / self.total_minutes
        return 0.0

    @property
    def strength_cardio_ratio(self) -> tuple[float, float]:
        """(strength, cardio) share of *training* minutes, ignoring rest."""
        strength = sum(s.minutes for s in self.stats if s.category == CATEGORY_STRENGTH)
        cardio = sum(s.minutes for s in self.stats if s.category == CATEGORY_CARDIO)
        total = strength + cardio
        if total <= 0:
            return 0.0, 0.0
        return strength / total, cardio / total


def training_breakdown(user_id: int, start: date, end: date) -> TrainingBreakdown:
    """Aggregate planned sessions in a window by training category."""
    sessions = sessions_for_range(user_id, start, end)
    buckets: dict[str, dict[str, int]] = {
        c: {"sessions": 0, "minutes": 0, "load": 0, "completed": 0} for c in CATEGORIES
    }
    for items in sessions.values():
        for item in items:
            cat = item.category if item.category in buckets else CATEGORY_CARDIO
            b = buckets[cat]
            b["sessions"] += 1
            b["minutes"] += max(0, item.definition.duration_min)
            b["load"] += max(0, item.definition.recovery_cost)
            if item.completed:
                b["completed"] += 1
    stats = tuple(
        CategoryStat(
            category=c,
            label=CATEGORY_LABELS[c],
            color=CATEGORY_COLORS[c],
            sessions=buckets[c]["sessions"],
            minutes=buckets[c]["minutes"],
            load=buckets[c]["load"],
            completed=buckets[c]["completed"],
        )
        for c in CATEGORIES
    )
    return TrainingBreakdown(start=start, end=end, stats=stats)
