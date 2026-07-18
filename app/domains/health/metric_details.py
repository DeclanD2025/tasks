"""Metric drilldowns: series, baselines, meaning, and honest caveats.

One registry drives every detail drawer in the web UI. Each entry declares
where its numbers come from and how to read them; the service returns plain
JSON-safe dicts. No interpretation happens in the web layer, and nothing is
invented: a metric with no rows returns an empty series plus the action that
would light it up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import (
    ActivityMetricDaily,
    HealthMetricDaily,
    MentalCheckIn,
    MindfulnessSession,
)
from app.domains import personal_os
from app.domains.health import derived

HAE_SOURCE = "Health Auto Export → Apple Health"


@dataclass(frozen=True)
class MetricSpec:
    kind: str
    title: str
    unit: str
    source: str
    meaning: str
    how: str  # how the number is produced (calculation transparency)
    caveat: str = ""
    lower_better: bool = False
    decimals: int = 1
    related: tuple[str, ...] = ()
    missing_action: str = "Import a Health Auto Export file on the Data tab."


METRIC_SPECS: dict[str, MetricSpec] = {
    "sleep": MetricSpec(
        "sleep", "Sleep", "h", HAE_SOURCE,
        "Nightly time asleep. Consistency moves recovery more than any single "
        "long night.",
        "Sum of Apple Health sleep samples per night, converted to hours.",
        related=("sleep_debt", "hrv", "resting_hr"),
    ),
    "sleep_debt": MetricSpec(
        "sleep_debt", "Sleep debt", "h", "Derived from your sleep history",
        "Accumulated shortfall against your own sleep need over the last 14 "
        "recorded nights. Under about 15 minutes counts as clear.",
        "Personal need = trimmed mean of your recent plausible nights (not a "
        "generic 8-hour rule). Debt = Σ max(need − actual, surplus caps at "
        "need+1h) across the window.",
        "A guide for planning easier days — not a diagnosis.",
        lower_better=True,
        related=("sleep", "readiness"),
    ),
    "hrv": MetricSpec(
        "hrv", "HRV", "ms", HAE_SOURCE,
        "Beat-to-beat variability (SDNN). Higher than your own baseline "
        "usually reads as better-absorbed stress.",
        "Daily mean of Apple Watch HRV samples.",
        "Only your own baseline matters; single-day swings are noise. "
        "Alcohol, illness and late meals push it around.",
        related=("resting_hr", "sleep", "readiness"),
    ),
    "resting_hr": MetricSpec(
        "resting_hr", "Resting heart rate", "bpm", HAE_SOURCE,
        "Beats per minute at full rest. Downward drift over months tracks "
        "improving aerobic fitness; a sudden rise often precedes illness.",
        "Apple Watch resting heart rate estimate, daily mean.",
        lower_better=True, decimals=0,
        related=("hrv", "vo2max", "readiness"),
    ),
    "weight": MetricSpec(
        "weight", "Weight", "kg", HAE_SOURCE,
        "Trend, not judgement: the 7-day average is the real signal, daily "
        "readings swing 1–2 kg on water alone.",
        "Latest smart-scale or manual entry per day; the chart overlays a "
        "7-day rolling average.",
        related=("run_distance", "active_energy"),
    ),
    "vo2max": MetricSpec(
        "vo2max", "VO₂ max", "ml/kg·min", HAE_SOURCE,
        "Estimated aerobic ceiling. Moves slowly — weeks, not days. The most "
        "durable lever is consistent easy-pace volume.",
        "Apple Watch cardio-fitness estimate from outdoor walk/run heart-rate "
        "response.",
        "A wrist estimate, not a lab test; treat the trend as real and the "
        "absolute number as approximate.",
        related=("run_distance", "resting_hr"),
    ),
    "run_distance": MetricSpec(
        "run_distance", "Run / walk distance", "km", HAE_SOURCE,
        "Daily moving distance. The weekly total is what the run plan "
        "progresses — see the Training tab.",
        "Apple Health walking+running distance per day.",
        related=("training_load", "vo2max"),
    ),
    "steps": MetricSpec(
        "steps", "Steps", "", HAE_SOURCE,
        "Background movement. It carries more of daily energy burn than "
        "workouts for most people.",
        "Apple Health daily step count.",
        decimals=0,
        missing_action="Add 'Steps' to your Health Auto Export metric "
                       "selection, then import on the Data tab.",
        related=("active_energy", "run_distance"),
    ),
    "active_energy": MetricSpec(
        "active_energy", "Active energy", "kcal", HAE_SOURCE,
        "Estimated calories burned above resting. Useful as a relative "
        "training-volume signal, not a food-licence calculator.",
        "Apple Health active energy per day.",
        decimals=0,
        missing_action="Add 'Active Energy' to your HAE export, then import "
                       "on the Data tab.",
        related=("steps", "training_load"),
    ),
    "respiratory_rate": MetricSpec(
        "respiratory_rate", "Respiratory rate", "/min", HAE_SOURCE,
        "Breaths per minute while asleep. Very stable night to night, which is "
        "what makes a sustained rise worth noticing — it often moves before you "
        "feel unwell.",
        "Apple Watch sleeping respiratory rate, daily mean.",
        "A rise on its own means little; read it next to resting HR and HRV.",
        related=("resting_hr", "hrv", "sleep"),
    ),
    "mindfulness": MetricSpec(
        "mindfulness", "Mindfulness", "min", "Apple Health + ORION sessions",
        "Minutes of deliberate attention practice. Consistency beats "
        "duration — a 3-minute daily floor holds the habit.",
        "Apple Health mindful minutes plus sessions logged in ORION, per day.",
        decimals=0,
        missing_action="Log a session on the Mind tab — one minute counts.",
        related=("mood", "sleep"),
    ),
    "mood": MetricSpec(
        "mood", "Mood", "", "Apple Health State of Mind + check-ins",
        "Daily emotional valence from −1 to +1. Patterns matter more than "
        "points: watch what sleep, training and people do to the line.",
        "Mean of Apple 'State of Mind' valence entries per day.",
        "Self-report is noisy by nature. A low day is data, not a verdict.",
        missing_action="Log State of Mind in Apple Health, or check in on "
                       "the Mind tab.",
        related=("mindfulness", "sleep", "stress"),
    ),
    "stress": MetricSpec(
        "stress", "Stress", "/10", "ORION evening debriefs",
        "Self-rated stress from the evening debrief. Watch the weekly shape, "
        "not single evenings.",
        "The 1–10 stress rating you log each evening on the Mind tab.",
        missing_action="Complete tonight's debrief on the Mind tab.",
        related=("mood", "sleep"),
    ),
    "training_load": MetricSpec(
        "training_load", "Training strain", "TRIMP", "Derived from workout heart rate",
        "Edwards TRIMP: duration weighted by heart-rate zone. Sharp spikes "
        "against your recent norm are where niggles start.",
        "Per workout: minutes in each HR zone × zone weight (1–5), summed "
        "per day from imported workouts.",
        "Estimated from average workout HR, not measured lactate — treat "
        "bands as rough.",
        decimals=0,
        missing_action="Import workouts with heart rate via HAE.",
        related=("run_distance", "readiness"),
    ),
    "readiness": MetricSpec(
        "readiness", "Readiness", "/100", "Derived from your own baselines",
        "A transparent recovery proxy that gates training intensity "
        "suggestions. Low readiness downgrades the day, it never shames it.",
        "Weighted blend of sleep vs need, HRV vs 30-day baseline, resting HR "
        "vs baseline, and recent strain. Every factor and its exact "
        "contribution is listed on the Health tab.",
        "Not a clinical measure. It cannot see illness, caffeine or a bad "
        "day at work unless the sensors do.",
        decimals=0,
        related=("sleep", "hrv", "resting_hr", "training_load"),
    ),
    "blood_pressure": MetricSpec(
        "blood_pressure", "Blood pressure", "mmHg", HAE_SOURCE,
        "Systolic over diastolic pressure. A single reading is less useful "
        "than the trend over weeks; watch for sustained elevation.",
        "Apple Health blood pressure samples, latest systolic and diastolic.",
        decimals=0,
        missing_action="Add 'Blood Pressure' to your HAE export, then import "
                       "on the Data tab.",
        related=("resting_hr", "hrv"),
    ),
}


def _series_from_rows(rows: list[tuple], transform=None) -> list[dict]:
    out = []
    for day, value in rows:
        if value is None:
            continue
        out.append({"day": day.isoformat(),
                    "value": round(transform(value) if transform else float(value), 3)})
    return out


def _health_column_series(uid: int, column, days: int, transform=None) -> list[dict]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, column)
            .where(HealthMetricDaily.user_id == uid, HealthMetricDaily.day >= since)
            .order_by(HealthMetricDaily.day)
        ).all()
    return _series_from_rows(rows, transform)


def _extra_series(uid: int, key: str, days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == uid, HealthMetricDaily.day >= since)
            .order_by(HealthMetricDaily.day)
        ).all()
    return _series_from_rows(
        [(day, (extra or {}).get(key)) for day, extra in rows]
    )


def _activity_column_series(uid: int, column, days: int) -> list[dict]:
    """Read a daily activity metric (steps / active minutes) from its own table.

    HAE routes movement into ``ActivityMetricDaily`` — not the health-metric
    extra — so steps and active energy are read from here, not ``_extra_series``.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(ActivityMetricDaily.day, column)
            .where(ActivityMetricDaily.user_id == uid, ActivityMetricDaily.day >= since)
            .order_by(ActivityMetricDaily.day)
        ).all()
    return _series_from_rows(rows)


