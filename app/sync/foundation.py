"""Desktop-side CloudKit sync metadata and backfill.

This module deliberately does not talk to CloudKit. It prepares the local
SQLite database for a signed helper to push/pull records by creating stable
record identities, checkpoints, and pending mutation envelopes.
"""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.database import get_engine, session_scope
from app.db.models import (
    Base,
    CalendarEvent,
    CaptureInboxItem,
    FitnessSession,
    Insight,
    StoicEntry,
    SyncCheckpoint,
    SyncDevice,
    SyncEntity,
    SyncOutbox,
    Task,
    User,
    Workout,
    utcnow,
)
from app.mobile.snapshot import build_mobile_snapshot
from app.sync.payloads import (
    SYNC_SCHEMA_VERSION,
    build_record_envelope,
    payload_for_row,
    payload_hash,
)

CLOUDKIT_CONTAINER_ID = "iCloud.com.declandundas.orion"
CLOUDKIT_ZONE_NAME = "orion-main"
SQLITE_SYNC_USER_VERSION = 1


@dataclass(frozen=True)
class SyncableModel:
    table_name: str
    record_type: str
    model: type
    conflict_policy: str


SYNCABLE_MODELS: tuple[SyncableModel, ...] = (
    SyncableModel("tasks", "Task", Task, "last_write_wins"),
    SyncableModel("capture_inbox_items", "CaptureInboxItem", CaptureInboxItem, "append_only"),
    SyncableModel("stoic_entries", "DailyCheckIn", StoicEntry, "last_write_wins"),
    SyncableModel("fitness_sessions", "FitnessSession", FitnessSession, "read_mostly"),
    SyncableModel("calendar_events", "CalendarEvent", CalendarEvent, "read_mostly"),
    SyncableModel("workouts", "WorkoutSummary", Workout, "read_mostly"),
    SyncableModel("insights", "Insight", Insight, "read_mostly"),
)


def ensure_sync_foundation(engine: Engine | None = None) -> dict[str, int | str]:
    """Create sync tables, backfill UUID mappings, and queue pending records."""
    engine = engine or get_engine()
    Base.metadata.create_all(bind=engine)
    _set_sqlite_user_version(engine)

    with session_scope() as session:
        device = _ensure_device(session)
        _ensure_checkpoint(session, device.device_id)
        syncable_rows = _backfill_syncable_rows(session, device.device_id)
        dashboard_rows = _queue_dashboard_snapshots(session, device.device_id)
        pending = session.scalar(
            select(func.count()).select_from(SyncOutbox).where(SyncOutbox.status == "pending")
        )
        return {
            "device_id": device.device_id,
            "syncable_rows": syncable_rows,
            "dashboard_rows": dashboard_rows,
            "pending_outbox": int(pending or 0),
        }


def pending_outbox_records(limit: int = 200) -> list[dict[str, Any]]:
    """Return pending CloudKit envelopes for the Swift helper."""
    with session_scope() as session:
        rows = session.scalars(
            select(SyncOutbox)
            .where(SyncOutbox.status == "pending")
            .order_by(SyncOutbox.created_at.asc(), SyncOutbox.id.asc())
            .limit(limit)
        ).all()
        return [
            {
                "outboxID": row.id,
                "recordType": row.record_type,
                "recordName": row.record_name,
                "operation": row.operation,
                "payload": row.payload,
            }
            for row in rows
        ]


