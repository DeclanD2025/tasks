"""JSON API for the Next.js UI.

One endpoint per screen. The payloads are shaped in ``app.web.ui_models`` to
match ``frontend/lib/types.ts`` exactly, so the client does no reshaping and no
arithmetic — it renders what ORION computed.

Separate from ``routes/api.py`` (which serves the Jinja app's drawers and
charts) because the two front ends want different shapes for the same numbers,
and pinning one to the other's contract would make both harder to change.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

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