def _active_energy_series(uid: int, days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(ActivityMetricDaily.day, ActivityMetricDaily.extra)
            .where(ActivityMetricDaily.user_id == uid, ActivityMetricDaily.day >= since)
            .order_by(ActivityMetricDaily.day)
        ).all()
    return _series_from_rows(
        [(day, (extra or {}).get("active_energy_kcal")) for day, extra in rows]
    )


def _mindfulness_series(uid: int, days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    imported = { }
    for point in _extra_series(uid, "mindful_minutes", days):
        imported[point["day"]] = point["value"]
    with session_scope() as s:
        rows = s.execute(
            select(MindfulnessSession.day, MindfulnessSession.duration_minutes)
            .where(MindfulnessSession.user_id == uid, MindfulnessSession.day >= since)
        ).all()
    for day, minutes in rows:
        key = day.isoformat()
        imported[key] = imported.get(key, 0) + (minutes or 0)
    return [{"day": k, "value": v} for k, v in sorted(imported.items())]


def _stress_series(uid: int, days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(MentalCheckIn.day, MentalCheckIn.stress)
            .where(MentalCheckIn.user_id == uid, MentalCheckIn.day >= since)
            .order_by(MentalCheckIn.day)
        ).all()
    return _series_from_rows(rows)


def _strain_series(uid: int, days: int) -> list[dict]:
    return [
        {"day": d.day.isoformat(), "value": round(d.trimp, 1)}
        for d in derived.get_strain_days(uid, days=days)
    ]


def _latest_blood_pressure(uid: int) -> tuple[float | None, float | None]:
    """Return the most recent stored systolic/diastolic pair, if any."""
    with session_scope() as s:
        row = s.scalars(
            select(HealthMetricDaily)
            .where(HealthMetricDaily.user_id == uid)
            .where(HealthMetricDaily.extra.is_not(None))
            .order_by(HealthMetricDaily.day.desc())
            .limit(1)
        ).first()
    if row is None:
        return None, None
    extra = row.extra or {}
    try:
        return float(extra["bp_systolic"]), float(extra["bp_diastolic"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _blood_pressure_series(uid: int, days: int) -> list[dict]:
    """Latest blood pressure per day as mean arterial pressure.

    Systolic and diastolic are stored in HealthMetricDaily.extra. The drilldown
    shows the combined pressure trend; the exact pair is surfaced in facts.
    """
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(HealthMetricDaily.day, HealthMetricDaily.extra)
            .where(HealthMetricDaily.user_id == uid, HealthMetricDaily.day >= since)
            .order_by(HealthMetricDaily.day)
        ).all()
    out = []
    for day, extra in rows:
        extra = extra or {}
        sys = extra.get("bp_systolic")
        dia = extra.get("bp_diastolic")
        if sys is None or dia is None:
            continue
        try:
            map_value = (float(sys) + 2 * float(dia)) / 3
        except (TypeError, ValueError):
            continue
        out.append({"day": day.isoformat(), "value": round(map_value, 1)})
    return out


def _series_for(uid: int, kind: str, days: int) -> list[dict]:
    if kind == "sleep":
        return _health_column_series(uid, HealthMetricDaily.sleep_minutes, days,
                                     lambda v: v / 60.0)
    if kind == "hrv":
        return _health_column_series(uid, HealthMetricDaily.hrv_ms, days)
    if kind == "resting_hr":
        return _health_column_series(uid, HealthMetricDaily.resting_hr, days)
    if kind == "weight":
        return _health_column_series(uid, HealthMetricDaily.weight_kg, days)
    if kind == "vo2max":
        return _extra_series(uid, "vo2max", days)
    if kind == "run_distance":
        return _extra_series(uid, "distance_km", days)
    if kind == "steps":
        return _activity_column_series(uid, ActivityMetricDaily.steps, days)
    if kind == "active_energy":
        return _active_energy_series(uid, days)
    if kind == "mood":
        return _extra_series(uid, "mood", days)
    if kind == "respiratory_rate":
        return _extra_series(uid, "respiratory_rate", days)
    if kind == "mindfulness":
        return _mindfulness_series(uid, days)
    if kind == "stress":
        return _stress_series(uid, days)
    if kind == "training_load":
        return _strain_series(uid, days)
    if kind == "blood_pressure":
        return _blood_pressure_series(uid, days)
    return []


def _rolling(series: list[dict], window: int) -> list[dict]:
    values = [p["value"] for p in series]
    out = []
    for i in range(len(series)):
        window_vals = values[max(0, i - window + 1): i + 1]
        out.append({"day": series[i]["day"], "value": round(mean(window_vals), 2)})
    return out


def _typical_band(values: list[float]) -> list[float] | None:
    """The user's own habitual range: the interquartile band of recent points.

    Honest and personal — the shaded zone shows where this body usually sits,
    not a clinical reference range. Needs enough points to be meaningful.
    """
    recent = values[-45:]
    if len(recent) < 8:
        return None
    ordered = sorted(recent)
    n = len(ordered)

    def pct(p: float) -> float:
        idx = p * (n - 1)
        lo = int(idx)
        frac = idx - lo
        hi = min(lo + 1, n - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * frac

    lo, hi = pct(0.25), pct(0.75)
    if hi <= lo:
        return None
    return [round(lo, 2), round(hi, 2)]


def get_metric_detail(uid: int, kind: str, days: int = 90) -> dict | None:
    """The full drilldown payload for one metric, or None for unknown kinds."""
    spec = METRIC_SPECS.get(kind)
    if spec is None:
        return None
    days = max(7, min(int(days or 90), 365))

    facts: list[dict] = []
    if kind == "readiness":
        recovery = personal_os.get_recovery_snapshot(uid)
        series: list[dict] = []
        facts = [
            {"label": f.label, "value": f.value, "detail": f.impact}
            for f in recovery.factors
        ]
        latest = recovery.score
    elif kind == "sleep_debt":
        debt = derived.get_sleep_debt(uid)
        series = _series_for(uid, "sleep", days)
        latest = round((debt.debt_minutes or 0) / 60.0, 1) if not debt.calibrating else None
        facts = [
            {"label": "Personal need",
             "value": f"{(debt.need_minutes or 0) / 60:.1f} h"
             if debt.need_minutes else "calibrating",
             "detail": "Trimmed mean of your recent plausible nights."},
            {"label": "Nights recorded", "value": str(debt.nights_recorded),
             "detail": f"{derived.CALIBRATION_NIGHTS} needed before the debt is "
                       "trusted."},
            {"label": "Debt now", "value": debt.label,
             "detail": "Net shortfall across the last 14 recorded nights."},
        ]
        if debt.trend_minutes is not None:
            direction = "growing" if debt.trend_minutes > 0 else "shrinking"
            facts.append({"label": "Week trend",
                          "value": f"{abs(debt.trend_minutes) / 60:.1f} h {direction}",
                          "detail": "Debt now vs one week ago."})
    elif kind == "blood_pressure":
        series = _series_for(uid, kind, days)
        latest_sys, latest_dia = _latest_blood_pressure(uid)
        latest = None
        if latest_sys is not None and latest_dia is not None:
            latest = f"{latest_sys:.0f}/{latest_dia:.0f}"
            facts = [
                {"label": "Systolic", "value": f"{latest_sys:.0f} mmHg",
                 "detail": "Pressure when the heart contracts."},
                {"label": "Diastolic", "value": f"{latest_dia:.0f} mmHg",
                 "detail": "Pressure when the heart relaxes."},
            ]
    else:
        series = _series_for(uid, kind, days)
        latest = series[-1]["value"] if series else None

    values = [p["value"] for p in series]
    baseline7 = round(mean(values[-7:]), 2) if len(values) >= 3 else None
    baseline30 = round(mean(values[-30:]), 2) if len(values) >= 10 else None
    freshness = series[-1]["day"] if series else None

    return {
        "kind": kind,
        "title": spec.title,
        "unit": spec.unit,
        "latest": latest,
        "series": series,
        "rolling7": _rolling(series, 7) if len(series) >= 5 else [],
        "baseline7": baseline7,
        "baseline30": baseline30,
        "band": _typical_band(values),
        "lower_better": spec.lower_better,
        "decimals": spec.decimals,
        "meaning": spec.meaning,
        "how": spec.how,
        "caveat": spec.caveat,
        "source": spec.source,
        "freshness": freshness,
        "facts": facts,
        "related": [
            {"kind": r, "title": METRIC_SPECS[r].title}
            for r in spec.related if r in METRIC_SPECS
        ],
        "empty": not series and not facts,
        "missing_action": spec.missing_action,
    }
