"""Read-only mobile snapshot contract.

The desktop app remains the source of truth for now. This module gathers a small
JSON-serialisable payload that an iOS companion can import from Files, iCloud
Drive, or a later API endpoint.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from app import services
from app.db.database import session_scope
from app.db.models import User
from app.ingestion.registry import iter_connectors

SCHEMA_VERSION = 1


def build_mobile_snapshot(
    user_id: int | None = None,
    *,
    days: int = 30,
    task_limit: int = 20,
    calendar_limit: int = 20,
    insight_limit: int = 12,
) -> dict[str, Any]:
    """Return the compact ORION payload consumed by the iOS companion.

    The contract favours strings, numbers, booleans, lists, and dicts so Swift's
    ``Codable`` can decode it with minimal custom glue. Datetimes and dates are
    ISO-8601 strings.
    """
    uid = user_id or services.get_default_user_id()
    if uid is None:
        raise RuntimeError("No ORION user exists. Run the app once or seed the database first.")

    health = services.health_frame(uid, days=days)
    activity = services.activity_frame(uid, days=days)
    net_worth = services.net_worth_series(uid, days=days)

    tasks = services.get_tasks(uid, include_done=False)[:task_limit]
    calendar = services.calendar_events(uid, days_back=1, days_forward=30)[:calendar_limit]
    insights = services.latest_insights(uid, limit=insight_limit)
    overview = services.overview_metrics(uid)

    return _json_value(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc),
            "user": _user(uid),
            "overview": {
                "metrics": [
                    {
                        "label": metric.label,
                        "value": metric.value,
                        "delta": metric.delta,
                        "trend": metric.trend,
                        "tone": metric.tone,
                        "series": metric.series or [],
                    }
                    for metric in overview
                ],
                "primary_insight": insights[0] if insights else None,
            },
            "finance": {
                "net_worth": _series_points(net_worth, x="day", y="value"),
                "accounts": services.account_snapshot_latest(uid),
                "spending_by_category": services.spending_by_category(uid, days=days),
            },
            "health": {
                "latest": _latest_row(health),
                "sleep": _series_points(health, x="day", y="sleep_minutes"),
                "hrv": _series_points(health, x="day", y="hrv_ms"),
                "resting_hr": _series_points(health, x="day", y="resting_hr"),
            },
            "activity": {
                "latest": _latest_row(activity),
                "steps": _series_points(activity, x="day", y="steps"),
                "training_load": _series_points(activity, x="day", y="training_load"),
                "deep_work_minutes": _series_points(activity, x="day", y="deep_work_minutes"),
            },
            "tasks": {
                "counts": services.task_counts(uid),
                "open": tasks,
            },
            "calendar": {
                "upcoming": calendar,
            },
            "insights": insights,
            "sources": _source_statuses(),
        }
    )


def write_mobile_snapshot(
    path: str | Path,
    *,
    user_id: int | None = None,
    days: int = 30,
    pretty: bool = True,
) -> Path:
    """Write the mobile snapshot JSON and return the resolved output path."""
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_mobile_snapshot(user_id=user_id, days=days)
    output.write_text(
        json.dumps(payload, indent=2 if pretty else None, sort_keys=pretty) + "\n",
        encoding="utf-8",
    )
    return output


def _user(user_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.scalars(select(User).where(User.id == user_id)).first()
        if row is None:
            return {"id": user_id, "display_name": "Operator", "email": ""}
        return {"id": row.id, "display_name": row.display_name, "email": row.email}


def _source_statuses() -> list[dict[str, Any]]:
    statuses = []
    for connector in iter_connectors():
        statuses.append(
            {
                "key": connector.key,
                "name": connector.name,
                "domain": connector.domain.value,
                "status": connector.status.value,
                "is_mock": bool(connector.is_mock),
            }
        )
    return statuses


def _latest_row(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    return frame.sort_values(frame.columns[0]).tail(1).to_dict("records")[0]


def _series_points(frame: pd.DataFrame, *, x: str, y: str) -> list[dict[str, Any]]:
    if frame.empty or x not in frame.columns or y not in frame.columns:
        return []
    points = []
    for row in frame[[x, y]].dropna().to_dict("records"):
        points.append({"x": row[x], "y": row[y]})
    return points


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
