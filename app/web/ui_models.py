"""ORION read models reshaped for the Next.js UI (``frontend/lib/types.ts``).

The Jinja templates consume the dataclasses in ``app.domains`` directly. The
Next app is a static export that fetches JSON, so it needs the same numbers in
the exact camelCase shapes its TypeScript declares. This module is the only
place that translation happens.

It computes nothing new: no scoring, no interpretation beyond phrasing a
comparison that the numbers already contain. Where ORION has no producer for
something the UI can display — habits and goals have no table — the payload
returns an empty list and an ``unavailable`` note. It never invents a value to
fill a slot.
"""

from __future__ import annotations

from datetime import date, datetime
from statistics import mean

from app import services
from app.db.database import session_scope
from app.db.models import DataSource, SourceStatus, User
from app.domains import personal_os, strength
from app.domains.health import derived, metric_details
from app.web import presentation

# --------------------------------------------------------------- vocabulary

# Which semantic colour a metric belongs to (frontend/lib/domains.ts).
DOMAIN_BY_KIND: dict[str, str] = {
    "sleep": "sleep",
    "sleep_debt": "sleep",
    "readiness": "recovery",
    "hrv": "recovery",
    "respiratory_rate": "recovery",
    "resting_hr": "cardio",
    "vo2max": "cardio",
    "steps": "cardio",
    "active_energy": "cardio",
    "blood_pressure": "cardio",
    "run_distance": "running",
    "training_load": "running",
    "weight": "nutrition",
    "mood": "mind",
    "mindfulness": "mind",
    "stress": "mind",
}

# Metrics ORION derives from other metrics rather than reading from a device.
_CALCULATED = {"readiness", "sleep_debt", "training_load", "stress"}

# ChangeRecord.metric is a display label; map it back to a metric kind so the
# change inherits the same colour as the metric it describes.
_KIND_BY_CHANGE_METRIC = {
    "Sleep": "sleep",
    "HRV": "hrv",
    "Resting HR": "resting_hr",
    "Training load": "training_load",
    "Mood": "mood",
}

# `area` is a human label on both OperatingInsight and DailyPlanItem, and the
# two use slightly different vocabularies. Both are covered here.
_DOMAIN_BY_AREA = {
    "Recovery": "recovery",
    "Run Plan": "running",
    "Running": "running",
    "Training": "strength",
    "Strength": "strength",
    "Mind": "mind",
    "Mindfulness": "mind",
    "Money": "neutral",
    "Finance": "neutral",
    "Nutrition": "nutrition",
    "Sleep": "sleep",
}


def domain_for(kind: str) -> str:
    return DOMAIN_BY_KIND.get(kind, "neutral")


# ----------------------------------------------------------------- helpers


def _freshness(day_iso: str | None) -> str:
    """"today" / "yesterday" / "6 days ago" — how current the last reading is."""
    if not day_iso:
        return "no data"
    try:
        seen = date.fromisoformat(str(day_iso)[:10])
    except ValueError:
        return str(day_iso)
    days = (date.today() - seen).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return seen.strftime("%-d %b")


def _hours_label(hours: float) -> str:
    """6.32 -> "6h 19m"."""
    total = int(round(hours * 60))
    return f"{total // 60}h {total % 60:02d}m"


def _display_value(kind: str, latest, decimals: int) -> str:
    if latest is None:
        return "—"
    if isinstance(latest, str):  # blood pressure arrives pre-formatted
        return latest
    if kind in ("sleep", "sleep_debt"):
        return _hours_label(float(latest))
    if decimals == 0:
        return f"{float(latest):,.0f}"
    return f"{float(latest):,.{decimals}f}"


def _trend(values: list[float]) -> str:
    """Latest against the preceding week, with a dead band for noise.

    Direction only — whether "up" is good depends on the metric, which is what
    ``_tone`` decides. Mirrors ``personal_os._trend`` so a metric never reads
    "up" on one screen and "flat" on another.
    """
    if len(values) < 4:
        return "flat"
    latest = values[-1]
    baseline = mean(values[:-1][-7:])
    delta = latest - baseline
    if abs(delta) < max(abs(baseline) * 0.04, 0.8):
        return "flat"
    return "up" if delta > 0 else "down"


def _tone(trend: str, *, lower_better: bool) -> str:
    if trend == "flat":
        return "flat"
    improving = (trend == "down") if lower_better else (trend == "up")
    return "good" if improving else "watch"


