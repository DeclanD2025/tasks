"""Money: monthly position, accounts, transactions, currency context."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import services
from app.domains import personal_os, settings_service
from app.integrations.external_signals import get_fx_rates
from app.web.context import page, user_id

router = APIRouter()


@router.get("/money", response_class=HTMLResponse)
def money(request: Request):
    uid = user_id()
    snapshot = personal_os.get_finance_operating_snapshot(uid)
    home = settings_service.get_value(uid, "home_currency") or "GBP"
    fx = get_fx_rates(home)
    return page(
        request,
        "money.html",
        "money",
        snap=snapshot,
        accounts=services.account_snapshot_latest(uid),
        transactions=services.recent_transactions(uid, limit=8),
        fx=fx,
        home_currency=home,
    )
