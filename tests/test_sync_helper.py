from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import SyncOutbox
from app.sync import ensure_sync_foundation
from app.sync.helper import mark_outbox_pushed, sync_pending_outbox


def test_sync_pending_outbox_invokes_helper_with_json(tmp_path):
    helper = tmp_path / "fake_helper.py"
    helper.write_text(
        """
import json
import sys

payload = json.load(sys.stdin)
print(json.dumps({"ok": True, "count": len(payload.get("records", []))}))
""".strip(),
        encoding="utf-8",
    )

    foundation = ensure_sync_foundation()
    response = sync_pending_outbox(
        dry_run=True,
        helper_command=[sys.executable, str(helper)],
    )

    assert response["ok"] is True
    assert response["count"] == foundation["pending_outbox"]


def test_mark_outbox_pushed_marks_rows_sent():
    ensure_sync_foundation()
    with session_scope() as session:
        row = session.scalars(select(SyncOutbox).where(SyncOutbox.status == "pending")).first()
        assert row is not None
        outbox_id = row.id
        entity_id = row.entity_id

    mark_outbox_pushed(
        [
            {
                "outboxID": outbox_id,
                "recordName": "record",
                "recordType": "Task",
                "operation": "upsert",
                "changeTag": "abc123",
            }
        ]
    )

    with session_scope() as session:
        row = session.get(SyncOutbox, outbox_id)
        assert row is not None
        assert row.status == "sent"
        if entity_id is not None:
            assert row.entity_id == entity_id
