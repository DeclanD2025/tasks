from __future__ import annotations

import json

from app.integrations.trading212.holdings_snapshot import import_holdings_snapshot
from app.domains.finance.finance_service import stocks_and_shares_isa_overview
from app.services import get_default_user_id


def test_import_holdings_snapshot_flattens_direct_and_pie_holdings(tmp_path):
    payload = {
        "source": "test",
        "captured_on": "2026-06-25",
        "currency": "GBP",
        "account_value": 120.0,
        "investments_value": 100.0,
        "direct_positions": [
            {"name": "Example ETF", "ticker": "EXM", "quantity": 2.0, "value": 60.0}
        ],
        "pies": [
            {
                "name": "Growth Pie",
                "holdings": [
                    {"name": "Example ETF", "value": 15.0},
                    {"name": "Second Stock", "value": 25.0, "return_value": 5.0},
                ],
            }
        ],
    }
    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = import_holdings_snapshot(path)
    overview = stocks_and_shares_isa_overview(get_default_user_id())

    assert result["holdings"] == 2
    assert overview is not None
    assert overview.investments_value == 100.0
    assert overview.cash_estimate == 20.0
    assert overview.holdings[0]["name"] == "Example ETF"
    assert overview.holdings[0]["value"] == 75.0
    assert set(overview.holdings[0]["sources"]) == {"Direct", "Growth Pie"}


def test_import_holdings_snapshot_uses_explicit_cash_value(tmp_path):
    payload = {
        "source": "test",
        "captured_on": "2026-06-26",
        "currency": "GBP",
        "account_value": 120.0,
        "investments_value": 120.0,
        "cash_value": 0.0,
        "direct_positions": [
            {"name": "Example ETF", "ticker": "EXM", "quantity": 2.0, "value": 120.0}
        ],
    }
    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    import_holdings_snapshot(path)
    overview = stocks_and_shares_isa_overview(get_default_user_id())

    assert overview is not None
    assert overview.investments_value == 120.0
    assert overview.cash_estimate == 0.0
