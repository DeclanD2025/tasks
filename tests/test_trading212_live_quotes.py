from __future__ import annotations

import json

from app.domains.finance.finance_service import stocks_and_shares_isa_overview
from app.integrations.trading212.holdings_snapshot import import_holdings_snapshot
from app.integrations.trading212.live_quotes import Quote, refresh_live_quotes
from app.services import get_default_user_id


def test_refresh_live_quotes_revalues_known_quantities(tmp_path):
    payload = {
        "source": "test",
        "captured_on": "2026-06-25",
        "currency": "GBP",
        "account_value": 60.0,
        "investments_value": 60.0,
        "cash_value": 0.0,
        "direct_positions": [
            {
                "name": "iShares Core S&P 500 (Acc)",
                "ticker": "SXR8",
                "quantity": 0.1,
                "value": 60.0,
                "return_value": 10.0,
            }
        ],
    }
    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    import_holdings_snapshot(path)

    def fake_fetcher(symbols):
        assert "SXR8.DE" in symbols
        return {
            "SXR8.DE": Quote("SXR8.DE", price=700.0, currency="EUR", previous_close=690.0),
            "EURGBP=X": Quote("EURGBP=X", price=0.86, currency="GBP"),
            "USDGBP=X": Quote("USDGBP=X", price=0.75, currency="GBP"),
        }

    result = refresh_live_quotes(user_id=get_default_user_id(), fetcher=fake_fetcher)
    overview = stocks_and_shares_isa_overview(get_default_user_id())

    assert result["investments_value"] == 60.2
    assert overview is not None
    assert overview.value == 60.2
    assert overview.cash_estimate == 0.0
    assert overview.holdings_status == "live_public_quotes"
    assert overview.holdings[0]["quote_symbol"] == "SXR8.DE"
    assert overview.holdings[0]["value"] == 60.2


def test_refresh_live_quotes_converts_london_pence(tmp_path):
    payload = {
        "source": "test",
        "captured_on": "2026-06-25",
        "currency": "GBP",
        "account_value": 0.0,
        "investments_value": 0.0,
        "cash_value": 0.0,
        "direct_positions": [
            {
                "name": "Seraphim Space Investment Trust",
                "ticker": "SSIT",
                "quantity": 10.0,
                "value": 18.0,
            }
        ],
    }
    path = tmp_path / "holdings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    import_holdings_snapshot(path)

    def fake_fetcher(_symbols):
        return {
            "SSIT.L": Quote("SSIT.L", price=183.0, currency="GBp", previous_close=180.0),
            "EURGBP=X": Quote("EURGBP=X", price=0.86, currency="GBP"),
            "USDGBP=X": Quote("USDGBP=X", price=0.75, currency="GBP"),
        }

    result = refresh_live_quotes(user_id=get_default_user_id(), fetcher=fake_fetcher)

    assert result["investments_value"] == 18.3
