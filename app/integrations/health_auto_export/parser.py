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
    "sleep_minutes": {"sleepanalysis", "sleep"},
    "mindful_minutes": {"mindfulminutes", "mindfulness", "mindfulsession"},
    "mood": {"stateofmind", "state_of_mind", "mood"},
}

# Fields where we SUM the day's points (durations / distances), vs average,
# vs take the latest reading.
_SUM_FIELDS = {"sleep_minutes", "mindful_minutes", "distance_km"}
_LATEST_FIELDS = {"weight_kg", "vo2max"}
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


def _point_value(field_name: str, point: dict) -> float | None:
    """Extract the numeric value from a data point for a given field.

    Quantity metrics use ``qty``. Sleep points may carry ``totalSleep`` /
    ``asleep`` (hours) or a ``qty``. State of Mind carries ``valence`` (or qty in
    [-1,1]).
    """
    if field_name == "sleep_minutes":
        # Prefer an explicit asleep duration (hours) if present.
        for k in ("totalSleep", "asleep", "value", "qty"):
            if k in point and point[k] is not None:
                hours = _to_float(point[k])
                return hours * 60.0 if hours is not None else None
        return None
    if field_name == "mood":
        for k in ("valence", "qty", "value"):
            if k in point and point[k] is not None:
                return _to_float(point[k])
        return None
    if field_name == "mindful_minutes":
        # qty may be minutes already, or seconds — HAE uses minutes for this.
        v = _to_float(point.get("qty"))
        return v
    return _to_float(point.get("qty"))


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


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
    else:
        out = sum(vals) / len(vals)
    # sensible rounding per field
    if field_name in ("distance_km", "hrv_ms"):
        return round(out, 1)
    if field_name == "mood":
        return round(out, 3)
    if field_name in ("sleep_minutes", "mindful_minutes", "resting_hr"):
        return round(out)
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


def recent_export_files(folder: str | Path, *, max_files: int = 12) -> list[Path]:
    """Return the most recently modified .json exports in ``folder`` (recursive).

    HAE writes a separate file per category (Health Metrics, State of Mind, …)
    and a new file each run, so we take the newest handful and merge them.
    Also resolves iCloud placeholder stubs (``.icloud``) to their real files and
    triggers a download so a partially-synced folder still reads fully.
    """
    folder = Path(folder)
    if not folder.exists():
        return []

    # Resolve iCloud placeholder stubs: ".<name>.json.icloud" -> "<name>.json".
    resolved: dict[Path, float] = {}
    for p in folder.rglob("*"):
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


def parse_folder(folder: str | Path, *, max_files: int = 12) -> list[dict]:
    """Merge the newest exports in ``folder`` into one set of per-day rows.

    Files are read newest-first; each contributes whatever ORION metrics it
    holds, so split-category exports (e.g. Health Metrics + State of Mind)
    combine on the same day.
    """
    days: dict[date, _DayAgg] = defaultdict(_DayAgg)
    files = recent_export_files(folder, max_files=max_files)
    for path in files:
        try:
            with Path(path).open(encoding="utf-8") as fh:
                payload = json.load(fh)
            _accumulate(payload, days)
        except (OSError, ValueError) as exc:
            log.warning("Skipping HAE file %s: %s", path, exc)
    rows = _rows_from_days(days)
    log.info("Health Auto Export: merged %d files into %d days", len(files), len(rows))
    return rows
