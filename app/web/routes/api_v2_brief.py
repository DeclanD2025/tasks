"""The homepage's API.

One composed endpoint (`GET /api/v2/brief`) rather than a homepage that fetches
six things and reconciles them client-side. The reconciliation — which insight
to show, whether the task counts can be trusted, what the next action is — is
exactly the judgement that belongs in the backend, where it can be tested and
where the answer gets persisted.

The write endpoints all record what the operator did, because the archive of
suggestions is only half the data. Knowing ORION proposed something is useless
without knowing whether it was taken.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domains.briefing import brief as brief_service
from app.domains.briefing import review as review_service
from app.web.context import user_id

router = APIRouter(prefix="/api/v2")


def _json(payload) -> JSONResponse:
    return JSONResponse(jsonable_encoder(payload))


def _error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


class DeferIn(BaseModel):
    until: date | None = None


class ReviewIn(BaseModel):
    status: str
    deferUntil: date | None = None
    nextAction: str | None = None
    estimateMinutes: int | None = None
    energy: str | None = None
    impact: str | None = None
    archivedReason: str | None = None


class EditBriefIn(BaseModel):
    stateSummary: str | None = None
    focus: str | None = None
    nextAction: str | None = None


class EventIn(BaseModel):
    kind: str
    taskId: int | None = None
    subject: str = ""
    detail: dict | None = None


@router.get("/brief")
def v2_brief(refresh: bool = False):
    """The whole homepage, prioritised and ready to render."""
    return _json(brief_service.generate(user_id(), force=refresh))


@router.get("/brief/history")
def v2_brief_history(days: int = 30):
    """Past briefs — what ORION said, and when."""
    return _json(brief_service.effectiveness(user_id(), days=days))


@router.post("/brief/edit")
def v2_edit_brief(body: EditBriefIn):
    try:
        brief_service.edit_brief(
            user_id(), date.today(),
            stateSummary=body.stateSummary, focus=body.focus, nextAction=body.nextAction,
        )
    except ValueError as exc:
        return _error(exc)
    return _json(brief_service.generate(user_id()))


@router.post("/brief/priorities/{task_id}/defer")
def v2_defer(task_id: int, body: DeferIn):
    try:
        brief_service.defer_priority(user_id(), task_id, until=body.until)
    except ValueError as exc:
        return _error(exc)
    return _json(brief_service.generate(user_id(), force=True))


@router.post("/brief/priorities/{task_id}/pin")
def v2_pin(task_id: int):
    try:
        brief_service.pin_priority(user_id(), task_id)
    except ValueError as exc:
        return _error(exc)
    return _json(brief_service.generate(user_id(), force=True))


@router.post("/brief/priorities/{task_id}/complete")
def v2_complete(task_id: int):
    try:
        brief_service.complete_task(user_id(), task_id)
    except ValueError as exc:
        return _error(exc)
    return _json(brief_service.generate(user_id(), force=True))


@router.post("/brief/events")
def v2_event(body: EventIn):
    """Log an interaction — evidence opened, insight dismissed.

    Separate from the action endpoints because viewing is not doing, and
    conflating them would make the archive useless for telling which
    suggestions were actually read.
    """
    brief_service.record_event(
        user_id(), body.kind, task_id=body.taskId,
        subject=body.subject, detail=body.detail,
    )
    return _json({"ok": True})


@router.post("/tasks/{task_id}/review")
def v2_review_task(task_id: int, body: ReviewIn):
    fields = {
        k: v for k, v in {
            "defer_until": body.deferUntil,
            "next_action": body.nextAction,
            "estimate_minutes": body.estimateMinutes,
            "energy": body.energy,
            "impact": body.impact,
            "archived_reason": body.archivedReason,
        }.items() if v is not None
    }
    try:
        review_service.mark_reviewed(user_id(), task_id, body.status, **fields)
    except ValueError as exc:
        return _error(exc)
    return _json({"ok": True})