def _interpretation(
    latest, baseline30: float | None, unit: str, decimals: int, *, lower_better: bool
) -> str:
    """One honest sentence comparing today with the user's own baseline."""
    if latest is None or isinstance(latest, str):
        return "" if latest is None else "Latest reading."
    if baseline30 is None:
        return "Baseline still building — not enough recorded days yet."
    diff = float(latest) - baseline30
    suffix = f" {unit}".rstrip()
    if abs(diff) < max(abs(baseline30) * 0.04, 0.8):
        return f"Near your 30-day baseline of {baseline30:,.{decimals}f}{suffix}."
    direction = "above" if diff > 0 else "below"
    improving = (diff < 0) if lower_better else (diff > 0)
    verdict = "in your favour" if improving else "worth watching"
    return (
        f"{abs(diff):,.{decimals}f}{suffix} {direction} your 30-day baseline of "
        f"{baseline30:,.{decimals}f}{suffix} — {verdict}."
    )


# ----------------------------------------------------------- metric detail


def metric_detail(uid: int, kind: str, days: int = 90) -> dict | None:
    """One metric in the shape of the TS ``MetricDetail``."""
    raw = metric_details.get_metric_detail(uid, kind, days=days)
    if raw is None:
        return None

    series = raw["series"]
    values = [p["value"] for p in series if isinstance(p.get("value"), (int, float))]
    latest = raw["latest"]
    decimals = int(raw["decimals"])
    lower_better = bool(raw["lower_better"])
    trend = _trend(values)

    if not series and not raw["facts"]:
        quality = "missing"
    elif kind in _CALCULATED:
        quality = "calculated"
    else:
        quality = "measured"

    band = raw["band"]
    return {
        "kind": kind,
        "title": raw["title"],
        "unit": raw["unit"],
        "domain": domain_for(kind),
        "latest": latest if not isinstance(latest, str) else None,
        "displayValue": _display_value(kind, latest, decimals),
        "trend": trend,
        "quality": quality,
        "series": series,
        "baseline7": raw["baseline7"],
        "baseline30": raw["baseline30"],
        "band": list(band) if band else None,
        "lowerBetter": lower_better,
        "decimals": decimals,
        "meaning": raw["meaning"],
        "how": raw["how"],
        "caveat": raw["caveat"],
        "source": raw["source"],
        "freshness": _freshness(raw["freshness"]),
        "interpretation": _interpretation(
            latest, raw["baseline30"], raw["unit"], decimals, lower_better=lower_better
        ),
        "facts": raw["facts"],
        "related": raw["related"],  # [{kind, title}] — the UI links by kind, labels by title
    }


def metric_details_for(uid: int, kinds: list[str], days: int = 90) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for kind in kinds:
        detail = metric_detail(uid, kind, days=days)
        if detail is not None:
            out[kind] = detail
    return out


# ---------------------------------------------------------------- insights


def _insight(index: int, item: personal_os.OperatingInsight) -> dict:
    """OperatingInsight -> TS ``Insight``.

    Every one of these is a rule evaluated over measured data, so they are all
    classified "calculated". The rule's suggested action rides along separately
    rather than being blended into the finding — the UI labels them differently
    because they warrant different levels of trust.
    """
    return {
        "id": f"insight-{index}",
        "title": item.title,
        "body": item.explanation,
        "domain": _DOMAIN_BY_AREA.get(item.area, "neutral"),
        "klass": "calculated",
        "confidence": item.confidence if item.confidence in ("high", "medium", "low")
        else "medium",
        "action": item.action,
        "severity": item.severity,
    }


def insights(uid: int, snapshot: personal_os.TodaySnapshot | None = None) -> list[dict]:
    snap = snapshot or personal_os.get_today_snapshot(uid)
    ordered = sorted(
        snap.insights,
        key=lambda i: presentation.SEVERITY_RANK.get(i.severity, 9),
    )
    return [_insight(i, item) for i, item in enumerate(ordered)]


# ------------------------------------------------------------ data sources


def sync_sources(uid: int) -> list[dict]:
    """Configured integrations and how fresh each one is."""
    out: list[dict] = []
    with session_scope() as session:
        rows = session.query(DataSource).filter(DataSource.user_id == uid).all()
        for row in rows:
            if row.status is SourceStatus.connected:
                stale = (
                    row.last_synced_at is None
                    or (datetime.now() - row.last_synced_at).days >= 2
                )
                status = "stale" if stale else "ok"
            elif row.status is SourceStatus.mock:
                status = "mock"
            elif row.status is SourceStatus.error:
                status = "error"
            else:
                status = "disconnected"
            out.append({
                "name": row.name,
                "status": status,
                "freshness": _freshness(
                    row.last_synced_at.date().isoformat() if row.last_synced_at else None
                ),
            })
    out.sort(key=lambda s: (s["status"] == "disconnected", s["name"]))
    return out


