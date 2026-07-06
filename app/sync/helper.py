"""Bridge from the Python desktop app to the signed Swift CloudKit helper."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.db.database import session_scope
from app.db.models import SyncEntity, SyncOutbox, utcnow
from app.sync.foundation import pending_outbox_records


def sync_pending_outbox(
    *,
    dry_run: bool = True,
    limit: int = 200,
    helper_command: list[str] | None = None,
) -> dict[str, Any]:
    """Send pending records to the Swift helper and return its JSON response."""
    records = pending_outbox_records(limit=limit)
    command = {
        "operation": "dryRun" if dry_run else "push",
        "records": records,
    }
    response = _run_helper(command, helper_command=helper_command)
    if not dry_run and response.get("ok"):
        mark_outbox_pushed(response.get("records", []))
    return response


def mark_outbox_pushed(records: list[dict[str, Any]]) -> None:
    """Mark successfully pushed outbox rows as sent."""
    if not records:
        return
    now = utcnow()
    with session_scope() as session:
        for record in records:
            outbox_id = record.get("outboxID")
            if outbox_id is None:
                continue
            row = session.get(SyncOutbox, int(outbox_id))
            if row is None:
                continue
            row.status = "sent"
            row.updated_at = now
            if row.entity_id is not None:
                entity = session.get(SyncEntity, row.entity_id)
                if entity is not None:
                    entity.last_pushed_at = now
                    entity.cloudkit_change_tag = record.get("changeTag")


def _run_helper(
    command: dict[str, Any],
    *,
    helper_command: list[str] | None = None,
) -> dict[str, Any]:
    args = helper_command or _default_helper_command()
    proc = subprocess.run(
        args,
        input=json.dumps(command).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or "no helper output"
        raise RuntimeError(
            f"orion-sync-helper exited {proc.returncode}: {detail}"
        )
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("orion-sync-helper returned invalid JSON") from exc


def _default_helper_command() -> list[str]:
    configured = os.getenv("ORION_SYNC_HELPER")
    if configured:
        return [configured]

    repo_root = Path(__file__).resolve().parents[2]
    built_helper = repo_root / "mobile" / "OrionSyncKit" / ".build" / "debug" / "orion-sync-helper"
    if built_helper.exists():
        return [str(built_helper)]

    package_path = repo_root / "mobile" / "OrionSyncKit"
    return ["swift", "run", "--package-path", str(package_path), "orion-sync-helper"]
