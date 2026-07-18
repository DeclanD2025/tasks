"""Health: body telemetry — readiness, sleep, HRV, weight, VO2, trends.

Served at both ``/health`` (canonical) and ``/recovery`` (legacy path kept for
bookmarks and the existing test contract).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.domains import personal_os
from app.domains.health import derived
from app.web import presentation
from app.web.context import page, user_id

router = APIRouter()


def _render(request: Request) -> HTMLResponse:
    uid = user_id()
    snapshot = personal_os.get_recovery_snapshot(uid)
    return page(
        request,
        "health.html",
        "health",
        snap=snapshot,
        sleep_debt=derived.get_sleep_debt(uid),
        signals=presentation.partition_metrics(snapshot.metrics, primary_count=3),
        detail_key=presentation.detail_key,
        insights=presentation.health_insights(uid),
    )


@router.get("/health", response_class=HTMLResponse)
def health(request: Request):
    return _render(request)


@router.get("/recovery", response_class=HTMLResponse)
def recovery(request: Request):
    return _render(request)