# -------------------------------------------------------------- status strip

# The four cards across the top of Today, in order. Units come from the metric
# spec, not from here — readiness is the one exception because it is a score
# out of 100 that the spec carries no unit for.
_STRIP = [
    ("readiness", "Recovery", "/100"),
    ("sleep", "Sleep", None),
    ("steps", "Activity", None),
    ("mood", "Check-in", None),
]


def status_strip(uid: int) -> list[dict]:
    out: list[dict] = []
    for kind, label, unit_override in _STRIP:
        detail = metric_detail(uid, kind, days=30)
        if detail is None:
            continue
        unit = detail["unit"] if unit_override is None else unit_override
        lower_better = detail["lowerBetter"]
        trend = detail["trend"]
        baseline = detail["baseline7"]
        coverage = detail.get("coverage7") or {}
        if detail["latest"] is None:
            delta_text = "not recorded today"
        elif baseline is None:
            delta_text = "baseline building"
        else:
            diff = float(detail["latest"]) - baseline
            sign = "+" if diff >= 0 else "−"
            delta_text = (
                f"{sign}{abs(diff):,.{detail['decimals']}f} vs 7-day "
                f"{baseline:,.{detail['decimals']}f}"
            )
            # Say what the baseline rests on when the week is not fully
            # captured, so a thin average is not read as a solid one.
            used, of = coverage.get("used"), coverage.get("of")
            if used is not None and of and used < of:
                delta_text += f" ({used} of {of} days)"
        out.append({
            "kind": kind,
            "label": label,
            "domain": detail["domain"],
            "value": detail["displayValue"],
            "unit": unit,
            "trend": trend,
            "deltaText": delta_text,
            "tone": "flat" if detail["latest"] is None
            else _tone(trend, lower_better=lower_better),
        })
    return out


# ------------------------------------------------------------------- today


def _recommendation(
    snap: personal_os.TodaySnapshot, recovery: personal_os.RecoverySnapshot
) -> dict | None:
    """Today's single call, with the factors that produced it as evidence."""
    if not snap.training_recommendation:
        return None
    evidence = [
        {
            "label": factor.label,
            "value": factor.value,
            "tone": {"improving": "good", "watch": "watch"}.get(factor.impact, "flat"),
        }
        for factor in recovery.factors
        if factor.present
    ]
    return {
        "id": "today-training",
        "title": snap.training_recommendation,
        # recovery.recommendation is the reasoning behind the training call.
        # snap.suggested_action is the day's next nudge and can be about
        # something else entirely, so it must not be presented as the why.
        "body": recovery.recommendation,
        "domain": "running",
        "confidence": recovery.data_quality
        if recovery.data_quality in ("high", "medium", "low")
        else "medium",
        "evidence": evidence,
        "actions": [{"label": "View evidence", "kind": "ghost"}],
    }


def _timeline(uid: int, snap: personal_os.TodaySnapshot) -> list[dict]:
    """Today's real calendar, then the plan items ORION generated for today."""
    now = datetime.now()
    entries: list[dict] = []
    for index, event in enumerate(services.calendar_events(uid, days_back=0, days_forward=1)):
        if event["starts_at"].date() != date.today() or event["all_day"]:
            continue
        ends = event["ends_at"] or event["starts_at"]
        if ends < now:
            status = "done"
        elif event["starts_at"] <= now <= ends:
            status = "now"
        else:
            status = "upcoming"
        entries.append({
            "id": f"cal-{index}",
            "time": event["starts_at"].strftime("%H:%M"),
            "title": event["title"],
            "detail": event.get("location") or "",
            "domain": "neutral",
            "status": status,
        })
    for index, item in enumerate(snap.plan):
        # No `loggable` flag: logging has no write endpoint yet, and a Log
        # button that silently does nothing is worse than no button.
        entries.append({
            "id": f"plan-{index}",
            "time": "",
            "title": item.title,
            "detail": item.detail,
            "domain": _DOMAIN_BY_AREA.get(item.area, "neutral"),
            "status": "upcoming",
        })
    return entries


