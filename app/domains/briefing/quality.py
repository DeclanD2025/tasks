"""Data quality and provenance for the homepage.

Built around the audit's most important finding: **`DataSource.status` cannot
be trusted.** In production it flags both calendar connectors `mock` while they
hold 81 real events with genuine EventKit identifiers, and it reports
`tasks_sync` as `connected` with a last-sync 22 days old.

So freshness is derived from **the newest actual record in each domain**, never
from a connector's self-report. A source is fresh if it recently produced data,
which is the only definition that cannot be wrong.

The output feeds two different needs and keeps them apart:

- ``trust`` — can a claim be made from this at all?
- ``note``  — what the operator should be told, in words, when it cannot.

A section with stale data says so. It does not render a confident number with a
small grey timestamp beside it and hope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.db.database import session_scope
from app.db.models import (
    CalendarEvent,
    HealthMetricDaily,
    StrengthWorkout,
    Task,
    Workout,
)

#: How old a domain's newest record may be before its claims are qualified.
FRESHNESS_LIMITS = {
    "health": 2,
    "tasks": 3,
    "calendar": 14,   # a calendar with nothing new for a fortnight is plausible
    "training": 10,
}


@dataclass
class SourceQuality:
    domain: str
    label: str
    latest_record: date | None
    age_days: int | None
    count: int
    #: live | stale | empty
    trust: str
    #: A complete sentence, for when this source is described on its own.
    note: str
    #: The same thing as a fragment, for when several are listed together.
    #: Two full sentences side by side repeated their shared consequence
    #: clause — "…so anything below may have moved on" twice, on one line.
    fact: str = ""

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "label": self.label,
            "latestRecord": self.latest_record.isoformat() if self.latest_record else None,
            "ageDays": self.age_days,
            "count": self.count,
            "trust": self.trust,
            "note": self.note,
            "fact": self.fact,
        }

    @property
    def usable(self) -> bool:
        return self.trust == "live"


def _judge(domain: str, label: str, latest: date | None, count: int) -> SourceQuality:
    if latest is None or count == 0:
        return SourceQuality(
            domain, label, None, None, count, "empty",
            f"No {label.lower()} data yet.",
            f"no {label.lower()} data",
        )
    age = (date.today() - latest).days
    limit = FRESHNESS_LIMITS.get(domain, 7)
    if age > limit:
        when = latest.strftime("%-d %b")
        return SourceQuality(
            domain, label, latest, age, count, "stale",
            f"{label} last updated {age} days ago ({when}), "
            "so anything below may have moved on.",
            f"{label.lower()} {age}d old ({when})",
        )
    return SourceQuality(domain, label, latest, age, count, "live", "")


def assess(uid: int) -> dict[str, SourceQuality]:
    """Freshness per domain, from records rather than connector claims.

    One query per domain, all aggregates — no row loading, no N+1.
    """
    with session_scope() as s:
        health_latest = s.scalar(
            select(func.max(HealthMetricDaily.day)).where(HealthMetricDaily.user_id == uid)
        )
        health_count = s.scalar(
            select(func.count()).select_from(HealthMetricDaily)
            .where(HealthMetricDaily.user_id == uid)
        ) or 0

        # Tasks have no updated_at, so the freshest thing they can prove is the
        # most recent sync stamp on a row. Still a record, not a self-report.
        task_synced = s.scalar(
            select(func.max(Task.synced_at)).where(Task.user_id == uid)
        )
        task_count = s.scalar(
            select(func.count()).select_from(Task)
            .where(Task.user_id == uid, Task.pending_delete == 0, Task.status != "done")
        ) or 0

        event_latest = s.scalar(
            select(func.max(CalendarEvent.synced_at)).where(CalendarEvent.user_id == uid)
        )
        event_count = s.scalar(
            select(func.count()).select_from(CalendarEvent)
            .where(CalendarEvent.user_id == uid)
        ) or 0

        workout_latest = s.scalar(
            select(func.max(Workout.started_at)).where(Workout.user_id == uid)
        )
        strength_latest = s.scalar(
            select(func.max(StrengthWorkout.started_at)).where(StrengthWorkout.user_id == uid)
        )
        workout_count = s.scalar(
            select(func.count()).select_from(Workout).where(Workout.user_id == uid)
        ) or 0

    def as_day(value) -> date | None:
        if value is None:
            return None
        return value.date() if isinstance(value, datetime) else value

    training_latest = max(
        [d for d in (as_day(workout_latest), as_day(strength_latest)) if d],
        default=None,
    )

    return {
        "health": _judge("health", "Health data", as_day(health_latest), health_count),
        "tasks": _judge("tasks", "Tasks", as_day(task_synced), task_count),
        "calendar": _judge("calendar", "Calendar", as_day(event_latest), event_count),
        "training": _judge("training", "Training", training_latest, workout_count),
    }


def warnings_from(quality: dict[str, SourceQuality]) -> list[dict]:
    """Only the problems, phrased for a person.

    Deliberately not a status list. The homepage shows this when something is
    actually wrong and shows nothing at all when everything is current — a
    permanent row of green ticks is plumbing, and plumbing does not belong on
    the first screen.
    """
    out = []
    for source in quality.values():
        if source.trust == "live":
            continue
        out.append({
            "domain": source.domain,
            "severity": "warning" if source.trust == "stale" else "info",
            "message": source.note,
            "fact": source.fact,
        })
    return out


def source_timestamp(quality: dict[str, SourceQuality]) -> datetime | None:
    """The newest record across all domains — what a brief is actually current to."""
    days = [q.latest_record for q in quality.values() if q.latest_record]
    if not days:
        return None
    return datetime.combine(max(days), datetime.min.time())
