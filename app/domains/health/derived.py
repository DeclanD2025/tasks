"""Derived health metrics: personal sleep need, sleep debt, and TRIMP strain.

Deterministic arithmetic over data already in the local database — no
external calls, no models. Everything here states its own confidence: sleep
need refuses to exist until enough nights are recorded, and strain says it is
estimated from workout heart rate, not measured load.

Sleep need   — trimmed mean of recent plausible nights (Bevel-style personal
               baseline instead of a generic 8h rule).
Sleep debt   — net shortfall vs personal need over the last 14 recorded
               nights, with a week-over-week trend.
TRIMP strain — Edwards-style training impulse per workout: duration in the
               heart-rate zone implied by average HR, summed per day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import func, select

from app.db.database import session_scope
from app.db.models import HealthMetricDaily, Workout

# Sleep-need calibration: how many plausible nights before a baseline exists,
# and the plausibility window (excludes nap fragments / tracker glitches).
CALIBRATION_NIGHTS = 14
MIN_PLAUSIBLE_SLEEP_MIN = 180
MAX_PLAUSIBLE_SLEEP_MIN = 720
NEED_FLOOR_MIN, NEED_CEIL_MIN = 390, 560  # 6.5h .. 9h20

DEBT_WINDOW_NIGHTS = 14

# Edwards TRIMP zone weights by fraction of estimated max heart rate.
_ZONE_BOUNDS = ((0.6, 1.0), (0.7, 2.0), (0.8, 3.0), (0.9, 4.0), (1.01, 5.0))
DEFAULT_HR_MAX = 190.0


@dataclass(frozen=True)
class SleepDebt:
    calibrating: bool
    nights_recorded: int  # plausible nights available for the baseline
    need_minutes: float | None  # personal nightly need, None while calibrating
    debt_minutes: float | None  # net shortfall over the debt window (>= 0)
    trend_minutes: float | None  # debt now minus debt a week ago (+ = growing)

    @property
    def label(self) -> str:
        if self.calibrating:
            return f"calibrating {self.nights_recorded}/{CALIBRATION_NIGHTS}"
        total = int(round(self.debt_minutes or 0))
        if total <= 15:
            return "clear"
        return f"−{total // 60}h {total % 60:02d}"


@dataclass(frozen=True)
class StrainDay:
    day: date
    trimp: float

    @property
    def band(self) -> str:
        if self.trimp <= 0:
            return "rest"
        if self.trimp < 60:
            return "light"
        if self.trimp < 120:
            return "moderate"
        if self.trimp < 200:
            return "hard"
        return "severe"


def _sleep_rows(user_id: int, days: int) -> list[tuple[date, int]]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.sleep_minutes)
            .where(HealthMetricDaily.user_id == user_id)
            .where(HealthMetricDaily.day >= since)
            .where(HealthMetricDaily.sleep_minutes.is_not(None))
            .order_by(HealthMetricDaily.day)
        ).all()
    return [
        (day, minutes)
        for day, minutes in rows
        if MIN_PLAUSIBLE_SLEEP_MIN <= minutes <= MAX_PLAUSIBLE_SLEEP_MIN
    ]


def sleep_need_minutes(user_id: int, days: int = 60) -> tuple[float | None, int]:
    """Personal nightly sleep need: trimmed mean of recent plausible nights.

    Returns ``(need, nights)``; need is None until CALIBRATION_NIGHTS exist.
    """
    values = sorted(minutes for _, minutes in _sleep_rows(user_id, days))
    nights = len(values)
    if nights < CALIBRATION_NIGHTS:
        return None, nights
    trim = max(1, nights // 5)  # drop the shortest/longest 20%
    core = values[trim : nights - trim] or values
    need = max(NEED_FLOOR_MIN, min(NEED_CEIL_MIN, mean(core)))
    return need, nights


def _window_debt(rows: list[tuple[date, int]], need: float, end: date) -> float | None:
    window = [minutes for day, minutes in rows if day <= end][-DEBT_WINDOW_NIGHTS:]
    if not window:
        return None
    return max(0.0, sum(need - minutes for minutes in window))


def get_sleep_debt(user_id: int) -> SleepDebt:
    need, nights = sleep_need_minutes(user_id)
    if need is None:
        return SleepDebt(True, nights, None, None, None)
    rows = _sleep_rows(user_id, days=45)
    today = date.today()
    debt_now = _window_debt(rows, need, today)
    debt_prev = _window_debt(rows, need, today - timedelta(days=7))
    trend = None if debt_now is None or debt_prev is None else debt_now - debt_prev
    return SleepDebt(False, nights, need, debt_now, trend)


def estimate_hr_max(user_id: int) -> float:
    """Highest heart rate seen in any workout, clamped to a plausible band."""
    with session_scope() as s:
        observed = s.scalar(
            select(func.max(Workout.max_heart_rate)).where(Workout.user_id == user_id)
        )
    if not observed:
        return DEFAULT_HR_MAX
    return max(170.0, min(205.0, float(observed)))


def _zone_weight(avg_hr: float, hr_max: float) -> float:
    fraction = avg_hr / hr_max if hr_max else 0.0
    for bound, weight in _ZONE_BOUNDS:
        if fraction < bound:
            return weight if fraction >= 0.5 else 0.5  # below-zone movement counts a little
    return 5.0


def get_strain_days(user_id: int, days: int = 35) -> list[StrainDay]:
    """Daily TRIMP totals for the window, including zero (rest) days."""
    since = date.today() - timedelta(days=days)
    hr_max = estimate_hr_max(user_id)
    with session_scope() as s:
        rows = s.execute(
            select(Workout.started_at, Workout.duration_seconds, Workout.average_heart_rate)
            .where(Workout.user_id == user_id)
            .where(Workout.started_at >= since)
        ).all()
    totals: dict[date, float] = {}
    for started_at, duration_seconds, avg_hr in rows:
        if not duration_seconds or not avg_hr:
            continue
        minutes = duration_seconds / 60.0
        totals[started_at.date()] = totals.get(started_at.date(), 0.0) + (
            minutes * _zone_weight(float(avg_hr), hr_max)
        )
    out: list[StrainDay] = []
    cursor = since
    while cursor <= date.today():
        out.append(StrainDay(cursor, round(totals.get(cursor, 0.0), 1)))
        cursor += timedelta(days=1)
    return out
