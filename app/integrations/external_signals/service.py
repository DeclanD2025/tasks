"""Fetch-and-cache layer for free public APIs (Open-Meteo, Nager.Date, Frankfurter).

Contract: every ``get_*`` function returns a :class:`Signal` and never raises.
Fresh cache hits skip the network entirely; on upstream failure the last good
payload is served marked ``stale``; with no cache at all the signal reports its
error and the UI shows a quiet "signal unavailable" state.

All calls run with a hard 6-second timeout so a dead upstream cannot make an
ORION page hang.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import ExternalSignalCache

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(6.0, connect=4.0)
_HEADERS = {"User-Agent": "ORION-personal/1.0 (private personal dashboard)"}


@dataclass(frozen=True)
class Signal:
    kind: str
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    stale: bool = False
    error: str = ""

    @property
    def age_label(self) -> str:
        if self.fetched_at is None:
            return "no data"
        delta = datetime.now(timezone.utc) - self.fetched_at.replace(tzinfo=timezone.utc)
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        return f"{hours}h ago" if hours < 48 else f"{hours // 24}d ago"


def _cache_read(kind: str, key: str) -> ExternalSignalCache | None:
    with session_scope() as s:
        row = s.scalars(
            select(ExternalSignalCache).where(
                ExternalSignalCache.kind == kind, ExternalSignalCache.key == key
            )
        ).first()
        if row is not None:
            s.expunge(row)
    return row


def _cache_write(kind: str, key: str, payload: dict, ttl_minutes: int) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope() as s:
        row = s.scalars(
            select(ExternalSignalCache).where(
                ExternalSignalCache.kind == kind, ExternalSignalCache.key == key
            )
        ).first()
        if row is None:
            row = ExternalSignalCache(kind=kind, key=key)
            s.add(row)
        row.payload = payload
        row.ok = True
        row.error = ""
        row.fetched_at = now
        row.expires_at = now + timedelta(minutes=ttl_minutes)


def _fetch(kind: str, key: str, url: str, params: dict, ttl_minutes: int) -> Signal:
    """Cache-first fetch. Fresh row -> no network. Failure -> stale row or error."""
    cached = _cache_read(kind, key)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cached is not None and cached.ok and cached.expires_at and cached.expires_at > now:
        return Signal(kind, True, cached.payload, cached.fetched_at)
    if os.environ.get("ORION_SIGNALS_OFFLINE") == "1":
        # Test/CI guard: never touch the network; serve stale or report quiet.
        if cached is not None and cached.payload:
            return Signal(kind, True, cached.payload, cached.fetched_at, stale=True)
        return Signal(kind, False, {}, None, error="signals offline")
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, list):  # normalise list bodies (Nager.Date)
            payload = {"items": payload}
        _cache_write(kind, key, payload, ttl_minutes)
        return Signal(kind, True, payload, now)
    except Exception as exc:  # noqa: BLE001 — by contract this layer never raises
        log.warning("Signal %s fetch failed: %s", kind, exc)
        if cached is not None and cached.payload:
            return Signal(kind, True, cached.payload, cached.fetched_at, stale=True,
                          error=str(exc)[:200])
        return Signal(kind, False, {}, None, error=str(exc)[:200])


# --------------------------------------------------------------------- weather
# WMO weather interpretation codes -> (label, glyph). Glyphs stay ASCII-adjacent
# and quiet — this is telemetry, not a cartoon sun.
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "○"), 1: ("Mostly clear", "○"), 2: ("Partly cloudy", "◔"),
    3: ("Overcast", "●"), 45: ("Fog", "≡"), 48: ("Freezing fog", "≡"),
    51: ("Light drizzle", "﹅"), 53: ("Drizzle", "﹅"), 55: ("Heavy drizzle", "﹅"),
    61: ("Light rain", "﹅"), 63: ("Rain", "﹅"), 65: ("Heavy rain", "﹅"),
    66: ("Freezing rain", "﹅"), 67: ("Freezing rain", "﹅"),
    71: ("Light snow", "❋"), 73: ("Snow", "❋"), 75: ("Heavy snow", "❋"),
    77: ("Snow grains", "❋"), 80: ("Showers", "﹅"), 81: ("Showers", "﹅"),
    82: ("Violent showers", "﹅"), 85: ("Snow showers", "❋"), 86: ("Snow showers", "❋"),
    95: ("Thunderstorm", "⌁"), 96: ("Thunderstorm, hail", "⌁"), 99: ("Thunderstorm, hail", "⌁"),
}


def describe_wmo(code: int | None) -> tuple[str, str]:
    if code is None:
        return ("—", "")
    return WMO_CODES.get(int(code), ("Mixed", "◔"))


def get_weather(lat: float, lon: float) -> Signal:
    key = f"{lat:.2f},{lon:.2f}"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,"
                   "wind_speed_10m,precipitation,relative_humidity_2m",
        "hourly": "temperature_2m,precipitation_probability,weather_code,"
                  "wind_speed_10m,uv_index",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "weather_code,sunrise,sunset,uv_index_max",
        "forecast_days": 3,
        "timezone": "auto",
        "wind_speed_unit": "mph",
    }
    return _fetch("weather", key, "https://api.open-meteo.com/v1/forecast", params, 30)


def get_air_quality(lat: float, lon: float) -> Signal:
    key = f"{lat:.2f},{lon:.2f}"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "european_aqi,pm2_5,pm10,ozone",
        "hourly": "grass_pollen,birch_pollen,alder_pollen,ragweed_pollen",
        "forecast_days": 1,
        "timezone": "auto",
    }
    return _fetch(
        "air", key, "https://air-quality-api.open-meteo.com/v1/air-quality", params, 60
    )


def get_holidays(country: str = "GB") -> Signal:
    country = (country or "GB").upper()[:2]
    return _fetch(
        "holidays", country,
        f"https://date.nager.at/api/v3/NextPublicHolidays/{country}", {}, 24 * 60,
    )


def get_fx_rates(base: str = "GBP") -> Signal:
    base = (base or "GBP").upper()[:3]
    params = {"base": base, "symbols": "EUR,USD,JPY,AUD,CAD,CHF,THB,TRY,PLN,SEK"}
    return _fetch("fx", base, "https://api.frankfurter.dev/v1/latest", params, 12 * 60)


def aqi_band(value: float | None) -> str:
    """European AQI bands in plain language (EEA scale)."""
    if value is None:
        return "unknown"
    if value <= 20:
        return "good"
    if value <= 40:
        return "fair"
    if value <= 60:
        return "moderate"
    if value <= 80:
        return "poor"
    return "very poor"


def signal_status() -> list[dict[str, Any]]:
    """Snapshot of every cached signal for the Data tab's API board."""
    with session_scope() as s:
        rows = s.scalars(select(ExternalSignalCache)).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        out = []
        for row in rows:
            out.append({
                "kind": row.kind,
                "key": row.key,
                "ok": bool(row.ok),
                "fresh": bool(row.expires_at and row.expires_at > now),
                "fetched_at": row.fetched_at,
                "error": row.error,
            })
    return sorted(out, key=lambda r: r["kind"])
