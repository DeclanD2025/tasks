"""Streaming parser for an Apple Health ``export.xml``.

Apple Health has no cloud API. The user exports their data from the Health app
(Profile → Export All Health Data), producing ``export.zip`` → ``export.xml``.
That file can be hundreds of MB, so we parse it with ``iterparse`` and clear
elements as we go, keeping memory flat.

We extract, per local day:
  * hrv_ms       — HeartRateVariabilitySDNN (mean of the day's samples, ms)
  * resting_hr   — RestingHeartRate (mean, bpm)
  * weight_kg    — BodyMass (last sample of the day, kg)
  * sleep_minutes— SleepAnalysis "asleep" segments, summed (minutes)
  * mood         — State of Mind valence in [-1, 1] (mean of the day), iOS 17+

Everything is local; no network. The result is a list of per-day dicts ready
for HealthMetricDaily upsert.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from app.core.logging import get_logger

log = get_logger(__name__)

# HealthKit identifiers we care about.
HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
RHR = "HKQuantityTypeIdentifierRestingHeartRate"
WEIGHT = "HKQuantityTypeIdentifierBodyMass"
SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
# "Asleep" sleep states (Apple split core/deep/REM in newer exports).
_ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}


@dataclass
class _DayAgg:
    hrv: list[float] = field(default_factory=list)
    rhr: list[float] = field(default_factory=list)
    weight: list[tuple[datetime, float]] = field(default_factory=list)
    sleep_seconds: float = 0.0
    mood: list[float] = field(default_factory=list)


def _parse_dt(value: str) -> datetime | None:
    # Apple format e.g. "2026-06-14 07:30:00 +0100"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except (ValueError, TypeError):
        return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_export(
    xml_path: str | Path, *, lookback_days: int | None = None
) -> list[dict]:
    """Parse ``export.xml`` into per-day health dicts.

    ``lookback_days`` optionally limits output to the most recent N days.
    Returns rows sorted by day ascending.
    """
    xml_path = Path(xml_path)
    if not xml_path.exists():
        raise FileNotFoundError(xml_path)

    days: dict[date, _DayAgg] = defaultdict(_DayAgg)

    # iterparse on "end" so each element is fully populated; clear to free memory.
    context = iterparse(str(xml_path), events=("end",))
    for _event, elem in context:
        tag = elem.tag
        if tag == "Record":
            _handle_record(elem, days)
        elif tag == "StateOfMind":
            _handle_state_of_mind(elem, days)
        elem.clear()

    rows = []
    for day in sorted(days):
        agg = days[day]
        rows.append({
            "day": day.isoformat(),
            "hrv_ms": round(_mean(agg.hrv), 1) if agg.hrv else None,
            "resting_hr": round(_mean(agg.rhr)) if agg.rhr else None,
            "weight_kg": round(agg.weight[-1][1], 1) if agg.weight else None,
            "sleep_minutes": round(agg.sleep_seconds / 60) if agg.sleep_seconds else None,
            "mood": round(_mean(agg.mood), 3) if agg.mood else None,
            "source": "apple_health_export",
        })

    if lookback_days is not None:
        rows = rows[-lookback_days:]
    log.info("Apple Health: parsed %d days from %s", len(rows), xml_path.name)
    return rows


def _handle_record(elem, days: dict[date, _DayAgg]) -> None:
    rtype = elem.get("type")
    if rtype not in (HRV, RHR, WEIGHT, SLEEP):
        return
    start = _parse_dt(elem.get("startDate", ""))
    if start is None:
        return
    day = start.astimezone().date()

    if rtype == SLEEP:
        if elem.get("value") in _ASLEEP_VALUES:
            end = _parse_dt(elem.get("endDate", ""))
            if end:
                days[day].sleep_seconds += (end - start).total_seconds()
        return

    val = _to_float(elem.get("value"))
    if val is None:
        return
    if rtype == HRV:
        days[day].hrv.append(val)
    elif rtype == RHR:
        days[day].rhr.append(val)
    elif rtype == WEIGHT:
        days[day].weight.append((start, val))


def _handle_state_of_mind(elem, days: dict[date, _DayAgg]) -> None:
    # iOS 17+ "State of Mind" logs. valence is in [-1, 1].
    start = _parse_dt(elem.get("startDate", "") or elem.get("date", ""))
    valence = _to_float(elem.get("valence"))
    if start is None or valence is None:
        return
    days[start.astimezone().date()].mood.append(valence)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
