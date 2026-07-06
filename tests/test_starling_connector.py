from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.database import session_scope
from app.db.models import Account, BalanceSnapshot, DataSource
from app.ingestion import get_connector
from app.services import get_default_user_id


def test_starling_balance_records_total_and_spaces_split():
    uid = get_default_user_id()
    connector = get_connector("open_banking")
    records = [
        {
            "record_type": "account",
            "provider_account_id": "starling-test-account",
            "default_category_uid": "category",
            "account_type": "PRIMARY",
            "name": "Personal",
            "kind": "current",
            "currency": "GBP",
        },
        {
            "record_type": "balance",
            "provider_account_id": "starling-test-account",
            "snapshot_date": date(2026, 6, 25),
            "balance_minor": 45_085,
            "currency": "GBP",
            "balance_basis": "total_effective_balance",
            "available_to_spend_minor": 217,
            "spaces_balance_minor": 44_868,
            "spaces": [{"name": "Buffer", "saved_minor": 44_868, "currency": "GBP"}],
        },
    ]

    with session_scope() as session:
        source = session.scalars(
            select(DataSource).where(DataSource.user_id == uid, DataSource.key == "open_banking")
        ).one()
        connector.store_normalised_data(session, uid, source.id, records)

    with session_scope() as session:
        account = session.scalars(
            select(Account).where(
                Account.user_id == uid,
                Account.extra["provider_account_id"].as_string() == "starling-test-account",
            )
        ).one()
        balance = session.scalars(
            select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id)
        ).one()

    assert balance.balance_minor == 45_085
    assert account.extra["starling_available_to_spend_minor"] == 217
    assert account.extra["starling_spaces_balance_minor"] == 44_868
    assert account.extra["starling_balance_basis"] == "total_effective_balance"
