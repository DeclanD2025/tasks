"""Apply pulled CloudKit records to the desktop SQLite store."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import session_scope
from app.db.models import (
    CaptureInboxItem,
    StoicEntry,
    SyncDevice,
    SyncEntity,
    Task,
    User,
    utcnow,
)
from app.sync.payloads import SYNC_SCHEMA_VERSION, payload_hash


SUPPORTED_INCOMING_RECORD_TYPES = {"Task", "CaptureInboxItem", "DailyCheckIn"}


def apply_incoming_records(
    records: list[dict[str, Any]],
    *,
    user_id: int | None = None,
) -> dict[str, int]:
    """Apply records pulled from CloudKit into the local desktop database.

    The function accepts either raw ORION envelopes or helper records containing
    an envelope under ``payload``. It is intentionally conservative: unsupported
    record types are ignored, and dirty local rows are treated as conflicts
    rather than overwritten.
    """
    result = {"applied": 0, "deleted": 0, "conflicts": 0, "ignored": 0}
    with session_scope() as session:
        uid = user_id or _default_user_id(session)
        if uid is None:
            result["ignored"] += len(records)
            return result
        local_device_id = _local_device_id(session)
        for record in records:
            envelope = _normalise_envelope(record)
            record_type = envelope.get("recordType")
            record_name = envelope.get("recordName")
            if (
                not isinstance(record_type, str)
                or not isinstance(record_name, str)
                or record_type not in SUPPORTED_INCOMING_RECORD_TYPES
            ):
                result["ignored"] += 1
                continue
            if envelope.get("sourceDeviceID") == local_device_id and _entity_by_record_name(
                session, record_name
            ):
                result["ignored"] += 1
                continue

            deleted_at = _parse_datetime(envelope.get("deletedAt"))
            if deleted_at is not None:
                result["deleted"] += _apply_tombstone(session, envelope)
                continue

            applied = _apply_upsert(session, uid, envelope)
            result[applied] += 1
    return result


def _apply_upsert(session: Session, user_id: int, envelope: dict[str, Any]) -> str:
    record_type = str(envelope["recordType"])
    record_name = str(envelope["recordName"])
    payload = envelope.get("payload") or {}
    incoming_updated_at = _parse_datetime(envelope.get("updatedAt")) or utcnow()

    entity = _entity_by_record_name(session, record_name)
    row = _row_for_entity(session, entity) if entity else None
    if row is not None and _has_dirty_local_changes(row, entity, incoming_updated_at):
        return "conflicts"

    if record_type == "Task":
        row = _upsert_task(session, user_id, payload, row)
        table_name = "tasks"
    elif record_type == "CaptureInboxItem":
        row = _upsert_capture(session, user_id, payload, row)
        table_name = "capture_inbox_items"
    elif record_type == "DailyCheckIn":
        row = _upsert_daily_check_in(session, user_id, payload, row)
        table_name = "stoic_entries"
    else:  # pragma: no cover - guarded by caller
        return "ignored"

    session.flush()
    _upsert_entity(
        session,
        entity=entity,
        table_name=table_name,
        local_id=row.id,
        record_type=record_type,
        envelope=envelope,
    )
    return "applied"


def _apply_tombstone(session: Session, envelope: dict[str, Any]) -> int:
    record_name = str(envelope["recordName"])
    entity = _entity_by_record_name(session, record_name)
    row = _row_for_entity(session, entity) if entity else None
    deleted_at = _parse_datetime(envelope.get("deletedAt")) or utcnow()
    if entity is not None:
        entity.deleted_at = deleted_at
        entity.last_pulled_at = utcnow()
        entity.payload_hash = payload_hash(envelope)
    if row is None:
        return 0
    if isinstance(row, Task | CaptureInboxItem):
        row.pending_delete = 1
        row.dirty = 0
    return 1


def _upsert_task(
    session: Session,
    user_id: int,
    payload: dict[str, Any],
    row: object | None,
) -> Task:
    if not isinstance(row, Task):
        row = Task(user_id=user_id, title=str(payload.get("title") or "New task"))
        session.add(row)
    row.title = str(payload.get("title") or row.title or "New task")
    row.area = _optional_string(payload.get("area"))
    row.category = _optional_string(payload.get("category"))
    row.priority = str(payload.get("priority") or row.priority or "medium")
    row.status = str(payload.get("status") or row.status or "open")
    row.notes = _optional_string(payload.get("notes"))
    row.due_date = _parse_date(payload.get("dueDate"))
    row.recurrence = _optional_string(payload.get("recurrence"))
    row.sort_order = _optional_int(payload.get("sortOrder"))
    row.remote_created_at = _parse_datetime(payload.get("remoteCreatedAt"))
    row.completed_at = _parse_datetime(payload.get("completedAt"))
    row.ext_id = _optional_string(payload.get("externalID"))
    row.synced_at = utcnow()
    row.dirty = 0
    row.pending_delete = 0
    return row


def _upsert_capture(
    session: Session,
    user_id: int,
    payload: dict[str, Any],
    row: object | None,
) -> CaptureInboxItem:
    if not isinstance(row, CaptureInboxItem):
        row = CaptureInboxItem(user_id=user_id, text=str(payload.get("text") or ""))
        session.add(row)
    row.text = str(payload.get("text") or row.text)
    row.source = str(payload.get("source") or row.source or "ios")
    row.status = str(payload.get("status") or row.status or "new")
    row.created_at = _parse_datetime(payload.get("createdAt")) or row.created_at or utcnow()
    row.updated_at = _parse_datetime(payload.get("updatedAt")) or utcnow()
    row.processed_at = _parse_datetime(payload.get("processedAt"))
    row.extra = dict(payload.get("extra") or {})
    row.dirty = 0
    row.pending_delete = 0
    return row


def _upsert_daily_check_in(
    session: Session,
    user_id: int,
    payload: dict[str, Any],
    row: object | None,
) -> StoicEntry:
    day = _parse_date(payload.get("day")) or date.today()
    if not isinstance(row, StoicEntry):
        row = session.scalars(
            select(StoicEntry).where(StoicEntry.user_id == user_id, StoicEntry.day == day)
        ).first()
    if row is None:
        row = StoicEntry(user_id=user_id, day=day)
        session.add(row)
    row.day = day
    row.virtue_focus = str(payload.get("virtueFocus") or row.virtue_focus or "wisdom")
    control_pct = _optional_int(payload.get("controlPercent"))
    if control_pct is not None:
        row.control_pct = control_pct
    row.reflected = bool(payload.get("reflected", row.reflected))
    row.served_others = bool(payload.get("servedOthers", row.served_others))
    row.faced_hard_thing = bool(payload.get("facedHardThing", row.faced_hard_thing))
    row.restrained_impulse = bool(payload.get("restrainedImpulse", row.restrained_impulse))
    study_minutes = _optional_int(payload.get("studyMinutes"))
    if study_minutes is not None:
        row.study_minutes = study_minutes
    row.reflection = str(payload.get("reflection") or row.reflection or "")
    row.updated_at = _parse_datetime(payload.get("updatedAt")) or utcnow()
    return row


def _upsert_entity(
    session: Session,
    *,
    entity: SyncEntity | None,
    table_name: str,
    local_id: int,
    record_type: str,
    envelope: dict[str, Any],
) -> SyncEntity:
    now = utcnow()
    if entity is None:
        entity = session.scalars(
            select(SyncEntity).where(
                SyncEntity.table_name == table_name,
                SyncEntity.local_id == local_id,
            )
        ).first()
    if entity is None:
        entity = SyncEntity(
            table_name=table_name,
            local_id=local_id,
            record_type=record_type,
            record_name=str(envelope["recordName"]),
            schema_version=int(envelope.get("schemaVersion") or SYNC_SCHEMA_VERSION),
            source_device_id=str(envelope.get("sourceDeviceID") or ""),
            conflict_policy="append_only" if record_type == "CaptureInboxItem" else "last_write_wins",
            updated_at=now,
        )
        session.add(entity)
    entity.table_name = table_name
    entity.local_id = local_id
    entity.record_type = record_type
    entity.record_name = str(envelope["recordName"])
    entity.schema_version = int(envelope.get("schemaVersion") or SYNC_SCHEMA_VERSION)
    entity.source_device_id = str(envelope.get("sourceDeviceID") or entity.source_device_id or "")
    entity.deleted_at = _parse_datetime(envelope.get("deletedAt"))
    entity.last_pulled_at = now
    entity.updated_at = _parse_datetime(envelope.get("updatedAt")) or now
    entity.payload_hash = payload_hash(envelope)
    return entity


def _row_for_entity(session: Session, entity: SyncEntity | None) -> object | None:
    if entity is None:
        return None
    models = {
        "tasks": Task,
        "capture_inbox_items": CaptureInboxItem,
        "stoic_entries": StoicEntry,
    }
    model = models.get(entity.table_name)
    if model is None:
        return None
    return session.get(model, entity.local_id)


def _has_dirty_local_changes(
    row: object,
    entity: SyncEntity | None,
    incoming_updated_at: datetime,
) -> bool:
    if bool(getattr(row, "dirty", False)):
        return True
    if entity is None:
        return False
    if entity.updated_at is None:
        return False
    return _timestamp_for_compare(entity.updated_at) > _timestamp_for_compare(incoming_updated_at)


def _entity_by_record_name(session: Session, record_name: str) -> SyncEntity | None:
    return session.scalars(
        select(SyncEntity).where(SyncEntity.record_name == record_name)
    ).first()


def _default_user_id(session: Session) -> int | None:
    user = session.scalars(select(User).order_by(User.id.asc()).limit(1)).first()
    return user.id if user else None


def _local_device_id(session: Session) -> str | None:
    device = session.scalars(select(SyncDevice).order_by(SyncDevice.id.asc()).limit(1)).first()
    return device.device_id if device else None


def _normalise_envelope(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if isinstance(payload, dict) and "recordType" in payload and "recordName" in payload:
        envelope = dict(payload)
        if "changeTag" in record:
            envelope["changeTag"] = record["changeTag"]
        return envelope
    return record


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _timestamp_for_compare(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
