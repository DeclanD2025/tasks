from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import CaptureInboxItem, SyncEntity, Task, utcnow
from app.services import get_default_user_id
from app.sync import apply_incoming_records, ensure_sync_foundation
from app.sync.payloads import build_record_envelope


def test_apply_incoming_capture_creates_desktop_inbox_item():
    user_id = get_default_user_id()
    assert user_id is not None
    envelope = build_record_envelope(
        record_type="CaptureInboxItem",
        record_name="mobile-capture-1",
        source_device_id="ios-device",
        updated_at=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        payload={
            "text": "Remember to review route plan",
            "source": "ios",
            "status": "new",
            "createdAt": "2026-07-02T10:00:00+00:00",
            "extra": {"context": "lock-screen"},
        },
    )

    result = apply_incoming_records([envelope], user_id=user_id)

    assert result["applied"] == 1
    with session_scope() as session:
        capture = session.scalars(
            select(CaptureInboxItem).where(CaptureInboxItem.text == "Remember to review route plan")
        ).one()
        entity = session.scalars(
            select(SyncEntity).where(SyncEntity.record_name == "mobile-capture-1")
        ).one()

    assert capture.source == "ios"
    assert capture.dirty == 0
    assert entity.table_name == "capture_inbox_items"
    assert entity.local_id == capture.id


def test_apply_incoming_task_creates_desktop_task():
    user_id = get_default_user_id()
    assert user_id is not None
    envelope = build_record_envelope(
        record_type="Task",
        record_name="mobile-task-1",
        source_device_id="ios-device",
        updated_at=datetime(2026, 7, 2, 11, 0, tzinfo=timezone.utc),
        payload={
            "title": "Book physio",
            "area": "Health",
            "category": "Admin",
            "priority": "high",
            "status": "open",
            "notes": "Use the sports clinic",
            "dueDate": "2026-07-05",
            "sortOrder": 4,
        },
    )

    result = apply_incoming_records([envelope], user_id=user_id)

    assert result["applied"] == 1
    with session_scope() as session:
        task = session.scalars(select(Task).where(Task.title == "Book physio")).one()
        entity = session.scalars(
            select(SyncEntity).where(SyncEntity.record_name == "mobile-task-1")
        ).one()

    assert task.area == "Health"
    assert task.due_date == date(2026, 7, 5)
    assert task.dirty == 0
    assert entity.table_name == "tasks"


def test_apply_incoming_tombstone_marks_task_pending_delete():
    user_id = get_default_user_id()
    assert user_id is not None
    with session_scope() as session:
        task = Task(user_id=user_id, title="Delete from phone", dirty=0)
        session.add(task)
    ensure_sync_foundation()
    with session_scope() as session:
        entity = session.scalars(
            select(SyncEntity).where(SyncEntity.record_type == "Task", SyncEntity.local_id == task.id)
        ).one()
        record_name = entity.record_name

    envelope = build_record_envelope(
        record_type="Task",
        record_name=record_name,
        source_device_id="ios-device",
        updated_at=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        deleted_at=datetime(2026, 7, 2, 12, 1, tzinfo=timezone.utc),
        payload={"title": "Delete from phone"},
    )

    result = apply_incoming_records([envelope], user_id=user_id)

    assert result["deleted"] == 1
    with session_scope() as session:
        task = session.get(Task, task.id)

    assert task is not None
    assert task.pending_delete == 1
    assert task.dirty == 0


def test_apply_incoming_task_does_not_clobber_dirty_local_edit():
    user_id = get_default_user_id()
    assert user_id is not None
    with session_scope() as session:
        task = Task(user_id=user_id, title="Desktop draft", dirty=1, synced_at=utcnow())
        session.add(task)
    ensure_sync_foundation()
    with session_scope() as session:
        entity = session.scalars(
            select(SyncEntity).where(SyncEntity.record_type == "Task", SyncEntity.local_id == task.id)
        ).one()
        record_name = entity.record_name

    envelope = build_record_envelope(
        record_type="Task",
        record_name=record_name,
        source_device_id="ios-device",
        updated_at=datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc),
        payload={
            "title": "Phone edit",
            "priority": "low",
            "status": "open",
        },
    )

    result = apply_incoming_records([envelope], user_id=user_id)

    assert result["conflicts"] == 1
    with session_scope() as session:
        task = session.get(Task, task.id)

    assert task is not None
    assert task.title == "Desktop draft"
    assert task.dirty == 1
