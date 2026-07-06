from __future__ import annotations

from sqlalchemy import func, select, text

from app.db.database import get_engine, session_scope
from app.db.models import CaptureInboxItem, SyncEntity, SyncOutbox, Task, utcnow
from app.services import get_default_user_id
from app.sync import CLOUDKIT_ZONE_NAME, ensure_sync_foundation, pending_outbox_records


def test_sync_foundation_sets_sqlite_user_version_and_checkpoint():
    result = ensure_sync_foundation()

    assert result["device_id"]
    with get_engine().connect() as conn:
        user_version = conn.execute(text("PRAGMA user_version")).scalar_one()
        checkpoint = conn.execute(
            text("select zone_name from sync_checkpoints where database_scope = 'private'")
        ).scalar_one()

    assert user_version >= 1
    assert checkpoint == CLOUDKIT_ZONE_NAME


def test_sync_backfill_is_idempotent_for_existing_rows():
    user_id = get_default_user_id()
    assert user_id is not None

    with session_scope() as session:
        task = Task(user_id=user_id, title="Sync me", status="open", dirty=1)
        capture = CaptureInboxItem(user_id=user_id, text="Mobile thought", source="ios")
        session.add_all([task, capture])

    first = ensure_sync_foundation()
    with session_scope() as session:
        entity_count_1 = session.scalar(select(func.count()).select_from(SyncEntity))
        outbox_count_1 = session.scalar(select(func.count()).select_from(SyncOutbox))
        task_entities = session.scalars(
            select(SyncEntity).where(SyncEntity.record_type == "Task")
        ).all()
        capture_entities = session.scalars(
            select(SyncEntity).where(SyncEntity.record_type == "CaptureInboxItem")
        ).all()

    second = ensure_sync_foundation()
    with session_scope() as session:
        entity_count_2 = session.scalar(select(func.count()).select_from(SyncEntity))
        outbox_count_2 = session.scalar(select(func.count()).select_from(SyncOutbox))

    assert first["pending_outbox"] == second["pending_outbox"]
    assert entity_count_1 == entity_count_2
    assert outbox_count_1 == outbox_count_2
    assert task_entities
    assert capture_entities
    assert all(entity.record_name for entity in task_entities + capture_entities)


def test_pending_outbox_records_use_shared_cloudkit_envelope():
    ensure_sync_foundation()
    records = pending_outbox_records(limit=50)

    assert records
    payloads = [record["payload"] for record in records]
    assert any(payload["recordType"] == "DashboardSnapshot" for payload in payloads)
    assert all(payload["schemaVersion"] == 1 for payload in payloads)
    assert all(payload["sourceDeviceID"] for payload in payloads)
    assert all("payload" in payload for payload in payloads)


def test_pending_delete_records_queue_tombstones():
    user_id = get_default_user_id()
    assert user_id is not None

    with session_scope() as session:
        task = Task(
            user_id=user_id,
            title="Delete me remotely",
            status="open",
            dirty=1,
            pending_delete=1,
            synced_at=utcnow(),
        )
        session.add(task)

    ensure_sync_foundation()

    with session_scope() as session:
        tombstone = session.scalars(
            select(SyncOutbox)
            .where(SyncOutbox.record_type == "Task")
            .where(SyncOutbox.operation == "delete")
            .order_by(SyncOutbox.id.desc())
        ).first()

    assert tombstone is not None
    assert tombstone.payload["deletedAt"]
