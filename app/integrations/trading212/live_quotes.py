"""Public quote refresh for imported Trading 212 holdings.

Trading 212's statement gives us quantities and identifiers. This module uses
public market quotes to revalue those quantities locally, without requiring a
Trading 212 API key or order-placement access.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import desc, select

from app.db.database import session_scope
from app.db.models import Account, BalanceSnapshot, DataSource, SourceStatus
from app.services import get_default_user_id


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
QUOTE_TIMEOUT = 8.0

QUOTE_SYMBOL_BY_TICKER = {
    "ARKK": "ARKK.L",
    "BOTZ": "BOTZ.L",
    "DEVSF": "DEVSF",
    "IITU": "IITU.L",
    "NATP": "NATP.L",
    "QBTS": "QBTS",
    "QUBT": "QUBT",
    "RGTI": "RGTI",
    "RKLB": "RKLB",
    "SAEM": "SAEM.L",
    "SSIT": "SSIT.L",
    "SXR8": "SXR8.DE",
    "VHYL": "VHYL.L",
    "VWRP": "VWRP.L",
}

FX_SYMBOLS = {"USD": "USDGBP=X", "EUR": "EURGBP=X"}


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    currency: str
    previous_close: float | None = None


def refresh_live_quotes(
    *,
    user_id: int | None = None,
    fetcher=None,
    today: date | None = None,
) -> dict:
    """Revalue the imported Stocks & Shares ISA holdings from live quotes."""

    uid = user_id if user_id is not None else get_default_user_id()
    if uid is None:
        return {"updated": 0, "detail": "no user"}
    today = today or date.today()

    with session_scope() as session:
        account = _stocks_isa_account(session, uid)
        if account is None:
            return {"updated": 0, "detail": "no stocks isa"}
        extra = dict(account.extra or {})
        holdings = extra.get("holdings") if isinstance(extra.get("holdings"), list) else []
        if not holdings:
            return {"updated": 0, "detail": "no holdings"}
        symbols = sorted(
            {
                symbol
                for holding in holdings
                if (symbol := _quote_symbol(holding))
                and holding.get("quantity") is not None
            }
        )
        if not symbols:
            return {"updated": 0, "detail": "no quoteable holdings"}

    fetch = fetcher or fetch_yahoo_quotes
    quotes = fetch(symbols + sorted(FX_SYMBOLS.values()))
    fx_rates = {
        currency: quote_row.price
        for currency, fx_symbol in FX_SYMBOLS.items()
        if (quote_row := quotes.get(fx_symbol)) is not None
    }

    with session_scope() as session:
        account = _stocks_isa_account(session, uid)
        if account is None:
            return {"updated": 0, "detail": "no stocks isa"}
        extra = dict(account.extra or {})
        holdings = [dict(row) for row in extra.get("holdings", []) if isinstance(row, dict)]
        updated, missing = _revalue_holdings(holdings, quotes, fx_rates)
        investments_value = round(sum(float(row.get("value") or 0.0) for row in updated), 2)
        cash_minor = extra.get("cash_value_minor")
        cash_value = float(cash_minor) / 100.0 if cash_minor is not None else 0.0
        account_value = round(investments_value + cash_value, 2)

        refreshed_at = datetime.now(timezone.utc)
        extra.update(
            {
                "holdings": updated,
                "holdings_status": "live_public_quotes",
                "quote_refreshed_at": refreshed_at.isoformat(),
                "quote_source": "Yahoo Finance public chart",
                "quote_missing_symbols": missing,
                "investments_value_minor": _money_minor(investments_value),
            }
        )
        account.extra = extra

        _upsert_balance(session, account.id, today, _money_minor(account_value), account.currency)
        source = session.get(DataSource, account.source_id)
        if source is not None:
            source.status = SourceStatus.connected
            source.last_synced_at = refreshed_at
    return {
        "updated": len(updated) - len(missing),
        "holdings": len(updated),
        "missing": missing,
        "investments_value": investments_value,
        "account_value": account_value,
    }


def refresh_live_quotes_if_stale(user_id: int, *, max_age_minutes: int = 15) -> dict:
    if _live_disabled_for_tests():
        return {"updated": 0, "detail": "disabled for tests"}
    with session_scope() as session:
        account = _stocks_isa_account(session, user_id)
        if account is None:
            return {"updated": 0, "detail": "no stocks isa"}
        refreshed = _parse_datetime((account.extra or {}).get("quote_refreshed_at"))
    if refreshed and datetime.now(timezone.utc) - refreshed < timedelta(minutes=max_age_minutes):
        return {"updated": 0, "detail": "fresh"}
    try:
        return refresh_live_quotes(user_id=user_id)
    except Exception as exc:
        return {"updated": 0, "detail": f"{type(exc).__name__}: {exc}"}


def fetch_yahoo_quotes(symbols: list[str]) -> dict[str, Quote]:
    out: dict[str, Quote] = {}
    for symbol in symbols:
        request = Request(
            YAHOO_CHART_URL.format(symbol=quote(symbol, safe="")),
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        with urlopen(request, timeout=QUOTE_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        result = (payload.get("chart", {}).get("result") or [{}])[0]
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        currency = meta.get("currency")
        if price is None or not currency:
            continue
        previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        out[symbol] = Quote(
            symbol=symbol,
            price=float(price),
            currency=str(currency),
            previous_close=float(previous_close) if previous_close is not None else None,
        )
    return out


def _revalue_holdings(
    holdings: list[dict],
    quotes: dict[str, Quote],
    fx_rates: dict[str, float],
) -> tuple[list[dict], list[str]]:
    missing: list[str] = []
    for row in holdings:
        symbol = _quote_symbol(row)
        row["quote_symbol"] = symbol
        if not symbol:
            continue
        quote_row = quotes.get(symbol)
        if quote_row is None:
            missing.append(symbol)
            continue
        try:
            quantity = float(row.get("quantity"))
        except (TypeError, ValueError):
            continue
        price_gbp = _price_to_gbp(quote_row.price, quote_row.currency, fx_rates)
        value = round(quantity * price_gbp, 2)
        previous_value = None
        if quote_row.previous_close is not None:
            previous_value = round(quantity * _price_to_gbp(quote_row.previous_close, quote_row.currency, fx_rates), 2)
        cost_basis = _cost_basis_gbp(row)
        row.update(
            {
                "quote_currency": quote_row.currency,
                "live_price": quote_row.price,
                "live_price_gbp": round(price_gbp, 6),
                "value": value,
                "live_value": value,
                "previous_value": previous_value,
                "quote_source": "Yahoo Finance public chart",
            }
        )
        if cost_basis is not None:
            ret = round(value - cost_basis, 2)
            row["return_value"] = ret
            row["return_pct"] = round(ret / cost_basis * 100.0, 2) if cost_basis else None
        if previous_value is not None:
            row["day_change_value"] = round(value - previous_value, 2)
            row["day_change_pct"] = round((value - previous_value) / previous_value * 100.0, 2) if previous_value else None

    total = sum(float(row.get("value") or 0.0) for row in holdings) or 1.0
    for row in holdings:
        row["portfolio_weight_pct"] = round(float(row.get("value") or 0.0) / total * 100.0, 2)
    return sorted(holdings, key=lambda item: float(item.get("value") or 0.0), reverse=True), sorted(set(missing))


def _quote_symbol(row: dict) -> str:
    existing = str(row.get("quote_symbol") or "").strip()
    if existing:
        return existing
    ticker = str(row.get("ticker") or "").strip().upper()
    return QUOTE_SYMBOL_BY_TICKER.get(ticker, ticker)


def _price_to_gbp(price: float, currency: str, fx_rates: dict[str, float]) -> float:
    raw_currency = str(currency)
    if raw_currency == "GBp":
        return price / 100.0
    currency = raw_currency.upper()
    if currency == "GBP":
        return price
    if currency in {"GBX", "GBPENCE"}:
        return price / 100.0
    if currency == "USD":
        return price * fx_rates.get("USD", 0.7572)
    if currency == "EUR":
        return price * fx_rates.get("EUR", 0.8614)
    return price


def _cost_basis_gbp(row: dict) -> float | None:
    statement_value = row.get("activity_statement_value")
    statement_return = row.get("activity_statement_return")
    if statement_value is not None and statement_return is not None:
        return round(float(statement_value) - float(statement_return), 2)
    value = row.get("value")
    ret = row.get("return_value")
    if value is not None and ret is not None:
        return round(float(value) - float(ret), 2)
    return None


def _stocks_isa_account(session, user_id: int) -> Account | None:
    trading212 = session.scalars(
        select(DataSource).where(DataSource.user_id == user_id, DataSource.key == "trading212")
    ).first()
    if trading212 is None:
        return None
    accounts = session.scalars(
        select(Account).where(Account.user_id == user_id, Account.source_id == trading212.id)
    ).all()
    return next(
        (
            row
            for row in accounts
            if (row.extra or {}).get("statement_label") == "ISA Account"
            or "stocks & shares isa" in row.name.lower()
        ),
        None,
    )


def _upsert_balance(session, account_id: int, snapshot_date: date, balance_minor: int, currency: str) -> None:
    existing = session.scalars(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id, BalanceSnapshot.snapshot_date == snapshot_date)
        .order_by(desc(BalanceSnapshot.id))
        .limit(1)
    ).first()
    if existing is None:
        session.add(
            BalanceSnapshot(
                account_id=account_id,
                snapshot_date=snapshot_date,
                balance_minor=balance_minor,
                currency=currency,
            )
        )
    else:
        existing.balance_minor = balance_minor
        existing.currency = currency


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _money_minor(value) -> int:
    return int(round(float(value) * 100))


def _live_disabled_for_tests() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)
