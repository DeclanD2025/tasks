"""The daily brief: state, focus, next action.

The prose here is **assembled from structured facts by deterministic rules**.
No model writes it. Every clause traces to a value carried in ``evidence``, so
"why does it say that?" is always answerable by opening the brief rather than
by trusting it.

Two disciplines make that hold:

**Nothing is claimed that the data cannot support.** If health data is stale,
the summary does not mention recovery. If tasks are 22 days old, counts carry
that caveat. The honest sentence is shorter, and short is what the first screen
needs anyway.

**The brief is persisted, not recomputed.** A stored record of what ORION
suggested — and what the operator did about it — is the only way the question
"is any of this useful?" stays open. Regenerating on every load would make the
system permanently unaccountable for its own advice.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import BriefEvent, CalendarEvent, DailyBrief, Task, utcnow
from app.domains import personal_os
from app.domains.briefing import priorities as prio
from app.domains.briefing import quality as dq
from app.domains.briefing import review as review_mod
from app.services import get_tasks

log = get_logger(__name__)

RULE_VERSION = prio.RULE_VERSION


# --------------------------------------------------------------------------- #
# Daypart
# --------------------------------------------------------------------------- #
def daypart_for(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


_DAYPART_FRAMING = {
    "morning": "The day is ahead of you.",
    "afternoon": "There is still a working stretch left.",
    "evening": "This is the last usable stretch of the day.",
    "night": "It is late — this is a wind-down, not a work session.",
}

#: Rough usable minutes left in each daypart, for fitting tasks to time.
#: Deliberately conservative: over-promising available time is how a plan
#: becomes a reproach.
_DAYPART_MINUTES = {"morning": 240, "afternoon": 200, "evening": 120, "night": 30}


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #
def _latest_health(uid: int) -> dict:
    """Sleep and bodyweight from the newest health row.

    Read directly rather than off ``RecoverySnapshot``, which carries a score
    and a label but no sleep figure — a `getattr` against it silently returned
    None and produced a summary with a hole in it.
    """
    from app.db.models import HealthMetricDaily

    with session_scope() as s:
        row = s.scalars(
            select(HealthMetricDaily)
            .where(HealthMetricDaily.user_id == uid)
            .order_by(HealthMetricDaily.day.desc())
            .limit(1)
        ).first()
        if row is None:
            return {}
        return {
            "day": row.day,
            "sleepHours": round(row.sleep_minutes / 60.0, 1) if row.sleep_minutes else None,
            "restingHr": row.resting_hr,
            "hrvMs": row.hrv_ms,
        }


def _state_summary(recovery, quality: dict, daypart: str,
                   health_row: dict | None = None) -> tuple[str, dict]:
    """One or two sentences on how the operator is doing, and the evidence.

    Refuses to characterise recovery at all when health data is stale, rather
    than describing a state from numbers that may be days old.

    Every clause is built only from a value that is actually present. An empty
    slot drops its whole clause instead of rendering — "Recovery reads ." is
    worse than saying nothing, because it looks like a bug the operator has to
    interpret.
    """
    evidence: dict = {}
    health = quality["health"]
    health_row = health_row or {}

    if not health.usable:
        return (
            f"{_DAYPART_FRAMING[daypart]} No current health data, so nothing to say "
            "about how you are recovering.",
            {"health": health.as_dict()},
        )

    parts: list[str] = []

    sleep = health_row.get("sleepHours")
    if sleep:
        evidence["sleepHours"] = sleep
        if sleep >= 7.5:
            parts.append(f"You slept {sleep:g} hours")
        elif sleep >= 6.5:
            parts.append(f"You slept {sleep:g} hours")
        else:
            parts.append(f"You slept {sleep:g} hours, which is short")

    score = getattr(recovery, "score", None)
    label = (getattr(recovery, "label", "") or "").strip()
    if score is not None and label:
        evidence["recoveryScore"] = round(score, 1)
        evidence["recoveryLabel"] = label
        if parts:
            parts.append(f"and recovery reads {label.lower()}")
        else:
            parts.append(f"Recovery reads {label.lower()}")
    elif score is not None:
        # A score with no label still says something; the number alone is
        # honest where an empty label would leave a dangling sentence.
        evidence["recoveryScore"] = round(score, 1)
        parts.append(
            f"and recovery is scoring {score:.0f}" if parts
            else f"Recovery is scoring {score:.0f}"
        )

    if not parts:
        return (
            f"{_DAYPART_FRAMING[daypart]} Health data is connected but thin today.",
            {"health": health.as_dict()},
        )

    return f"{' '.join(parts)}. {_DAYPART_FRAMING[daypart]}", evidence


def _focus(chosen: list[prio.ScoredTask], review: dict, daypart: str,
           quality: dict) -> str:
    """What the remainder of the day is for.

    Names the shape of the work rather than restating the task list, and stays
    silent about task counts when the task data is too old to assert them.
    """
    if not chosen:
        if daypart == "night":
            return "Nothing scheduled. Switch off."
        return "Nothing is scheduled. A good window to pick one thing and finish it."

    projects = {p.as_dict()["project"] for p in chosen}

    if daypart == "night":
        return "Too late to start anything substantial. Note tomorrow's first move and stop."

    if len(projects) == 1:
        project = next(iter(projects))
        base = f"Tonight is about {project}." if daypart == "evening" else f"Today is about {project}."
    else:
        base = (
            f"{len(chosen)} things worth finishing, across {len(projects)} areas."
            if daypart != "evening"
            else f"Clear {len(chosen)} commitments, then switch off."
        )

    # Staleness is deliberately *not* repeated here. The data-quality line below
    # already names the source and the date it went cold; saying it again as a
    # parenthetical put the same caveat on screen twice, three lines apart, and
    # pushed this sentence onto a second line to do it.
    return base


def _next_action(chosen: list[prio.ScoredTask]) -> str:
    """One concrete thing. Prefers a written next step over the task title.

    "Edit Struan's article" is a project; "open the draft and do the first
    pass" is something a person can start in the next thirty seconds.
    """
    if not chosen:
        return ""
    top = chosen[0]
    written = top.task.get("next_action")
    if written:
        return written
    return top.task["title"]


def _select_insight(uid: int, snap, recovery, quality: dict) -> dict:
    """At most one insight, and only when it is properly supported.

    Everything ORION could say is available on other screens. The homepage gets
    the single most decision-relevant item, or nothing — a page that shows its
    best insight and its fourth-best insight has taught the operator that
    insights are wallpaper.
    """
    if not quality["health"].usable:
        return {}

    candidates = []
    for change in getattr(recovery, "changes", []) or []:
        candidates.append({
            "id": f"change-{change.metric}",
            "title": change.metric,
            "body": change.text,
            "tone": change.tone,
            "domain": "recovery",
            "klass": "measured",
            "confidence": "high",
            "evidence": {
                "metric": change.metric,
                "delta": change.delta,
                "unit": change.unit,
                "direction": change.direction,
                "comparison": "7-day baseline",
            },
        })

    if not candidates:
        return {}

    # Prefer something that should change behaviour over something merely true.
    watch = [c for c in candidates if c["tone"] == "watch"]
    return (watch or candidates)[0]


def _timeline(uid: int, today: date, daypart: str, quality: dict) -> list[dict]:
    """What is left of the day, in order.

    Open space is left open. Filling every gap turns a plan into a schedule
    nobody agreed to, and hides whether the day is actually realistic.
    """
    if not quality["calendar"].usable:
        return []
    now = datetime.now()
    with session_scope() as s:
        rows = s.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == uid,
                CalendarEvent.starts_at >= datetime.combine(today, time.min),
                CalendarEvent.starts_at <= datetime.combine(today, time.max),
            )
            .order_by(CalendarEvent.starts_at)
        ).all()
        return [
            {
                "id": f"event-{e.id}",
                "time": e.starts_at.strftime("%H:%M"),
                "title": e.title,
                "detail": e.location or e.calendar_name or "",
                "kind": "event",
                "allDay": bool(e.all_day),
                "past": e.starts_at < now,
            }
            for e in rows
        ]


# --------------------------------------------------------------------------- #
# Generation and persistence
# --------------------------------------------------------------------------- #
def generate(uid: int, *, day: date | None = None, force: bool = False) -> dict:
    """Build (or reuse) today's brief.

    Reuses a stored brief for the same day and daypart. Regenerating on every
    load would make the "next action" change under the operator mid-glance, and
    would destroy the record of what was actually suggested.
    """
    day = day or date.today()
    part = daypart_for()

    if not force:
        existing = _load(uid, day)
        if existing and existing.get("daypart") == part:
            # The stored brief holds the narrative only. The live sections are
            # recomputed on every read — see _live_sections for why.
            return {**existing, **_live_sections(uid, day, part)}

    quality = dq.assess(uid)
    recovery = personal_os.get_recovery_snapshot(uid)
    snap = personal_os.get_today_snapshot(uid, recovery=recovery)
    tasks = get_tasks(uid, include_done=False)

    chosen = prio.select_priorities(
        tasks, today=day, limit=3,
        minutes_available=_DAYPART_MINUTES.get(part),
        energy=_energy_from(recovery),
    )
    live = _live_sections(uid, day, part, quality=quality, tasks=tasks)
    summary, evidence = _state_summary(recovery, quality, part, _latest_health(uid))
    insight = _select_insight(uid, snap, recovery, quality)
    warnings = dq.warnings_from(quality)
    generated_at = utcnow()

    payload = {
        "day": day.isoformat(),
        "daypart": part,
        "stateSummary": summary,
        "focus": _focus(chosen, live["review"], part, quality),
        "nextAction": _next_action(chosen),
        "priorities": [p.as_dict() for p in chosen],
        "insight": insight,
        "evidence": evidence,
        "dataQuality": warnings,
        "confidence": _confidence(quality, chosen),
        "ruleVersion": RULE_VERSION,
        "sourceDataAt": (
            dq.source_timestamp(quality).isoformat()
            if dq.source_timestamp(quality) else None
        ),
        "edited": False,
        "generatedAt": generated_at.isoformat(),
        **live,
    }

    _persist(uid, day, payload, generated_at=generated_at)
    _log_generated(uid, day, chosen)
    return payload


def _live_sections(
    uid: int, day: date, part: str, *, quality: dict | None = None,
    tasks: list | None = None,
) -> dict:
    """The parts of the brief that must reflect *now*, not when it was written.

    The narrative — how you're doing, what to focus on, the three priorities —
    is deliberately frozen for the day, so the page does not rewrite itself
    under the operator mid-glance. These three are the opposite: the backlog
    shrinks as tasks get done, the timeline's "next up" moves as the day
    passes, and a source that went stale an hour ago must say so. Freezing them
    would make the page quietly lie by lunchtime.

    Keeping them in one function is also what stops the stored brief and the
    freshly generated one from having different shapes — the bug that took the
    homepage down, because the frontend read `timeline` off a cached payload
    that never carried it.
    """
    quality = dq.assess(uid) if quality is None else quality
    tasks = get_tasks(uid, include_done=False) if tasks is None else tasks
    return {
        "review": review_mod.review_buckets(tasks, today=day),
        "timeline": _timeline(uid, day, part, quality),
        "sources": {k: v.as_dict() for k, v in quality.items()},
    }


def _energy_from(recovery) -> str:
    score = getattr(recovery, "score", None)
    if score is None:
        return ""
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _confidence(quality: dict, chosen: list) -> str:
    """How much the brief should be trusted as a whole."""
    stale = [q for q in quality.values() if q.trust != "live"]
    if len(stale) >= 2:
        return "low"
    if stale or not chosen:
        return "medium"
    return "high"


def _persist(
    uid: int, day: date, payload: dict, *, generated_at: datetime | None = None
) -> None:
    with session_scope() as s:
        row = s.scalars(
            select(DailyBrief).where(DailyBrief.user_id == uid, DailyBrief.day == day)
        ).first()
        if row is None:
            row = DailyBrief(user_id=uid, day=day)
            s.add(row)
        row.daypart = payload["daypart"]
        row.state_summary = payload["stateSummary"]
        row.focus = payload["focus"]
        row.next_action = payload["nextAction"]
        row.priorities = payload["priorities"]
        row.insight = payload["insight"]
        row.evidence = payload["evidence"]
        row.data_quality = payload["dataQuality"]
        row.confidence = payload["confidence"]
        row.rule_version = payload["ruleVersion"]
        row.generated_at = generated_at or utcnow()
        if payload["sourceDataAt"]:
            row.source_data_at = datetime.fromisoformat(payload["sourceDataAt"])


def _load(uid: int, day: date) -> dict | None:
    """A stored brief, with manual edits merged over the generated text."""
    with session_scope() as s:
        row = s.scalars(
            select(DailyBrief).where(DailyBrief.user_id == uid, DailyBrief.day == day)
        ).first()
        if row is None:
            return None
        edits = row.manual_edits or {}
        return {
            "day": row.day.isoformat(),
            "daypart": row.daypart,
            "stateSummary": edits.get("stateSummary", row.state_summary),
            "focus": edits.get("focus", row.focus),
            "nextAction": edits.get("nextAction", row.next_action),
            "priorities": row.priorities or [],
            "insight": row.insight or {},
            "evidence": row.evidence or {},
            "dataQuality": row.data_quality or [],
            "confidence": row.confidence,
            "ruleVersion": row.rule_version,
            "sourceDataAt": row.source_data_at.isoformat() if row.source_data_at else None,
            "edited": bool(edits),
            "generatedAt": row.generated_at.isoformat(),
        }


def _log_generated(uid: int, day: date, chosen: list) -> None:
    with session_scope() as s:
        for item in chosen:
            s.add(BriefEvent(
                user_id=uid, day=day, kind="priority_generated",
                task_id=item.task["id"], subject=item.task["title"],
                detail={"score": item.score, "pinned": item.pinned},
                daypart=daypart_for(),
            ))


# --------------------------------------------------------------------------- #
# Interaction
# --------------------------------------------------------------------------- #
def record_event(uid: int, kind: str, *, task_id: int | None = None,
                 subject: str = "", detail: dict | None = None,
                 day: date | None = None) -> None:
    with session_scope() as s:
        s.add(BriefEvent(
            user_id=uid, day=day or date.today(), kind=kind, task_id=task_id,
            subject=subject, detail=detail or {}, daypart=daypart_for(),
        ))


def defer_priority(uid: int, task_id: int, *, until: date | None = None) -> None:
    """Push a priority out, and remember that it was pushed.

    The counter is what stops the same task being offered every morning
    forever — and makes the pattern visible when the operator reviews.
    """
    with session_scope() as s:
        task = s.scalars(
            select(Task).where(Task.id == task_id, Task.user_id == uid)
        ).first()
        if task is None:
            raise ValueError("That task does not exist.")
        task.defer_until = until or (date.today() + timedelta(days=1))
        task.deferral_count = int(task.deferral_count or 0) + 1
    record_event(uid, "priority_deferred", task_id=task_id,
                 detail={"until": (until or date.today() + timedelta(days=1)).isoformat()})


def pin_priority(uid: int, task_id: int, *, day: date | None = None) -> None:
    day = day or date.today()
    with session_scope() as s:
        task = s.scalars(
            select(Task).where(Task.id == task_id, Task.user_id == uid)
        ).first()
        if task is None:
            raise ValueError("That task does not exist.")
        task.pinned_for = day
    record_event(uid, "priority_pinned", task_id=task_id, day=day)


def complete_task(uid: int, task_id: int) -> None:
    with session_scope() as s:
        task = s.scalars(
            select(Task).where(Task.id == task_id, Task.user_id == uid)
        ).first()
        if task is None:
            raise ValueError("That task does not exist.")
        task.status = "done"
        task.completed_at = utcnow()
        # Mark for push back to Supabase rather than writing there directly.
        task.dirty = 1
        title = task.title
    record_event(uid, "task_completed", task_id=task_id, subject=title)


def edit_brief(uid: int, day: date, **edits) -> None:
    """Operator override. Stored separately so the generated text survives."""
    allowed = {"stateSummary", "focus", "nextAction"}
    unknown = set(edits) - allowed
    if unknown:
        raise ValueError(f"Cannot edit: {', '.join(sorted(unknown))}")
    with session_scope() as s:
        row = s.scalars(
            select(DailyBrief).where(DailyBrief.user_id == uid, DailyBrief.day == day)
        ).first()
        if row is None:
            raise ValueError("No brief for that day.")
        merged = dict(row.manual_edits or {})
        merged.update({k: v for k, v in edits.items() if v is not None})
        row.manual_edits = merged
    record_event(uid, "brief_edited", detail=edits, day=day)


# --------------------------------------------------------------------------- #
# Analytics over the archive
# --------------------------------------------------------------------------- #
def effectiveness(uid: int, *, days: int = 90) -> dict:
    """Is any of this useful?

    The question the whole archive exists to answer. Reports counts rather than
    a satisfaction score — with one user and a short history, a percentage
    would be false precision.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.scalars(
            select(BriefEvent).where(
                BriefEvent.user_id == uid, BriefEvent.day >= since
            )
        ).all()
        briefs = s.scalars(
            select(DailyBrief).where(DailyBrief.user_id == uid, DailyBrief.day >= since)
        ).all()

    counts: dict[str, int] = {}
    by_daypart: dict[str, int] = {}
    deferred: dict[str, int] = {}
    for event in rows:
        counts[event.kind] = counts.get(event.kind, 0) + 1
        if event.kind == "task_completed":
            by_daypart[event.daypart] = by_daypart.get(event.daypart, 0) + 1
        if event.kind == "priority_deferred" and event.subject:
            deferred[event.subject] = deferred.get(event.subject, 0) + 1

    generated = counts.get("priority_generated", 0)
    completed = counts.get("task_completed", 0)
    return {
        "windowDays": days,
        "briefs": len(briefs),
        "events": counts,
        "prioritiesGenerated": generated,
        "prioritiesCompleted": completed,
        "acceptanceAvailable": generated > 0,
        "completionsByDaypart": by_daypart,
        "mostDeferred": sorted(deferred.items(), key=lambda kv: -kv[1])[:5],
        "note": (
            "Counts, not rates — one user over a short window cannot support a "
            "meaningful percentage."
            if generated < 30 else ""
        ),
    }
