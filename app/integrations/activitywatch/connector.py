"""ActivityWatch connector — REAL local source.

ActivityWatch runs a local REST server (default http://localhost:5600) exposing
window and AFK buckets. This is fully local-first: no cloud, no OAuth, no token.

This connector queries that local API for the last N days and derives, per day:
  * active_minutes   — total non-AFK time
  * deep_work_minutes — time spent in *sustained* non-AFK focus blocks
                        (continuous not-AFK stretches >= DEEP_WORK_MIN_BLOCK)

If ActivityWatch is not running / not reachable, the connector reports itself as
unavailable and (in development) falls back to mock data so the demo still works
— but ``last_real`` records whether the most recent fetch was genuinely live.

API reference: https://docs.activitywatch.net/en/latest/api/rest.html
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import URLError
from urllib.request import urlopen
import json

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ActivityMetricDaily, Domain
from app.ingestion.base import Connector

log = get_logger(__name__)

AW_BASE = "http://localhost:5600/api/0"
AW_TIMEOUT = 2.0
LOOKBACK_DAYS = 30
# A continuous non-AFK stretch must reach this many minutes to count as "deep
# work" (sustained focus), rather than scattered activity.
DEEP_WORK_MIN_BLOCK = 25
# Gaps shorter than this between non-AFK events don't break a focus block.
FOCUS_GAP_TOLERANCE_S = 120


def _get_json(url: str):
    with urlopen(url, timeout=AW_TIMEOUT) as resp:  # noqa: S310 (localhost only)
        return json.loads(resp.read().decode("utf-8"))


class ActivityWatchConnector(Connector):
    key = "activitywatch"
    name = "ActivityWatch"
    domain = Domain.productivity
    is_mock = True  # flips to False once a live fetch succeeds

    def __init__(self) -> None:
        self._available: bool | None = None
        self._afk_bucket: str | None = None

    # --- availability ------------------------------------------------------ #
    def connect(self) -> bool:
        """Probe the local AW server and locate the AFK bucket."""
        try:
            buckets = _get_json(f"{AW_BASE}/buckets/")
        except (URLError, OSError, ValueError, TimeoutError):
            self._available = False
            return False
        afk = [b for b in buckets if "afk" in b.lower()]
        self._afk_bucket = afk[0] if afk else None
        self._available = self._afk_bucket is not None
        self.is_mock = not self._available
        return self._available

    @property
    def available(self) -> bool:
        if self._available is None:
            self.connect()
        return bool(self._available)

    # --- fetch ------------------------------------------------------------- #
    def fetch_raw_data(self) -> list[dict]:
        if self.available:
            try:
                rows = self._fetch_live()
                if rows:
                    self.is_mock = False
                    log.info("ActivityWatch: fetched %d live days", len(rows))
                    return rows
            except (URLError, OSError, ValueError, TimeoutError) as exc:
                log.warning("ActivityWatch live fetch failed: %s", exc)
        # Fallback: mock (development only).
        self.is_mock = True
        if get_settings().is_production:
            return []
        return self._fetch_mock()

    def _fetch_live(self) -> list[dict]:
        """Query AFK events and aggregate per-day active + deep-work minutes."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=LOOKBACK_DAYS)
        url = (
            f"{AW_BASE}/buckets/{self._afk_bucket}/events"
            f"?start={start.isoformat()}&end={end.isoformat()}&limit=-1"
        )
        events = _get_json(url)

        # Keep only not-afk events, sorted by start time.
        active = []
        for e in events:
            if e.get("data", {}).get("status") != "not-afk":
                continue
            ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            dur = float(e.get("duration", 0.0))
            active.append((ts, dur))
        active.sort(key=lambda x: x[0])

        per_day_active: dict[date, float] = defaultdict(float)
        per_day_deep: dict[date, float] = defaultdict(float)

        # Active minutes: sum of all not-afk durations, attributed to local day.
        for ts, dur in active:
            per_day_active[ts.astimezone().date()] += dur

        # Deep work: merge near-contiguous not-afk events into focus blocks; a
        # block counts only if it is long enough.
        block_start: datetime | None = None
        block_end: datetime | None = None
        for ts, dur in active:
            ev_end = ts + timedelta(seconds=dur)
            if block_start is None:
                block_start, block_end = ts, ev_end
                continue
            if (ts - block_end).total_seconds() <= FOCUS_GAP_TOLERANCE_S:
                block_end = max(block_end, ev_end)
            else:
                self._commit_block(block_start, block_end, per_day_deep)
                block_start, block_end = ts, ev_end
        self._commit_block(block_start, block_end, per_day_deep)

        out = []
        for day in sorted(per_day_active):
            out.append({
                "day": day.isoformat(),
                "active_minutes": round(per_day_active[day] / 60.0),
                "deep_work_minutes": round(per_day_deep.get(day, 0.0) / 60.0),
                "steps": None,  # AW has no step data
                "source": "activitywatch_live",
            })
        return out

    @staticmethod
    def _commit_block(start, end, per_day_deep) -> None:
        if start is None or end is None:
            return
        length_min = (end - start).total_seconds() / 60.0
        if length_min >= DEEP_WORK_MIN_BLOCK:
            per_day_deep[start.astimezone().date()] += length_min * 60.0

    # --- persistence: upsert ActivityMetricDaily ------------------------- #
    def store_normalised_data(self, session, user_id, source_id, records) -> int:
        """Upsert active/deep-work minutes per day without clobbering other
        metrics (e.g. training_load owned by the Football Manager connector)."""
        written = 0
        for r in records:
            day = date.fromisoformat(r["day"])
            row = session.scalars(
                select(ActivityMetricDaily).where(
                    ActivityMetricDaily.user_id == user_id,
                    ActivityMetricDaily.day == day,
                )
            ).first()
            if row is None:
                row = ActivityMetricDaily(user_id=user_id, day=day)
                session.add(row)
            if r.get("active_minutes") is not None:
                row.active_minutes = r["active_minutes"]
            if r.get("deep_work_minutes") is not None:
                row.deep_work_minutes = r["deep_work_minutes"]
            if r.get("steps") is not None:
                row.steps = r["steps"]
            written += 1
        session.flush()
        return written

    def _fetch_mock(self) -> list[dict]:
        today = date.today()
        out = []
        for i in range(LOOKBACK_DAYS):
            day = today - timedelta(days=i)
            weekday = day.weekday() < 5
            out.append({
                "day": day.isoformat(),
                "deep_work_minutes": random.randint(120, 300) if weekday
                else random.randint(0, 90),
                "active_minutes": random.randint(20, 90),
                "steps": random.randint(3000, 12000),
                "source": "activitywatch_mock",
            })
        return out


# Backwards-compatibility: some callers used a midnight-bounded day helper.
def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)
