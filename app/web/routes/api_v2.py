"""JSON API for the Next.js UI.

One endpoint per screen. The payloads are shaped in ``app.web.ui_models`` to
match ``frontend/lib/types.ts`` exactly, so the client does no reshaping and no
arithmetic — it renders what ORION computed.

Separate from ``routes/api.py`` (which serves the Jinja app's drawers and
charts) because the two front ends want different shapes for the same numbers,
and pinning one to the other's contract would make both harder to change.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domains import plan_service
from app.web import ui_models
from app.web.context import user_id

router = APIRouter(prefix="/api/v2")


def _json(payload) -> JSONResponse:
    return JSONResponse(jsonable_encoder(payload))


@router.get("/today")
def v2_today():
    return _json(ui_models.today(user_id()))


@router.get("/recovery")
def v2_recovery():
    return _json(ui_models.recovery(user_id()))


@router.get("/training")
def v2_training():
    return _json(ui_models.training(user_id()))


@router.get("/plan")
def v2_plan():
    return _json(ui_models.plan(user_id()))


@router.get("/insights")
def v2_insights(days: int = 90):
    return _json(ui_models.insights_page(user_id(), days=days))


@router.get("/health")
def v2_health(days: int = 90):
    uid = user_id()
    return _json({
        "metrics": ui_models.metric_details_for(uid, ui_models.HEALTH_KINDS, days=days),
    })


@router.get("/metrics")
def v2_metrics(kinds: str = "", days: int = 90):
    """Several metrics at once: ``/api/v2/metrics?kinds=sleep,hrv``.

    Defaults to every kind ORION knows, which is what the metric drilldown
    needs since it can be linked to directly.
    """
    wanted = [k.strip() for k in kinds.split(",") if k.strip()] or ui_models.ALL_KINDS
    return _json(ui_models.metric_details_for(user_id(), wanted, days=days))


@router.get("/metrics/{kind}")
def v2_metric(kind: str, days: int = 90):
    detail = ui_models.metric_detail(user_id(), kind, days=days)
    if detail is None:
        return JSONResponse({"error": "unknown metric"}, status_code=404)
    return _json(detail)


@router.get("/sources")
def v2_sources():
    return _json({"sources": ui_models.sync_sources(user_id())})


# --------------------------------------------------------------------- plan
# The first write path in the Next UI. Reads elsewhere in this module are
# idempotent GETs; these mutate, so they validate through plan_service and
# translate its PlanError into a 400 rather than letting it 500.


class HabitDayIn(BaseModel):
    day: date
    done: bool


class HabitIn(BaseModel):
    name: str
    detail: str | None = None
    domain: str = "neutral"
    cadence: str = "daily"
    targetPerPeriod: int = 1


class GoalIn(BaseModel):
    title: str
    detail: str | None = None
    domain: str = "neutral"
    metricKind: str | None = None
    baselineValue: float | None = None
    targetValue: float | None = None
    manualValue: float | None = None
    unit: str = ""
    direction: str = "increase"
    targetDate: date | None = None


class GoalPatch(BaseModel):
    """Partial update. Unset fields are left alone, so omitting is not clearing."""

    title: str | None = None
    detail: str | None = None
    manualValue: float | None = None
    targetValue: float | None = None
    baselineValue: float | None = None
    targetDate: date | None = None
    status: str | None = None


def _plan_error(exc: plan_service.PlanError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/habits")
def v2_create_habit(body: HabitIn):
    try:
        habit_id = plan_service.create_habit(
            user_id(),
            body.name,
            detail=body.detail,
            domain=body.domain,
            cadence=body.cadence,
            target_per_period=body.targetPerPeriod,
        )
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json({"id": habit_id})


@router.post("/habits/{habit_id}/day")
def v2_set_habit_day(habit_id: int, body: HabitDayIn):
    """Tick or clear one day, returning the habit with its streak recomputed.

    The recomputed view comes back so the client never has to derive a streak
    itself — that arithmetic lives in one place.
    """
    try:
        view = plan_service.set_habit_day(user_id(), habit_id, body.day, body.done)
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json(ui_models.habit_view(view))


@router.delete("/habits/{habit_id}")
def v2_archive_habit(habit_id: int):
    try:
        plan_service.archive_habit(user_id(), habit_id)
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json({"ok": True})


@router.post("/goals")
def v2_create_goal(body: GoalIn):
    try:
        goal_id = plan_service.create_goal(
            user_id(),
            body.title,
            detail=body.detail,
            domain=body.domain,
            metric_kind=body.metricKind,
            baseline_value=body.baselineValue,
            target_value=body.targetValue,
            manual_value=body.manualValue,
            unit=body.unit,
            direction=body.direction,
            target_date=body.targetDate,
        )
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json({"id": goal_id})


@router.patch("/goals/{goal_id}")
def v2_update_goal(goal_id: int, body: GoalPatch):
    changes = {
        {"manualValue": "manual_value", "targetValue": "target_value",
         "baselineValue": "baseline_value", "targetDate": "target_date"}.get(k, k): v
        for k, v in body.model_dump(exclude_unset=True).items()
    }
    if not changes:
        return JSONResponse({"error": "nothing to update"}, status_code=400)
    try:
        view = plan_service.update_goal(user_id(), goal_id, **changes)
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json(ui_models.goal_view(view))


@router.delete("/goals/{goal_id}")
def v2_delete_goal(goal_id: int):
    try:
        plan_service.delete_goal(user_id(), goal_id)
    except plan_service.PlanError as exc:
        return _plan_error(exc)
    return _json({"ok": True})