def _change(change: personal_os.ChangeRecord) -> dict:
    """ChangeRecord -> TS ``Change``.

    The UI prints the metric name in its own column, so the sentence is rebuilt
    from the record's parts without it — reusing ``change.text`` verbatim would
    render "Sleep · Sleep is up vs 7-day baseline".
    """
    if not change.metric:  # the "no drift detected" placeholder
        return {"metric": "", "domain": "neutral", "text": change.text, "tone": "flat"}
    unit = f" {change.unit}" if change.unit else ""
    return {
        "metric": change.metric,
        "domain": domain_for(_KIND_BY_CHANGE_METRIC.get(change.metric, "")),
        "text": f"{change.direction} vs 7-day baseline ({change.delta:+.1f}{unit})",
        "tone": change.tone,
    }


def _display_name(uid: int) -> str:
    with session_scope() as session:
        user = session.get(User, uid)
        return user.display_name if user else ""


def today(uid: int) -> dict:
    # Built once and threaded through: each of these rebuilds pandas frames
    # from SQLite, and Today needs all three. Recomputing them per section put
    # the page on a visible skeleton for seconds.
    recovery = personal_os.get_recovery_snapshot(uid)
    run_plan = personal_os.get_run_plan_snapshot(uid, recovery)
    snap = personal_os.get_today_snapshot(uid, recovery=recovery, run_plan=run_plan)
    return {
        "user": {"name": _display_name(uid), "today": date.today().isoformat()},
        "status": snap.status,
        "score": snap.score,
        "scoreLabel": snap.score_label,
        "estimated": snap.estimated,
        "freshness": snap.freshness_label,
        "sleepDebtLabel": snap.sleep_debt_label,
        "statusStrip": status_strip(uid),
        "recommendation": _recommendation(snap, recovery),
        # Today shows the next run and the sync list too. Serving them here
        # spares the page two more round trips into the same read models.
        "nextRun": {
            "title": run_plan.next_run.title,
            "detail": run_plan.next_run.detail,
            "distanceKm": run_plan.next_run.distance_km,
            "intensity": run_plan.next_run.intensity,
            "dayLabel": run_plan.next_run.day_label,
            "phase": f"Week {run_plan.current_week}",
        },
        "syncSources": sync_sources(uid),
        "timeline": _timeline(uid, snap),
        "changes": [_change(change) for change in recovery.changes],
        "insights": insights(uid, snap),
    }


# ----------------------------------------------------------------- recovery


def recovery(uid: int) -> dict:
    snap = personal_os.get_recovery_snapshot(uid)
    debt = derived.get_sleep_debt(uid)
    return {
        "score": snap.score,
        "label": snap.label,
        "estimated": snap.estimated,
        "dataQuality": snap.data_quality,
        "recommendation": snap.recommendation,
        "changes": snap.changes,
        "factors": [
            {
                "label": f.label,
                "value": f.value,
                "impact": f.impact,
                "contribution": f.contribution,
                "delta": f.delta,
                "present": f.present,
            }
            for f in snap.factors
        ],
        "sleepDebt": {
            "label": debt.label,
            "calibrating": debt.calibrating,
            "nightsRecorded": debt.nights_recorded,
        },
        "metrics": metric_details_for(
            uid, ["readiness", "sleep", "hrv", "resting_hr", "sleep_debt"]
        ),
    }


# ----------------------------------------------------------------- training


def training(uid: int) -> dict:
    plan = personal_os.get_run_plan_snapshot(uid)
    tracker = personal_os.get_workout_tracker_snapshot(uid)
    board = strength.dashboard(uid)
    return {
        "runPlan": {
            "goal": plan.goal,
            "phase": f"Week {plan.current_week}",
            "weekTargetKm": plan.weekly_target_km,
            "weekDoneKm": plan.week_distance_km,
            "fourWeekAvgKm": plan.average_distance_km,
            "avgPace": plan.average_pace_label,
            "adherence": plan.adherence_label,
            "guardrail": plan.guardrail,
            "nextRun": {
                "title": plan.next_run.title,
                "detail": plan.next_run.detail,
                "distanceKm": plan.next_run.distance_km,
                "intensity": plan.next_run.intensity,
                "dayLabel": plan.next_run.day_label,
            },
            "week": [
                {
                    "dayLabel": s.day_label,
                    "title": s.title,
                    "detail": s.detail,
                    "distanceKm": s.distance_km,
                    "intensity": s.intensity,
                    "sessionType": s.session_type,
                }
                for s in plan.weekly_plan
            ],
        },
        "strength": {
            "weekSessions": tracker.weekly_sessions,
            "weekVolumeKg": tracker.weekly_volume,
            "personalBests": tracker.personal_bests,
            "progressionInsight": tracker.progression_insight,
            "recentSessions": [
                {
                    "id": s.id,
                    "day": s.day.isoformat(),
                    "title": s.title,
                    "category": s.category,
                    "completed": s.completed,
                    "durationMinutes": s.duration_minutes,
                    "rpe": s.rpe,
                    "setCount": s.set_count,
                    "volume": s.volume,
                }
                for s in tracker.recent_sessions
            ],
        },
        "board": board,
        "metrics": metric_details_for(uid, ["run_distance", "training_load", "vo2max"]),
    }


