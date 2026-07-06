"""Shared JSON envelopes for ORION CloudKit records.

The Swift helper and iOS app intentionally receive plain JSON values. The
CloudKit record itself stores a small stable metadata shell plus one JSON
``payload`` field so schema additions can evolve without migrating every client
in lockstep.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from app.db.models import (
    CalendarEvent,
    CaptureInboxItem,
    FitnessSession,
    Insight,
    StoicEntry,
    Task,
    Workout,
)


SYNC_SCHEMA_VERSION = 1


def build_record_envelope(
    *,
    record_type: str,
    record_name: str,
    source_device_id: str,
    payload: dict[str, Any],
    updated_at: datetime,
    deleted_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the canonical CloudKit-bound JSON envelope for one record."""
    return _json_value(
        {
            "schemaVersion": SYNC_SCHEMA_VERSION,
            "recordType": record_type,
            "recordName": record_name,
            "sourceDeviceID": source_device_id,
            "updatedAt": updated_at,
            "deletedAt": deleted_at,
            "payload": payload,
        }
    )


def payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash used to avoid needlessly queueing unchanged payloads."""
    encoded = json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def payload_for_row(row: object) -> dict[str, Any]:
    if isinstance(row, Task):
        return {
            "localID": row.id,
            "externalID": row.ext_id,
            "title": row.title,
            "area": row.area,
            "category": row.category,
            "priority": row.priority,
            "status": row.status,
            "notes": row.notes,
            "dueDate": row.due_date,
            "recurrence": row.recurrence,
            "sortOrder": row.sort_order,
            "remoteCreatedAt": row.remote_created_at,
            "completedAt": row.completed_at,
            "createdAt": row.created_at,
            "syncedAt": row.synced_at,
        }
    if isinstance(row, CalendarEvent):
        return {
            "localID": row.id,
            "externalID": row.ext_id,
            "title": row.title,
            "location": row.location,
            "calendarName": row.calendar_name,
            "startsAt": row.starts_at,
            "endsAt": row.ends_at,
            "allDay": bool(row.all_day),
            "notes": row.notes,
            "syncedAt": row.synced_at,
            "extra": row.extra or {},
        }
    if isinstance(row, CaptureInboxItem):
        return {
            "localID": row.id,
            "text": row.text,
            "source": row.source,
            "status": row.status,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
            "processedAt": row.processed_at,
            "extra": row.extra or {},
        }
    if isinstance(row, StoicEntry):
        return {
            "localID": row.id,
            "day": row.day,
            "virtueFocus": row.virtue_focus,
            "controlPercent": row.control_pct,
            "reflected": bool(row.reflected),
            "servedOthers": bool(row.served_others),
            "facedHardThing": bool(row.faced_hard_thing),
            "restrainedImpulse": bool(row.restrained_impulse),
            "studyMinutes": row.study_minutes,
            "reflection": row.reflection,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }
    if isinstance(row, FitnessSession):
        return {
            "localID": row.id,
            "day": row.day,
            "sessionType": row.session_type,
            "label": row.label,
            "color": row.color,
            "notes": row.notes,
            "completed": bool(row.completed),
            "sortOrder": row.sort_order,
            "createdAt": row.created_at,
        }
    if isinstance(row, Workout):
        return {
            "localID": row.id,
            "source": row.source,
            "sourceID": row.source_id,
            "title": row.title,
            "sportType": row.sport_type,
            "startedAt": row.started_at,
            "endedAt": row.ended_at,
            "durationSeconds": row.duration_seconds,
            "movingTimeSeconds": row.moving_time_seconds,
            "distanceMeters": row.distance_meters,
            "averageHeartRate": row.average_heart_rate,
            "maxHeartRate": row.max_heart_rate,
            "elevationGainMeters": row.elevation_gain_meters,
            "splits": row.splits or [],
            "extra": row.extra or {},
            "createdAt": row.created_at,
        }
    if isinstance(row, Insight):
        return {
            "localID": row.id,
            "domain": row.domain.value,
            "severity": row.severity.value,
            "title": row.title,
            "body": row.body,
            "ruleKey": row.rule_key,
            "metricValue": row.metric_value,
            "createdAt": row.created_at,
        }
    raise TypeError(f"Unsupported sync payload row: {type(row)!r}")


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, str):
        return _json_value(value.value)
    return value
