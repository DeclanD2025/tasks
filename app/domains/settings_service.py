"""Operator settings: typed targets and preferences with honest defaults.

All reads go through :func:`get_settings_snapshot` (one query) or :func:`get_value`.
Values are stored as ``{"v": payload}`` JSON so booleans/numbers/strings survive
round-trips untouched. Unknown keys are rejected — the registry below is the
single source of truth for what a setting means, its default, and how the UI
should render it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import UserSetting


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    default: Any
    kind: str  # "number" | "text" | "choice" | "bool"
    unit: str = ""
    group: str = "targets"
    help: str = ""
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None


# Registry: group -> rendered section on the Settings page (in this order).
SETTING_SPECS: tuple[SettingSpec, ...] = (
    # -- sleep / recovery
    SettingSpec(
        "sleep_target_hours", "Sleep target", 8.0, "number", "h", "recovery",
        "A planning anchor for wind-down prompts. Sleep debt itself is measured "
        "against your own recorded need, not this number.",
        min=5, max=12,
    ),
    # -- training
    SettingSpec(
        "run_weekly_target_km", "Weekly running target", None, "number", "km", "training",
        "Leave blank to let ORION adapt the target from your recent 4 weeks "
        "(capped at +10% per week).", min=0, max=200,
    ),
    SettingSpec(
        "run_goal", "Running goal", "5k base progression", "text", "", "training",
        "The outcome the weekly target protects. Shown on the training page.",
    ),
    SettingSpec(
        "strength_weekly_target", "Strength sessions per week", 3, "number", "", "training",
        "", min=0, max=14,
    ),
    # -- body
    SettingSpec(
        "weight_goal_kg", "Weight goal", None, "number", "kg", "body",
        "Optional. Weight is reported as a trend, not a judgement.", min=30, max=250,
    ),
    # -- nutrition
    SettingSpec("calorie_target", "Calorie target", 2400, "number", "kcal", "nutrition",
                "", min=1000, max=6000),
    SettingSpec("protein_target_g", "Protein target", 120, "number", "g", "nutrition",
                "", min=20, max=400),
    SettingSpec("fibre_target_g", "Fibre target", 30, "number", "g", "nutrition",
                "UK guidance for adults is about 30 g per day.", min=5, max=100),
    SettingSpec("water_target_ml", "Hydration target", 2000, "number", "ml", "nutrition",
                "", min=500, max=6000),
    # -- mind
    SettingSpec(
        "mindfulness_weekly_minutes", "Mindfulness target", 21, "number", "min/week", "mind",
        "Three minutes a day beats a heroic hour once a month.", min=0, max=600,
    ),
    # -- signals / location
    SettingSpec(
        "location_name", "Location", "Motherwell", "text", "", "signals",
        "Used for weather, daylight and air quality. Name is display-only.",
    ),
    SettingSpec("location_lat", "Latitude", 55.789, "number", "°", "signals", "",
                min=-90, max=90),
    SettingSpec("location_lon", "Longitude", -3.992, "number", "°", "signals", "",
                min=-180, max=180),
    SettingSpec(
        "holiday_country", "Public holiday region", "GB", "text", "", "signals",
        "ISO country code for Nager.Date public holidays.",
    ),
    SettingSpec(
        "home_currency", "Home currency", "GBP", "text", "", "signals",
        "Base currency for the travel converter on Money.",
    ),
    # -- appearance
    SettingSpec(
        "theme_intensity", "Theme intensity", "cinematic", "choice", "", "appearance",
        "How much atmosphere the interface carries.",
        choices=("subtle", "cinematic", "observatory"),
    ),
    # -- integrations (all free; commercial adapters stay off by default)
    SettingSpec(
        "off_enabled", "Open Food Facts lookups", True, "bool", "", "integrations",
        "Barcode and food search via the free Open Food Facts database.",
    ),
    SettingSpec(
        "usda_api_key", "USDA FoodData Central key", "", "text", "", "integrations",
        "Optional adapter, off unless a (free) key is entered. Never required.",
    ),
)

_SPEC_BY_KEY = {spec.key: spec for spec in SETTING_SPECS}
HAE_INGEST_TOKEN_HASH_KEY = "hae_ingest_token_sha256"

GROUP_LABELS = {
    "recovery": "Sleep & recovery",
    "training": "Training",
    "body": "Body",
    "nutrition": "Nutrition",
    "mind": "Mind",
    "signals": "Signals & location",
    "appearance": "Appearance",
    "integrations": "Integrations",
}


def spec_for(key: str) -> SettingSpec:
    return _SPEC_BY_KEY[key]


def get_settings_snapshot(user_id: int) -> dict[str, Any]:
    """Every setting resolved to its effective value, one query."""
    values = {spec.key: spec.default for spec in SETTING_SPECS}
    with session_scope() as s:
        rows = s.scalars(select(UserSetting).where(UserSetting.user_id == user_id)).all()
        for row in rows:
            if row.key in values and isinstance(row.value, dict) and "v" in row.value:
                values[row.key] = row.value["v"]
    return values


def get_value(user_id: int, key: str) -> Any:
    spec = _SPEC_BY_KEY[key]
    with session_scope() as s:
        row = s.scalars(
            select(UserSetting).where(UserSetting.user_id == user_id, UserSetting.key == key)
        ).first()
        if row is not None and isinstance(row.value, dict) and "v" in row.value:
            return row.value["v"]
    return spec.default


def _coerce(spec: SettingSpec, raw: str) -> Any:
    """Parse a form string into the spec's native type; None clears to default."""
    raw = (raw or "").strip()
    if spec.kind == "bool":
        return raw in {"1", "true", "on", "yes"}
    if raw == "":
        return None
    if spec.kind == "number":
        value = float(raw)
        if spec.min is not None:
            value = max(spec.min, value)
        if spec.max is not None:
            value = min(spec.max, value)
        return int(value) if value == int(value) else value
    if spec.kind == "choice":
        return raw if raw in spec.choices else spec.default
    return raw[:300]


