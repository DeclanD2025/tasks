"""Parser for Health Auto Export (HealthyApps) JSON exports.

Health Auto Export is a paid iOS app that auto-syncs Apple Health data on a
schedule — to a REST endpoint or as JSON/CSV files. ORION uses the *file* route
(local-first, no open ports): the app writes JSON into a folder (e.g. iCloud
Drive), and ORION reads the latest file. As new files arrive, data refreshes —
unlike a one-shot Health export.xml, this keeps updating.

JSON shape (per the app's docs):

    {
      "data": {
        "metrics": [
          {"name": "heart_rate_variability", "units": "ms",
           "data": [{"qty": 55.2, "date": "2026-06-14 07:00:00 +0100"}, ...]},
          ...
        ],
        "workouts": [...]
      }
    }

Metric ``name`` slugs vary slightly by app version / locale, so we match each
ORION field against a set of aliases rather than one exact string. Sleep and
mindfulness are durations; State of Mind carries a valence we map to mood.

Output mirrors the export.xml parser: a list of per-day dicts ready for
HealthMetricDaily upsert (hrv_ms, resting_hr, sleep_minutes, weight_kg, mood,
mindful_minutes, distance_km, vo2max).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


# Map each ORION field to the HAE metric-name aliases that feed it. Lowercased,
# matched on a normalised (underscores/spaces stripped) basis.
_ALIASES: dict[str, set[str]] = {
    "hrv_ms": {"heartratevariability", "heartratevariabilitysdnn", "hrv"},
    "resting_hr": {"restingheartrate"},
    "weight_kg": {"weightbodymass", "bodymass", "weight"},
    "vo2max": {"vo2max", "vo2_max", "cardiofitness"},
    "distance_km": {"walkingrunningdistance", "distancewalkingrunning",
                    "walking_running_distance"},
    "steps": {"stepcount", "steps"},
    "active_energy_kcal": {"activeenergyburned", "activeenergy", "activecalories"},
    "exercise_minutes": {"appleexercisetime", "exercisetime", "workoutminutes"},
    "respiratory_rate": {"respiratoryrate", "respirationrate"},
    "sleep_minutes": {"sleepanalysis", "sleep"},
    "mindful_minutes": {"mindfulminutes", "mindfulness", "mindfulsession"},
    "mood": {"stateofmind", "state_of_mind", "mood"},
    # Whole-day heart-rate stream. Used only as a fallback for resting HR (its
    # daily minimum) when the dedicated "resting_heart_rate" metric is absent —
    # many HAE setups export heart_rate but not resting_heart_rate.
    "heart_rate": {"heartrate"},
}

# Fields where we SUM the day's points (durations / distances), vs average,
# vs take the latest reading, vs take the daily minimum.
_SUM_FIELDS = {
    "sleep_minutes",
    "mindful_minutes",
    "distance_km",
    "steps",
    "active_energy_kcal",
    "exercise_minutes",
}
_LATEST_FIELDS = {"weight_kg", "vo2max"}
_MIN_FIELDS = {"heart_rate"}  # daily resting-HR proxy
# everything else (hrv_ms, resting_hr, mood) -> mean of the day


@dataclass
class _DayAgg:
    values: dict[str, list[tuple[datetime, float]]] = field(default_factory=lambda: defaultdict(list))


def _norm(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "").replace("-", "")


def _field_for(metric_name: str) -> str | None:
    key = _norm(metric_name)
    for field_name, aliases in _ALIASES.items():
        if key in aliases:
            return field_name
    return None


def _parse_dt(value: str) -> datetime | None:
    # HAE: "yyyy-MM-dd HH:mm:ss Z" e.g. "2026-06-14 07:00:00 +0100"
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


# Sleep-stage categories. HAE exports either a daily summary (one point with
# ``totalSleep`` / ``asleep`` hours) OR a stream of stage segments where
# ``value`` is the stage name and ``qty`` is that segment's hours. We count only
# genuine sleep stages and never the awake / in-bed segments.
_ASLEEP_STAGES = {"asleep", "core", "deep", "rem"}
_NONSLEEP_STAGES = {"awake", "inbed", "inbedawake", "inbedasleep"}


def _point_value(field_name: str, point: dict) -> float | None:
    """Extract the numeric value from a data point for a given field.

    Quantity metrics use ``qty``. Sleep is the awkward one — see ``_sleep_value``.
    State of Mind carries ``valence`` (or qty in [-1,1]).
    """
    if field_name == "sleep_minutes":
        return _sleep_value(point)
    if field_name == "mood":
        for k in ("valence", "qty", "value"):
            if k in point and point[k] is not None:
                return _to_float(point[k])
        return None
    if field_name == "mindful_minutes":
        # qty may be minutes already, or seconds — HAE uses minutes for this.
        v = _to_float(point.get("qty"))
        return v
    if field_name == "heart_rate":
        # Heart-rate points carry Min/Max/Avg per sample window. The lowest
        # reading of the day is our resting-HR proxy, so take Min when present.
        for k in ("Min", "min", "qty", "Avg", "avg"):
            if point.get(k) is not None:
                return _to_float(point[k])
        return None
    return _to_float(point.get("qty"))


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _sleep_value(point: dict) -> float | None:
    """Return the asleep minutes contributed by one sleep point.

    Two HAE shapes:
      * Daily summary — ``totalSleep``/``asleep`` hours; ``value`` may be absent
        or a number. We take the summary hours directly.
      * Stage segments — ``value`` is a stage name ("Core"/"Deep"/"REM"/"Awake"
        …) and ``qty`` is that segment's hours. We keep real sleep stages and
        drop awake / in-bed so segments sum to true asleep time.
    """
    # Explicit summary fields win.
    for k in ("totalSleep", "asleep"):
        if point.get(k) is not None:
            hours = _to_float(point[k])
            return hours * 60.0 if hours is not None else None

    stage = point.get("value")
    if isinstance(stage, str):
        key = stage.lower().replace(" ", "").replace("_", "")
        if key in _NONSLEEP_STAGES:
            return None  # awake / in-bed time is not sleep
        if key in _ASLEEP_STAGES or key == "":
            hours = _to_float(point.get("qty"))
            return hours * 60.0 if hours is not None else None
        # Unknown string stage: ignore rather than guess.
        return None

    # Numeric value or bare qty (older summary form): treat as hours.
    hours = _to_float(point.get("value") if point.get("value") is not None
                      else point.get("qty"))
    return hours * 60.0 if hours is not None else None


def _accumulate(payload: dict, days: dict[date, _DayAgg]) -> None:
    """Fold one HAE payload into a shared per-day aggregate.

    HAE splits exports by category (Health Metrics, State of Mind, …), so a
    single sync folder can hold several files. We accumulate them all into one
    aggregate keyed by day, then reduce once. State of Mind may arrive either
    inside ``data.metrics`` (name='state_of_mind') or as its own array under
    ``data.stateOfMind`` / ``data.state_of_mind`` — handle both.
    """
    data = payload.get("data") or {}

    # Standard metrics array.
    for metric in data.get("metrics") or []:
        field_name = _field_for(str(metric.get("name", "")))
        if field_name is None:
            continue
        for point in metric.get("data", []):
            _add_point(days, field_name, point)

    # State of Mind as a dedicated array (some HAE versions/categories).
    for key in ("stateOfMind", "state_of_mind", "stateOfMindData"):
        for point in data.get(key) or []:
            _add_point(days, "mood", point)


def _add_point(days: dict[date, _DayAgg], field_name: str, point: dict) -> None:
    dt = _parse_dt(str(point.get("date", "") or point.get("start", "")))
    if dt is None:
        return
    val = _point_value(field_name, point)
    if val is None:
        return
    days[dt.astimezone().date()].values[field_name].append((dt, val))


def _rows_from_days(days: dict[date, _DayAgg]) -> list[dict]:
    rows = []
    for day in sorted(days):
        agg = days[day].values
        row = {"day": day.isoformat(), "source": "health_auto_export"}
        for field_name in _ALIASES:
            pts = agg.get(field_name)
            row[field_name] = _reduce(field_name, pts) if pts else None
        # Fallback: if the export has no dedicated resting-HR metric, use the
        # day's minimum heart rate as a proxy. The real metric always wins — we
        # tag provenance so a later merge never lets the proxy override it.
        hr_min = row.pop("heart_rate", None)
        row["resting_hr_is_proxy"] = False
        if row.get("resting_hr") is None and hr_min is not None:
            row["resting_hr"] = hr_min
            row["resting_hr_is_proxy"] = True
        rows.append(row)
    return rows


def parse_payload(payload: dict) -> list[dict]:
    """Parse a single HAE JSON payload into per-day health dicts."""
    days: dict[date, _DayAgg] = defaultdict(_DayAgg)
    _accumulate(payload, days)
    rows = _rows_from_days(days)
    log.info("Health Auto Export: parsed %d days", len(rows))
    return rows


def _reduce(field_name: str, pts: list[tuple[datetime, float]]) -> float:
    vals = [v for _, v in pts]
    if field_name in _SUM_FIELDS:
        out = sum(vals)
    elif field_name in _LATEST_FIELDS:
        out = sorted(pts, key=lambda x: x[0])[-1][1]
    elif field_name in _MIN_FIELDS:
        out = min(vals)
    else:
        out = sum(vals) / len(vals)
    # sensible rounding per field
    if field_name in ("distance_km", "hrv_ms"):
        return round(out, 1)
    if field_name == "mood":
        return round(out, 3)
    if field_name in (
        "sleep_minutes",
        "mindful_minutes",
        "resting_hr",
        "heart_rate",
        "steps",
        "active_energy_kcal",
        "exercise_minutes",
    ):
        return round(out)
    if field_name == "respiratory_rate":
        return round(out, 1)
    if field_name == "vo2max":
        return round(out, 1)
    if field_name == "weight_kg":
        return round(out, 1)
    return round(out, 2)


def parse_file(path: str | Path) -> list[dict]:
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return parse_payload(payload)


def _ensure_downloaded(path: Path) -> None:
    """Ask macOS to materialise an iCloud placeholder, if this file is one.

    Files synced via iCloud Drive can exist only as ``.icloud`` stubs until
    opened. ``brctl download`` (best-effort) pulls the real bytes down.
    """
    try:
        import subprocess

        subprocess.run(["brctl", "download", str(path)], capture_output=True, timeout=20)
    except Exception:
        pass


# HAE writes internal bookkeeping under these names — they carry no health data.
# When the user points ORION at the parent export tree (rather than one
# sub-folder), skip them so they don't crowd out real exports.
_SKIP_DIRS = {"automations"}
_SKIP_NAMES = {"manifest.json"}


def _is_bookkeeping(p: Path) -> bool:
    if p.name.lower() in _SKIP_NAMES:
        return True
    return any(part.lower() in _SKIP_DIRS for part in p.parts)


def recent_export_files(folder: str | Path, *, max_files: int = 200) -> list[Path]:
    """Return the most recently modified .json exports in ``folder`` (recursive).

    HAE writes a separate file per category (Health Metrics, State of Mind, …)
    and a new file each run, so we merge the newest files. The cap is generous
    because exports are small; it only guards against an unbounded tree. HAE's
    own ``Automations/`` bookkeeping and ``manifest.json`` are skipped.
    Also resolves iCloud placeholder stubs (``.icloud``) to their real files and
    triggers a download so a partially-synced folder still reads fully.
    """
    folder = Path(folder)
    if not folder.exists():
        return []

    # Resolve iCloud placeholder stubs: ".<name>.json.icloud" -> "<name>.json".
    resolved: dict[Path, float] = {}
    for p in folder.rglob("*"):
        if _is_bookkeeping(p):
            continue
        if p.suffix == ".json":
            resolved[p] = p.stat().st_mtime
        elif p.suffix == ".icloud" and p.name.endswith(".json.icloud"):
            real = p.with_name(p.name[1:-len(".icloud")])  # strip leading '.' + '.icloud'
            _ensure_downloaded(real)
            if real.exists():
                resolved[real] = real.stat().st_mtime
            else:
                resolved.setdefault(real, p.stat().st_mtime)

    candidates = sorted(resolved, key=lambda p: resolved[p], reverse=True)
    # Make sure the ones we'll actually read are materialised.
    for p in candidates[:max_files]:
        if not p.exists() or p.stat().st_size == 0:
            _ensure_downloaded(p)
    return [p for p in candidates[:max_files] if p.exists() and p.stat().st_size > 0]


def latest_export_file(folder: str | Path) -> Path | None:
    files = recent_export_files(folder, max_files=1)
    return files[0] if files else None


def parse_folder(folder: str | Path, *, max_files: int = 200) -> list[dict]:
    """Merge the newest exports in ``folder`` into one set of per-day rows.

    Files are read newest-first; each contributes whatever ORION metrics it
    holds, so split-category exports (e.g. Health Metrics + State of Mind)
    combine on the same day.
    """
    files = recent_export_files(folder, max_files=max_files)

    # Reduce EACH file to per-day rows on its own, then merge across files. The
    # same calendar day often appears in several files (a daily export AND a
    # weekly one). Reducing per file first means an 8h night is 8h in each, and
    # the cross-file merge takes one representative value per field — never the
    # sum of both, which previously inflated sleep / distance on overlap days.
    merged: dict[str, dict] = {}
    for path in files:
        try:
            with Path(path).open(encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("Skipping HAE file %s: %s", path, exc)
            continue
        for row in parse_payload(payload):
            _merge_day_row(merged, row)

    rows = [merged[day] for day in sorted(merged)]
    log.info("Health Auto Export: merged %d files into %d days", len(files), len(rows))
    return rows


def _merge_day_row(merged: dict[str, dict], row: dict) -> None:
    """Merge one file's per-day row into the cross-file accumulator.

    For each field, an existing value is only replaced by a non-None incoming
    value. When both files have a value for the same day+field we keep the
    LARGER magnitude for cumulative fields (sleep/distance/mindful) — a fuller
    export wins — and otherwise keep the existing one. This is idempotent: the
    same file merged twice yields the same result.
    """
    day = row["day"]
    cur = merged.get(day)
    if cur is None:
        merged[day] = dict(row)
        return
    for field_name in _ALIASES:
        incoming = row.get(field_name)
        if incoming is None:
            continue
        existing = cur.get(field_name)
        if existing is None:
            cur[field_name] = incoming
        elif field_name in _SUM_FIELDS:
            # Fuller export wins (e.g. a complete night vs a partial one).
            cur[field_name] = max(existing, incoming)
        elif field_name == "resting_hr":
            # The real Apple "Resting Heart Rate" metric ALWAYS beats the
            # heart-rate-min proxy, regardless of magnitude — the proxy reads
            # artificially low (deepest-sleep window) and must never override a
            # genuine resting value. Between two proxies, the lower min wins;
            # between two real readings, keep the lower (HAE reports one/day).
            cur_proxy = cur.get("resting_hr_is_proxy", False)
            inc_proxy = row.get("resting_hr_is_proxy", False)
            if cur_proxy and not inc_proxy:
                cur[field_name] = incoming
                cur["resting_hr_is_proxy"] = False
            elif inc_proxy and not cur_proxy:
                pass  # keep the existing real value
            else:
                cur[field_name] = min(existing, incoming)
        # else (other averages / latest): keep the first non-None we saw.
