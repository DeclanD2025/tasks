"""Import a manually captured Trading 212 holdings snapshot.

Trading 212 web screenshots can show current positions and pie holdings even
when the exported transactions statement does not. This module imports that
snapshot into Account.extra so the Finance screen can show a current ISA
holdings overview without needing a Trading 212 API key.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import Account, BalanceSnapshot, DataSource, Domain, SourceStatus
from app.services import get_default_user_id


def import_holdings_snapshot(path: str | Path, user_id: int | None = None) -> dict:
    snapshot_path = Path(path).expanduser()
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    uid = user_id if user_id is not None else get_default_user_id()
    if uid is None:
        raise RuntimeError("No ORION user exists yet. Launch ORION once first.")

    captured_on = date.fromisoformat(payload["captured_on"])
    holdings = _flatten_holdings(payload)
    investments_minor = _money_minor(payload.get("investments_value", _sum_values(holdings)))
    account_value = payload.get("account_value")
    cash_value = payload.get("cash_value")

    with session_scope() as session:
        source = session.scalars(
            select(DataSource).where(DataSource.user_id == uid, DataSource.key == "trading212")
        ).first()
        if source is None:
            source = DataSource(
                user_id=uid,
                key="trading212",
                name="Trading 212",
                domain=Domain.finance,
                status=SourceStatus.connected,
            )
            session.add(source)
            session.flush()
        source.status = SourceStatus.connected
        source.last_synced_at = datetime.now()

        account = _isa_account(session, uid, source.id)
        if account is None:
            account = Account(
                user_id=uid,
                source_id=source.id,
                name="Trading 212 Stocks & Shares ISA",
                kind="investment",
                currency=payload.get("currency", "GBP"),
                extra={},
            )
            session.add(account)
            session.flush()
        extra = dict(account.extra or {})
        if cash_value is None:
            extra.pop("cash_value_minor", None)
        extra.update(
            {
                "provider": extra.get("provider") or "trading212_statement",
                "statement_label": extra.get("statement_label") or "ISA Account",
                "holdings_status": "live_snapshot_from_trading212_screen",
                "holdings_source": payload.get("source", "Trading 212 screenshot"),
                "holdings_captured_on": captured_on.isoformat(),
                "holdings": holdings,
                "investments_value_minor": investments_minor,
            }
        )
        if cash_value is not None:
            extra["cash_value_minor"] = _money_minor(cash_value)
        account.extra = extra
        if account_value is not None:
            _upsert_balance(
                session,
                account.id,
                captured_on,
                _money_minor(account_value),
                payload.get("currency", "GBP"),
            )
    return {
        "holdings": len(holdings),
        "investments_value": investments_minor / 100.0,
        "captured_on": captured_on.isoformat(),
    }


def _flatten_holdings(payload: dict[str, Any]) -> list[dict]:
    by_name: dict[str, dict] = {}
    sources: dict[str, list[str]] = defaultdict(list)

    def add_holding(row: dict, source: str, *, direct: bool = False) -> None:
        name = str(row["name"])
        value = float(row.get("value") or 0.0)
        existing = by_name.setdefault(
            name,
            {
                "name": name,
                "ticker": row.get("ticker", ""),
                "quantity": row.get("quantity"),
                "value": 0.0,
                "return_value": 0.0,
                "return_pct": None,
                "actual_weight_pct": None,
                "target_weight_pct": None,
                "sources": [],
            },
        )
        existing["value"] = round(float(existing["value"]) + value, 2)
        existing["return_value"] = round(
            float(existing.get("return_value") or 0.0) + float(row.get("return_value") or 0.0),
            2,
        )
        if row.get("ticker") and not existing.get("ticker"):
            existing["ticker"] = row["ticker"]
        if direct and row.get("quantity") is not None:
            existing["quantity"] = row["quantity"]
        if row.get("actual_weight_pct") is not None:
            existing["actual_weight_pct"] = row.get("actual_weight_pct")
        if row.get("target_weight_pct") is not None:
            existing["target_weight_pct"] = row.get("target_weight_pct")
        sources[name].append(source)

    for row in payload.get("direct_positions", []):
        add_holding(row, "Direct", direct=True)
    for pie in payload.get("pies", []):
        for row in pie.get("holdings", []):
            add_holding(row, pie.get("name", "Pie"))

    total_value = _sum_values(by_name.values()) or 1.0
    out = []
    for name, row in by_name.items():
        row["sources"] = sorted(set(sources[name]))
        row["portfolio_weight_pct"] = round(float(row["value"]) / total_value * 100.0, 2)
        if row["value"]:
            row["return_pct"] = round(float(row["return_value"]) / (row["value"] - row["return_value"]) * 100.0, 2)
        out.append(row)
    return sorted(out, key=lambda item: float(item["value"]), reverse=True)


def _isa_account(session, user_id: int, source_id: int) -> Account | None:
    accounts = session.scalars(
        select(Account).where(Account.user_id == user_id, Account.source_id == source_id)
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
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.snapshot_date == snapshot_date,
        )
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


def _sum_values(rows) -> float:
    return round(sum(float(row.get("value") or 0.0) for row in rows), 2)


def _money_minor(value) -> int:
    return int(round(float(value) * 100))