def _set_sqlite_user_version(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        current = conn.execute(text("PRAGMA user_version")).scalar_one()
        if int(current) < SQLITE_SYNC_USER_VERSION:
            conn.execute(text(f"PRAGMA user_version={SQLITE_SYNC_USER_VERSION}"))


def _ensure_device(session: Session) -> SyncDevice:
    device = session.scalars(select(SyncDevice).order_by(SyncDevice.id.asc()).limit(1)).first()
    now = utcnow()
    if device is None:
        device = SyncDevice(
            device_id=str(uuid4()),
            name=socket.gethostname() or "ORION Mac",
            platform=f"macos-desktop:{platform.machine()}",
            created_at=now,
            last_seen_at=now,
            extra={"python": platform.python_version()},
        )
        session.add(device)
        session.flush()
    else:
        device.last_seen_at = now
    return device


def _ensure_checkpoint(session: Session, device_id: str) -> None:
    checkpoint = session.scalars(
        select(SyncCheckpoint).where(
            SyncCheckpoint.database_scope == "private",
            SyncCheckpoint.zone_name == CLOUDKIT_ZONE_NAME,
        )
    ).first()
    if checkpoint is None:
        session.add(
            SyncCheckpoint(
                database_scope="private",
                zone_name=CLOUDKIT_ZONE_NAME,
                device_id=device_id,
                extra={"container": CLOUDKIT_CONTAINER_ID},
            )
        )
    else:
        checkpoint.device_id = device_id


def _backfill_syncable_rows(session: Session, device_id: str) -> int:
    inspector = inspect(session.bind)
    existing_tables = set(inspector.get_table_names())
    count = 0
    for syncable in SYNCABLE_MODELS:
        if syncable.table_name not in existing_tables:
            continue
        rows = session.scalars(select(syncable.model).order_by(syncable.model.id.asc())).all()
        for row in rows:
            entity = _ensure_entity(
                session,
                syncable=syncable,
                local_id=row.id,
                device_id=device_id,
            )
            deleted_at = _deleted_at(row)
            envelope = build_record_envelope(
                record_type=syncable.record_type,
                record_name=entity.record_name,
                source_device_id=device_id,
                payload=payload_for_row(row),
                updated_at=_row_updated_at(row),
                deleted_at=deleted_at,
            )
            new_hash = payload_hash(envelope)
            operation = "delete" if deleted_at else "upsert"
            if entity.payload_hash != new_hash or entity.deleted_at != deleted_at:
                entity.payload_hash = new_hash
                entity.updated_at = utcnow()
                entity.deleted_at = deleted_at
                _queue_outbox(session, entity, operation, envelope)
            count += 1
    return count


def _queue_dashboard_snapshots(session: Session, device_id: str) -> int:
    users = session.scalars(select(User).order_by(User.id.asc())).all()
    count = 0
    for user in users:
        entity = _ensure_entity(
            session,
            syncable=SyncableModel(
                "users",
                "DashboardSnapshot",
                User,
                "read_mostly",
            ),
            local_id=user.id,
            device_id=device_id,
        )
        try:
            snapshot = build_mobile_snapshot(user_id=user.id)
        except Exception as exc:  # pragma: no cover - defensive for live integrations
            snapshot = {
                "schema_version": SYNC_SCHEMA_VERSION,
                "user": {"id": user.id, "display_name": user.display_name, "email": user.email},
                "error": str(exc),
            }
        envelope = build_record_envelope(
            record_type="DashboardSnapshot",
            record_name=entity.record_name,
            source_device_id=device_id,
            payload=snapshot,
            updated_at=utcnow(),
        )
        new_hash = payload_hash(envelope)
        if entity.payload_hash != new_hash:
            entity.payload_hash = new_hash
            entity.updated_at = utcnow()
            _queue_outbox(session, entity, "upsert", envelope)
        count += 1
    return count


def _ensure_entity(
    session: Session,
    *,
    syncable: SyncableModel,
    local_id: int,
    device_id: str,
) -> SyncEntity:
    entity = session.scalars(
        select(SyncEntity).where(
            SyncEntity.table_name == syncable.table_name,
            SyncEntity.local_id == local_id,
        )
    ).first()
    if entity is None:
        entity = SyncEntity(
            table_name=syncable.table_name,
            local_id=local_id,
            record_type=syncable.record_type,
            record_name=str(uuid4()),
            schema_version=SYNC_SCHEMA_VERSION,
            source_device_id=device_id,
            conflict_policy=syncable.conflict_policy,
            updated_at=utcnow(),
        )
        session.add(entity)
        session.flush()
    return entity


def _queue_outbox(
    session: Session,
    entity: SyncEntity,
    operation: str,
    payload: dict[str, Any],
) -> None:
    existing = session.scalars(
        select(SyncOutbox).where(
            SyncOutbox.entity_id == entity.id,
            SyncOutbox.operation == operation,
            SyncOutbox.status == "pending",
        )
    ).first()
    if existing is not None:
        existing.payload = payload
        existing.updated_at = utcnow()
        return
    session.add(
        SyncOutbox(
            entity_id=entity.id,
            record_type=entity.record_type,
            record_name=entity.record_name,
            operation=operation,
            payload=payload,
            status="pending",
        )
    )


def _row_updated_at(row: object) -> datetime:
    for attr in ("updated_at", "synced_at", "completed_at", "created_at", "starts_at"):
        value = getattr(row, attr, None)
        if isinstance(value, datetime):
            return value
    return utcnow()


def _deleted_at(row: object) -> datetime | None:
    pending_delete = bool(getattr(row, "pending_delete", False))
    if not pending_delete:
        return None
    value = getattr(row, "updated_at", None) or getattr(row, "synced_at", None)
    return value if isinstance(value, datetime) else utcnow()
