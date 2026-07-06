from __future__ import annotations

from dataclasses import asdict

from app import services
from app.domains.finance.finance_service import (
    account_readouts,
    allocation_by_kind,
    finance_intelligence_snapshot,
    get_finance_dashboard_snapshot,
    provider_plans,
    store_provider_credential,
    store_provider_credentials,
)
from app.db.database import session_scope
from app.db.models import Account, DataSource, Domain, SourceStatus, Transaction
from datetime import date


def test_finance_provider_plans_cover_secure_sources():
    uid = services.get_default_user_id()
    plans = provider_plans(uid)
    keys = {plan.key for plan in plans}

    assert {"open_banking", "trading212", "moneybox"}.issubset(keys)
    assert all(
        plan.status_label in {"LIVE", "WAITING", "ATTENTION", "KEY STORED", "TOKEN STORED"}
        for plan in plans
    )
    assert all(plan.required_items for plan in plans)

    open_banking = next(plan for plan in plans if plan.key == "open_banking")
    assert "starling" in open_banking.auth_method.lower()
    assert "token" in open_banking.auth_method.lower()
    assert "passwords" in open_banking.security_note.lower()


def test_finance_snapshot_exposes_read_only_dashboard_contract():
    uid = services.get_default_user_id()
    snapshot = get_finance_dashboard_snapshot(uid)

    labels = {metric.label for metric in snapshot.metrics}
    assert {"Net Worth", "Cash", "Invested", "LISA", "Debt"}.issubset(labels)
    assert snapshot.providers
    assert snapshot.accounts
    assert snapshot.capital_series
    assert snapshot.security_posture == "READ-ONLY DESIGN"
    assert snapshot.risk.provider_count == len(snapshot.providers)


def test_lisa_account_is_bucketed_separately():
    uid = services.get_default_user_id()
    accounts = account_readouts(uid)
    allocation = allocation_by_kind(accounts)

    assert any(row["source_key"] == "moneybox" for row in accounts)
    assert allocation["LISA"] > 0


def test_provider_plans_do_not_expose_secret_values():
    uid = services.get_default_user_id()
    serialised = str([asdict(plan) for plan in provider_plans(uid)]).lower()

    for forbidden in ("api_key=", "api_secret=", "client_secret=", "refresh_token="):
        assert forbidden not in serialised


def test_store_provider_credential_keeps_plaintext_out_of_db(monkeypatch):
    uid = services.get_default_user_id()

    def fake_store_secret(name: str, secret: str) -> str:
        assert name == "finance.trading212.api_key"
        assert secret == "secret-value"
        return "macos-keychain:orion.finance.trading212.api_key"

    monkeypatch.setattr(
        "app.domains.finance.finance_service.store_secret",
        fake_store_secret,
    )

    ref = store_provider_credential(uid, "trading212", "api_key", "secret-value")

    assert ref.startswith("macos-keychain:")
    with session_scope() as s:
        source = s.query(DataSource).filter_by(user_id=uid, key="trading212").one()
        assert source.extra["credential_state"] == "stored"
        assert source.extra["credential_refs"]["api_key"] == ref
        assert "secret-value" not in str(source.extra)

    plan = next(plan for plan in provider_plans(uid) if plan.key == "trading212")
    assert plan.status_label in {"KEY STORED", "LIVE"}


def test_store_starling_token_keeps_plaintext_out_of_db(monkeypatch):
    uid = services.get_default_user_id()
    seen: dict[str, str] = {}

    def fake_store_secret(name: str, secret: str) -> str:
        seen[name] = secret
        return f"macos-keychain:orion.{name}"

    monkeypatch.setattr(
        "app.domains.finance.finance_service.store_secret",
        fake_store_secret,
    )

    refs = store_provider_credentials(uid, "open_banking", {"access_token": "starling-token"})

    assert seen == {"finance.open_banking.access_token": "starling-token"}
    assert refs == {"access_token": "macos-keychain:orion.finance.open_banking.access_token"}
    with session_scope() as s:
        source = s.query(DataSource).filter_by(user_id=uid, key="open_banking").one()
        assert source.extra["credential_state"] == "token_stored"
        assert source.extra["credential_refs"] == refs
        assert "starling-token" not in str(source.extra)

    plan = next(plan for plan in provider_plans(uid) if plan.key == "open_banking")
    assert plan.status_label == "TOKEN STORED"