# --------------------------------------------------------------------- plan


_INTENSITY = {"easy": "easy", "low": "easy", "moderate": "moderate", "hard": "hard"}


def _week(uid: int) -> list[dict]:
    """Mon–Sun of the current week: what actually happened on each day.

    Deliberately not the plan. ORION's run plan schedules sessions relative to
    now ("Next", "Midweek", "Weekend") and never commits them to a weekday, so
    placing them on the grid would be the UI inventing a fact the planner
    declined to state. The grid shows recorded activity; the plan is listed
    separately under the labels the planner actually uses.
    """
    today_date = date.today()
    monday = date.fromordinal(today_date.toordinal() - today_date.weekday())

    distance = {p["day"]: p["value"] for p in metric_details._series_for(uid, "run_distance", 60)}
    load = {p["day"]: p["value"] for p in metric_details._series_for(uid, "training_load", 60)}
    loads = [v for v in load.values() if v]
    typical = mean(loads) if loads else 0.0

    def band(value: float | None) -> str:
        if not value:
            return "clear"
        if not typical:
            return "light"
        if value >= typical * 1.5:
            return "heavy"
        if value >= typical:
            return "loaded"
        return "light"

    days: list[dict] = []
    for offset in range(7):
        day = date.fromordinal(monday.toordinal() + offset)
        iso = day.isoformat()
        km = distance.get(iso)
        sessions = []
        if km:
            sessions.append({
                "id": f"run-{iso}",
                "domain": "running",
                "title": f"{km:.1f} km",
                "detail": "Recorded",
                "durationMin": 0,
                "intensity": "moderate",
                "status": "done",
            })
        days.append({
            "date": iso,
            "dow": day.strftime("%a"),
            "dom": day.day,
            "isToday": day == today_date,
            "sessions": sessions,
            "loadBand": band(load.get(iso)),
        })
    return days


def _planned_sessions(
    uid: int, snapshot: personal_os.RunPlanSnapshot | None = None
) -> list[dict]:
    """ORION's planned running sessions, under the planner's own labels."""
    snapshot = snapshot or personal_os.get_run_plan_snapshot(uid)
    return [
        {
            "id": f"planned-{index}",
            "domain": "running",
            "when": session.day_label,
            "title": session.title,
            "detail": session.detail,
            "distanceKm": session.distance_km,
            "sessionType": session.session_type,
            "intensity": _INTENSITY.get(session.intensity, "moderate"),
        }
        for index, session in enumerate(snapshot.weekly_plan)
    ]


def plan(uid: int) -> dict:
    """The week: what was recorded, and what ORION plans next.

    Habits and goals have no table in ORION yet, so they come back empty with
    the reason attached — the UI shows an honest empty state rather than
    plausible-looking placeholders.
    """
    return {
        "week": _week(uid),
        "planned": _planned_sessions(uid),
        "habits": [],
        "goals": [],
        "unavailable": {
            "habits": "ORION has no habit store yet — nothing is being tracked.",
            "goals": "ORION has no goal store yet — nothing is being tracked.",
        },
    }


# ----------------------------------------------------------------- insights


def insights_page(uid: int, days: int = 90) -> dict:
    tracker = personal_os.get_workout_tracker_snapshot(uid)
    return {
        "insights": insights(uid),
        "metrics": metric_details_for(uid, BOARD_KINDS, days=days),
        "personalRecords": [
            {"domain": "strength", "label": pb, "value": "", "when": ""}
            for pb in tracker.personal_bests
        ],
        "syncSources": sync_sources(uid),
    }


BOARD_KINDS = [
    "readiness", "sleep", "hrv", "resting_hr",
    "run_distance", "training_load", "weight", "mood",
]

HEALTH_KINDS = ["vo2max", "resting_hr", "weight", "respiratory_rate", "blood_pressure"]

ALL_KINDS = sorted(set(BOARD_KINDS) | set(HEALTH_KINDS) | {
    "steps", "active_energy", "mindfulness", "sleep_debt",
})
