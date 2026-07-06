"""Tasks: the Supabase-mirrored open-loop list."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import services
from app.db.database import session_scope
from app.db.models import DataSource
from app.ingestion import get_connector
from app.web.context import page, parse_form_date, user_id

router = APIRouter()


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    uid = user_id()
    tasks = services.get_tasks(uid, include_done=True)
    open_tasks = [t for t in tasks if t["status"] != "done"]
    done_tasks = [t for t in tasks if t["status"] == "done"]
    grouped: dict[str, list[dict]] = {}
    for task in open_tasks:
        grouped.setdefault(task["area"], []).append(task)
    return page(
        request,
        "tasks.html",
        "tasks",
        tasks=tasks,
        open_tasks=open_tasks,
        done_tasks=done_tasks,
        grouped_tasks=grouped,
        counts=services.task_counts(uid),
        sync_status=request.query_params.get("sync", ""),
        sync_count=request.query_params.get("count", ""),
    )


@router.post("/tasks/sync")
def tasks_sync():
    uid = user_id()
    conn = get_connector("tasks_sync")
    if not conn.connect():
        return RedirectResponse("/tasks?sync=error", status_code=303)
    with session_scope() as s:
        src = s.query(DataSource).filter_by(user_id=uid, key=conn.key).one_or_none()
        if src is None:
            src = DataSource(
                user_id=uid,
                key=conn.key,
                name=conn.name,
                domain=conn.domain,
                status=conn.status,
            )
            s.add(src)
            s.flush()
        result = conn.run(s, uid, src.id)
        src.status = conn.status
        src.last_synced_at = datetime.now()
    if not result.ok:
        return RedirectResponse("/tasks?sync=error", status_code=303)
    return RedirectResponse(
        f"/tasks?sync=ok&count={result.normalised_records}",
        status_code=303,
    )


@router.post("/tasks")
def tasks_add(
    title: str = Form(""),
    area: str = Form(""),
    category: str = Form(""),
    priority: str = Form("medium"),
    due_date: str = Form(""),
    notes: str = Form(""),
):
    services.add_task(
        user_id(),
        title,
        area=area.strip() or None,
        category=category.strip() or None,
        priority=priority if priority in {"low", "medium", "high"} else "medium",
        due_date=parse_form_date(due_date),
        notes=notes.strip() or None,
    )
    return RedirectResponse("/tasks", status_code=303)


@router.post("/tasks/{task_id}/complete")
def tasks_complete(task_id: int, done: str = Form("")):
    services.set_task_done(task_id, done=bool(done))
    return RedirectResponse("/tasks", status_code=303)


@router.post("/tasks/{task_id}/delete")
def tasks_delete(task_id: int):
    services.delete_task(task_id)
    return RedirectResponse("/tasks", status_code=303)
