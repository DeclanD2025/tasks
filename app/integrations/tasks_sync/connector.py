"""Tasks connector — two-way sync with the companion tasks app (Supabase).

Each sync run:
  1. Pushes locally-changed rows back to Supabase (``dirty`` → insert/update,
     ``pending_delete`` → delete), so edits and completions made inside ORION
     reach the web app.
  2. Pulls the full ``tasks`` table and upserts it into the local ``tasks`` table
     by ``ext_id`` (Supabase row UUID), pruning local rows whose remote row was
     deleted elsewhere.

Conflict policy is last-writer-wins, biased to the local edit: a row marked
``dirty`` is pushed and then refreshed from the push response, so a pull in the
same run can't clobber an unsynced local change.

If Supabase is unreachable, the run is a no-op (it never wipes the local mirror).
The companion tasks repo itself is never modified — only its database rows.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Domain, Task
from app.ingestion.base import Connector
from app.integrations.tasks_sync.supabase import SupabaseTasks

log = get_logger(__name__)


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        # Supabase returns ISO 8601 with offset; normalise to aware UTC.
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class TasksSyncConnector(Connector):
    key = "tasks_sync"
    name = "Tasks (Supabase)"
    domain = Domain.tasks
    is_mock = False  # this is a real network sync

    def __init__(self) -> None:
        self._client = SupabaseTasks()
        self._reachable = True

    @property
    def available(self) -> bool:
        return self._client.ping()

    def connect(self) -> bool:
        self._reachable = self._client.ping()
        return self._reachable

    # fetch happens inside the run via store_normalised_data; nothing to stage.
    def fetch_raw_data(self) -> list[dict]:
        return []

    def store_normalised_data(self, session, user_id, source_id, records) -> int:
        if not self._reachable:
            return 0
        self._push_local_changes(session, user_id)
        return self._pull_remote(session, user_id)

    # --- push ------------------------------------------------------------- #
    def _push_local_changes(self, session, user_id) -> None:
        # Deletes first.
        to_delete = session.scalars(
            select(Task).where(
                Task.user_id == user_id, Task.pending_delete == 1
            )
        ).all()
        for row in to_delete:
            try:
                if row.ext_id:
                    self._client.delete(row.ext_id)
                session.delete(row)
            except Exception as exc:  # leave the row queued for next run
                log.warning("Task delete push failed (%s): %s", row.ext_id, exc)

        # Inserts / updates.
        dirty = session.scalars(
            select(Task).where(
                Task.user_id == user_id,
                Task.dirty == 1,
                Task.pending_delete == 0,
            )
        ).all()
        for row in dirty:
            payload = _to_remote_payload(row)
            try:
                if row.ext_id:
                    self._client.update(row.ext_id, payload)
                else:
                    created = self._client.insert(payload)
                    if created and created.get("id"):
                        row.ext_id = str(created["id"])
                        row.remote_created_at = _parse_dt(created.get("created_at"))
                row.dirty = 0
                row.synced_at = datetime.now(timezone.utc)
            except Exception as exc:
                log.warning("Task push failed (%s): %s", row.ext_id, exc)
        session.flush()

    # --- pull ------------------------------------------------------------- #
    def _pull_remote(self, session, user_id) -> int:
        try:
            remote = self._client.list_tasks()
        except Exception as exc:
            log.warning("Task pull failed: %s", exc)
            return 0

        seen: set[str] = set()
        written = 0
        for r in remote:
            ext_id = str(r["id"])
            seen.add(ext_id)
            row = session.scalars(
                select(Task).where(
                    Task.user_id == user_id, Task.ext_id == ext_id
                )
            ).first()
            if row is None:
                row = Task(user_id=user_id, ext_id=ext_id)
                session.add(row)
            elif row.dirty or row.pending_delete:
                # Local edit not yet pushed — don't let the pull clobber it.
                continue
            _apply_remote(row, r)
            row.synced_at = datetime.now(timezone.utc)
            written += 1

        # Prune local rows whose remote row was deleted elsewhere (skip rows
        # that were created locally and not yet pushed, i.e. no ext_id).
        local = session.scalars(
            select(Task).where(
                Task.user_id == user_id, Task.ext_id.is_not(None)
            )
        ).all()
        for row in local:
            if row.ext_id not in seen and not row.dirty and not row.pending_delete:
                session.delete(row)

        session.flush()
        return written


def _apply_remote(row: Task, r: dict) -> None:
    row.title = r.get("title") or ""
    row.area = r.get("area")
    row.category = r.get("category")
    row.priority = r.get("priority") or "medium"
    # Supabase status: 'done' marks completion; anything else is open.
    row.status = "done" if (r.get("status") == "done") else "open"
    row.notes = r.get("notes")
    row.due_date = _parse_date(r.get("due_date"))
    row.recurrence = r.get("recurrence")
    row.sort_order = r.get("sort_order")
    row.remote_created_at = _parse_dt(r.get("created_at"))
    row.completed_at = _parse_dt(r.get("completed_at"))


def _to_remote_payload(row: Task) -> dict:
    payload = {
        "title": row.title,
        "area": row.area,
        "category": row.category,
        "priority": row.priority,
        "status": "done" if row.status == "done" else "open",
        "notes": row.notes,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "recurrence": row.recurrence,
        "sort_order": row.sort_order,
    }
    if row.status == "done":
        payload["completed_at"] = (
            row.completed_at or datetime.now(timezone.utc)
        ).isoformat()
    else:
        payload["completed_at"] = None
    return payload