def set_values(user_id: int, form: dict[str, str]) -> list[str]:
    """Apply submitted settings; returns the keys that changed.

    A blank value resets that setting to its default (row deleted) so the
    registry default can evolve without stale copies in the database.
    """
    changed: list[str] = []
    with session_scope() as s:
        existing = {
            row.key: row
            for row in s.scalars(select(UserSetting).where(UserSetting.user_id == user_id))
        }
        for key, raw in form.items():
            spec = _SPEC_BY_KEY.get(key)
            if spec is None:
                continue
            try:
                value = _coerce(spec, raw)
            except ValueError:
                continue
            row = existing.get(key)
            if value is None or value == spec.default:
                if row is not None:
                    s.delete(row)
                    changed.append(key)
                continue
            if row is None:
                s.add(UserSetting(user_id=user_id, key=key, value={"v": value}))
                changed.append(key)
            elif row.value.get("v") != value:
                row.value = {"v": value}
                changed.append(key)
    return changed


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_hae_ingest_token(user_id: int) -> str:
    """Create a HAE REST ingest token and store only its hash.

    `ORION_INGEST_TOKEN` remains the deployment-secret path. This database-backed
    path lets the web app enable HAE from the authenticated Data Vault page when
    a host has already been deployed without that secret.
    """
    token = secrets.token_urlsafe(32)
    value = {"sha256": _token_hash(token), "created_at": datetime.now().isoformat()}
    with session_scope() as s:
        row = s.scalars(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == HAE_INGEST_TOKEN_HASH_KEY,
            )
        ).first()
        if row is None:
            s.add(UserSetting(user_id=user_id, key=HAE_INGEST_TOKEN_HASH_KEY, value=value))
        else:
            row.value = value
    return token


def hae_ingest_token_configured(user_id: int) -> bool:
    with session_scope() as s:
        row = s.scalars(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == HAE_INGEST_TOKEN_HASH_KEY,
            )
        ).first()
        return bool(row and isinstance(row.value, dict) and row.value.get("sha256"))


def verify_hae_ingest_token(user_id: int, supplied: str) -> bool:
    if not supplied:
        return False
    supplied_hash = _token_hash(supplied)
    with session_scope() as s:
        row = s.scalars(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == HAE_INGEST_TOKEN_HASH_KEY,
            )
        ).first()
        expected = row.value.get("sha256") if row and isinstance(row.value, dict) else ""
    return bool(expected) and hmac.compare_digest(supplied_hash, expected)
