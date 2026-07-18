"""Presentation-only helpers: formatting, deltas, sparklines.

No scoring or interpretation lives here — only how already-derived numbers are
shown (baseline comparisons, trend glyphs, money formatting).
"""

from __future__ import annotations

from statistics import mean

from app.db.database import session_scope
from app.db.models import Domain, Insight
from app.domains import personal_os

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
LOWER_BETTER = {"Resting HR", "Respiratory Rate"}
METRIC_UNITS = {
    "Sleep": "h",
    "HRV": "ms",
    "Resting HR": "bpm",
    "Steps": "",
    "Active Energy": "kcal",
    "Workout Load": "",
    "Run/Walk Distance": "km",
    "Weight": "kg",
    "Mindfulness": "min",
    "Mood": "",
    "Respiratory Rate": "/min",
    "Blood Pressure": "mmHg",
}

# Drilldown keys: which metric cards open which detail drawer (see routes/api.py).
METRIC_DETAIL_KEYS = {
    "Sleep": "sleep",
    "HRV": "hrv",
    "Resting HR": "resting_hr",
    "Weight": "weight",
    "Run/Walk Distance": "run_distance",
    "Steps": "steps",
    "Active Energy": "active_energy",
    "Mindfulness": "mindfulness",
    "Mood": "mood",
    "Workout Load": "training_load",
    "VO2 Max": "vo2max",
    "Blood Pressure": "blood_pressure",
}


def spark(series: list[float], width: int = 100, height: int = 28) -> str:
    """SVG polyline points for a small trend line (empty string if too sparse)."""
    values = [v for v in series if v is not None]
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    pad = 2
    usable = height - pad * 2
    return " ".join(
        f"{i * step:.1f},{height - pad - ((v - lo) / span) * usable:.1f}"
        for i, v in enumerate(values)
    )


def _fmt_quantity(value: float) -> str:
    return f"{value:+.1f}" if abs(value) < 10 else f"{value:+,.0f}"


def delta(metric: personal_os.TodayMetric) -> dict | None:
    """Latest value vs the trailing 7-point baseline, with a quality tone.

    Returns None when the series is too short to make a precise claim — the
    card then says "baseline pending" instead of implying a trend.
    """
    values = [v for v in metric.series if v is not None]
    if len(values) < 4:
        return None
    latest = values[-1]
    baseline = mean(values[:-1][-7:])
    if abs(latest) < 0.05 and abs(baseline) < 0.05:
        return None  # nothing happening vs nothing: no claim to make
    delta_value = latest - baseline
    unit = METRIC_UNITS.get(metric.label, "")
    threshold = max(abs(baseline) * 0.04, 0.05)
    if abs(delta_value) < threshold:
        tone, glyph = "flat", "—"
    else:
        rising = delta_value > 0
        good = (not rising) if metric.label in LOWER_BETTER else rising
        tone = "good" if good else "watch"
        glyph = "▲" if rising else "▼"
    baseline_label = f"{baseline:.1f}" if abs(baseline) < 10 else f"{baseline:,.0f}"
    return {
        "glyph": glyph,
        "text": f"{_fmt_quantity(delta_value)}{f' {unit}' if unit else ''} vs 7-day {baseline_label}",
        "tone": tone,
    }


def partition_metrics(
    metrics: list[personal_os.TodayMetric], primary_count: int = 6
) -> dict[str, list[personal_os.TodayMetric]]:
    """Split signals into a focused primary band, a disclosure, and gaps."""
    present = [m for m in metrics if m.quality != "missing"]
    missing = [m for m in metrics if m.quality == "missing"]
    return {
        "primary": present[:primary_count],
        "secondary": present[primary_count:],
        "missing": missing,
    }


def sorted_insights(
    insights: list[personal_os.OperatingInsight],
) -> list[personal_os.OperatingInsight]:
    return sorted(insights, key=lambda i: SEVERITY_RANK.get(i.severity, 9))


def money(value: float) -> str:
    sign = "−" if value < 0 else ""
    magnitude = abs(value)
    return f"{sign}£{magnitude:,.0f}" if magnitude >= 100 else f"{sign}£{magnitude:,.2f}"


def detail_key(label: str) -> str:
    return METRIC_DETAIL_KEYS.get(label, "")


def health_insights(user_id: int) -> list[dict]:
    """Return recent health-domain insights in the format the insight_queue macro expects."""
    with session_scope() as s:
        rows = (
            s.query(Insight)
            .filter(Insight.user_id == user_id, Insight.domain == Domain.health)
            .order_by(Insight.created_at.desc())
            .limit(10)
            .all()
        )
    return [
        {
            "title": row.title,
            "explanation": row.body,
            "severity": row.severity.value,
            "area": "Health",
            "action": "Review trend",
            "confidence": "high",
        }
        for row in rows
    ]
