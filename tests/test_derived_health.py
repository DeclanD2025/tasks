"""Derived health metrics: sleep need/debt calibration and TRIMP strain."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.db.database import session_scope
from app.db.models import HealthMetricDaily, User, Workout
from app.domains.health import derived


@pytest.fixture()
def fresh_user() -> int:
    with session_scope() as s:
        user = User(email=f"derived-{datetime.now().timestamp()}@test.local")
        s.add(user)
        s.flush()
        return user.id


def _add_sleep(user_id: int, nights: int, minutes: int, offset: int = 0) -> None:
    with session_scope() as s:
        for i in range(nights):
            s.add(
                HealthMetricDaily(
                    user_id=user_id,
                    day=date.today() - timedelta(days=offset + i),
                    sleep_minutes=minutes,
                )
            )


def test_sleep_need_calibrates_then_resolves(fresh_user: int):
    _add_sleep(fresh_user, nights=5, minutes=440)
    need, nights = derived.sleep_need_minutes(fresh_user)
    assert need is None and nights == 5
    debt = derived.get_sleep_debt(fresh_user)
    assert debt.calibrating and "5/14" in debt.label

    _add_sleep(fresh_user, nights=15, minutes=450, offset=5)
    need, nights = derived.sleep_need_minutes(fresh_user)
    assert need is not None
    assert 390 <= need <= 560


def test_sleep_debt_accumulates_shortfall(fresh_user: int):
    # 20 nights at 8h to set the need, then the last 5 nights at 6h.
    _add_sleep(fresh_user, nights=20, minutes=480, offset=5)
    _add_sleep(fresh_user, nights=5, minutes=360)
    debt = derived.get_sleep_debt(fresh_user)
    assert not debt.calibrating
    assert debt.debt_minutes is not None and debt.debt_minutes > 0
    assert debt.label.startswith("−")
    # Debt should have grown vs a week ago (short nights are recent).
    assert debt.trend_minutes is not None and debt.trend_minutes > 0


def test_sleep_debt_clear_when_meeting_need(fresh_user: int):
    _add_sleep(fresh_user, nights=25, minutes=470)
    debt = derived.get_sleep_debt(fresh_user)
    assert not debt.calibrating
    assert debt.label == "clear"


def test_implausible_nights_excluded(fresh_user: int):
    _add_sleep(fresh_user, nights=16, minutes=460)
    with session_scope() as s:  # a 38-minute tracker glitch must not skew need
        s.add(HealthMetricDaily(user_id=fresh_user, day=date.today() - timedelta(days=20), sleep_minutes=38))
    need, nights = derived.sleep_need_minutes(fresh_user)
    assert nights == 16  # glitch not counted
    assert need is not None and need > 400


def _add_workout(user_id: int, day_offset: int, minutes: int, avg_hr: float, max_hr: float = 185) -> None:
    with session_scope() as s:
        started = datetime.combine(date.today() - timedelta(days=day_offset), datetime.min.time())
        s.add(
            Workout(
                user_id=user_id,
                source="test",
                source_id=f"w-{day_offset}-{avg_hr}",
                sport_type="run",
                started_at=started,
                duration_seconds=minutes * 60,
                average_heart_rate=avg_hr,
                max_heart_rate=max_hr,
            )
        )


def test_trimp_strain_scales_with_intensity(fresh_user: int):
    _add_workout(fresh_user, day_offset=1, minutes=40, avg_hr=110)  # easy
    _add_workout(fresh_user, day_offset=0, minutes=40, avg_hr=165)  # hard
    days = derived.get_strain_days(fresh_user, days=5)
    by_day = {d.day: d for d in days}
    easy = by_day[date.today() - timedelta(days=1)]
    hard = by_day[date.today()]
    assert hard.trimp > easy.trimp * 1.5
    assert easy.band in {"light", "moderate"}
    assert hard.band in {"hard", "severe"}
    # A day with no workouts is an explicit rest day, not missing data.
    assert by_day[date.today() - timedelta(days=3)].band == "rest"


def test_hr_max_estimated_from_workouts(fresh_user: int):
    assert derived.estimate_hr_max(fresh_user) == derived.DEFAULT_HR_MAX
    _add_workout(fresh_user, day_offset=2, minutes=30, avg_hr=150, max_hr=192)
    assert derived.estimate_hr_max(fresh_user) == 192.0