def test_open_banking_access_token_reference_reports_token_stored():
    uid = services.get_default_user_id()
    ref = "macos-keychain:orion.finance.open_banking.access_token"
    with session_scope() as s:
        source = s.query(DataSource).filter_by(user_id=uid, key="open_banking").one()
        source.extra = {
            "credential_state": "token_stored",
            "credential_refs": {"access_token": ref},
        }

    plan = next(plan for plan in provider_plans(uid) if plan.key == "open_banking")
    assert plan.status_label == "TOKEN STORED"
    assert plan.action_label == "ROTATE TOKEN"
    assert ref not in str(plan)
    assert "access-token-value" not in str(plan)


def test_finance_intelligence_detects_recurring_subscriptions_and_funding():
    uid = services.get_default_user_id()
    with session_scope() as s:
        source = DataSource(
            user_id=uid,
            key="test_finance_intel",
            name="Test Finance Intel",
            domain=Domain.finance,
            status=SourceStatus.connected,
        )
        s.add(source)
        s.flush()
        account = Account(
            user_id=uid,
            source_id=source.id,
            name="Intel Current",
            kind="current",
            currency="GBP",
            extra={},
        )
        s.add(account)
        s.flush()
        for day in (date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)):
            s.add(
                Transaction(
                    account_id=account.id,
                    booked_at=day,
                    amount_minor=-999,
                    currency="GBP",
                    category="subscriptions",
                    description="Example Stream - EXAMPLE - MASTER_CARD - BILLS_AND_SERVICES",
                    extra={},
                )
            )
        s.add(
            Transaction(
                account_id=account.id,
                booked_at=date(2026, 6, 2),
                amount_minor=-10000,
                currency="GBP",
                category="uncategorised",
                description="Trading 212 - TEST - FASTER_PAYMENTS_OUT - NONE",
                extra={},
            )
        )
        s.add(
            Transaction(
                account_id=account.id,
                booked_at=date(2026, 6, 3),
                amount_minor=-10000,
                currency="GBP",
                category="uncategorised",
                description="Moneybox S&S LISA - TEST - FASTER_PAYMENTS_OUT - NONE",
                extra={},
            )
        )

    intel = finance_intelligence_snapshot(uid, days=190)

    assert any(line.merchant == "Example Stream" for line in intel.subscriptions)
    assert any(line.destination == "Stocks & Shares ISA" for line in intel.funding_flows)
    assert any(line.destination == "LISA" for line in intel.funding_flows)


def test_finance_intelligence_collapses_subscription_charge_bursts():
    uid = services.get_default_user_id()
    with session_scope() as s:
        source = DataSource(
            user_id=uid,
            key="test_finance_burst",
            name="Test Finance Burst",
            domain=Domain.finance,
            status=SourceStatus.connected,
        )
        s.add(source)
        s.flush()
        account = Account(
            user_id=uid,
            source_id=source.id,
            name="Burst Current",
            kind="current",
            currency="GBP",
            extra={},
        )
        s.add(account)
        s.flush()
        for offset in range(5):
            s.add(
                Transaction(
                    account_id=account.id,
                    booked_at=date(2026, 6, 1 + offset),
                    amount_minor=-999,
                    currency="GBP",
                    category="subscriptions",
                    description="Burst Service - BURST - MASTER_CARD - BILLS_AND_SERVICES",
                    extra={},
                )
            )

    intel = finance_intelligence_snapshot(uid, days=190)

    assert not any(line.merchant == "Burst Service" for line in intel.recurring)
    assert any("Burst Service" in alert.title for alert in intel.alerts)
