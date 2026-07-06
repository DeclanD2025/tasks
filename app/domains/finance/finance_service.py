"""Finance-domain read models and secure connection planning.

This module is deliberately credential-free. It describes what ORION needs in
order to monitor banking, Trading 212, and LISA data, but it never asks for or
stores secrets. Real credentials should live in the OS keychain and provider
OAuth flows, with only non-secret connection metadata mirrored into the DB.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import desc, select

from app import services
from app.core.secrets import store_secret
from app.db.database import session_scope
from app.db.models import (
    Account,
    BalanceSnapshot,
    DataSource,
    Domain,
    SourceStatus,
    Transaction,
    utcnow,
)
from app.services import Metric


@dataclass(frozen=True)
class FinanceProviderPlan:
    """A secure setup/readiness card for one finance data source."""

    key: str
    title: str
    code: str
    role: str
    auth_method: str
    data_scope: str
    status_label: str
    tone: str
    action_label: str
    required_items: list[str]
    security_note: str
    credential_label: str = ""
    credential_fields: tuple[tuple[str, str], ...] = ()
    connected: bool = False
    source_name: str = ""
    last_synced_label: str = "NEVER"


@dataclass(frozen=True)
class FinanceRiskSnapshot:
    cash: float
    invested: float
    lisa: float
    debt: float
    monthly_burn: float
    runway_months: float
    total_assets: float
    net_worth: float
    net_worth_delta_pct: float
    live_provider_count: int
    provider_count: int


@dataclass(frozen=True)
class StocksAndSharesIsaOverview:
    account_name: str
    value: float
    investments_value: float
    cash_estimate: float
    currency: str
    snapshot_date: date
    period_start: date | None
    period_end: date | None
    generated_on: date | None
    deposits: float
    withdrawals: float
    interest: float
    net_cash_flow: float
    movement_count: int
    holdings_status: str
    holdings_captured_on: date | None
    quote_refreshed_at: datetime | None
    quote_source: str
    day_change: float
    day_change_pct: float
    holdings: list[dict]


@dataclass(frozen=True)
class LiabilityLine:
    """One hard debt the user owes (loan, bill). Reduces net worth."""

    name: str
    balance: float          # positive number = amount still owed
    kind: str               # "loan" | "bill" | "card" | ...
    source_label: str


@dataclass(frozen=True)
class CreditFacilityLine:
    """Available credit headroom on a card — spending power, NOT owed.

    Deliberately does not touch net worth: ``available`` is the unused limit,
    ``drawn`` is anything actually owed on it (normally 0 here).
    """

    name: str
    available: float
    drawn: float


@dataclass(frozen=True)
class RecurringExpenseLine:
    merchant: str
    category: str
    average: float
    monthly_estimate: float
    count: int
    cadence_label: str
    last_seen: date
    next_due: date | None


@dataclass(frozen=True)
class SpendingPatternLine:
    label: str
    value: str
    detail: str
    tone: str = "neutral"


@dataclass(frozen=True)
class FinanceAlertLine:
    title: str
    detail: str
    amount: float
    tone: str = "warning"


@dataclass(frozen=True)
class FundingFlowLine:
    destination: str
    monthly_rate: float
    total: float
    count: int
    last_seen: date | None
    source: str


@dataclass(frozen=True)
class ProjectionLine:
    label: str
    value_1y: float
    value_3y: float
    value_5y: float
    monthly_contribution: float
    rate_label: str
    note: str


@dataclass(frozen=True)
class FinanceIntelligenceSnapshot:
    period_start: date | None
    period_end: date | None
    recurring: list[RecurringExpenseLine]
    subscriptions: list[RecurringExpenseLine]
    patterns: list[SpendingPatternLine]
    alerts: list[FinanceAlertLine]
    funding_flows: list[FundingFlowLine]
    projections: list[ProjectionLine]


@dataclass(frozen=True)
class FinanceDashboardSnapshot:
    metrics: list[Metric]
    providers: list[FinanceProviderPlan]
    setup_tasks: list[str]
    accounts: list[dict]
    allocation: dict[str, float]
    capital_series: list[float]
    spend_zones: list[dict]
    transactions: list[dict]
    risk: FinanceRiskSnapshot
    stocks_isa: StocksAndSharesIsaOverview | None
    sync_label: str
    database_label: str
    security_posture: str
    liabilities: list[LiabilityLine]
    credit_facilities: list[CreditFacilityLine]
    total_debt: float
    available_credit: float
    intelligence: FinanceIntelligenceSnapshot


_PROVIDER_CATALOG: dict[str, dict] = {
    "open_banking": {
        "title": "Starling Bank",
        "code": "FIN-BNK",
        "role": "Current, savings and card movements",
        "auth_method": "Starling Personal Access Token",
        "data_scope": "Accounts, balances and transaction feed",
        "action_label": "ADD STARLING TOKEN",
        "credential_label": "Starling personal access token",
        "credential_fields": (("access_token", "Personal Access Token"),),
        "required_items": [
            "Create a Starling Personal Access Token with account, balance and transaction read permissions.",
            "Store the token in macOS Keychain; ORION keeps only a local reference.",
            "Rotate the token in Starling if it was ever pasted into the wrong place.",
        ],
        "security_note": "Never collect bank passwords. Revoke or rotate this token from Starling at any time.",
    },
    "trading212": {
        "title": "Trading 212",
        "code": "FIN-T12",
        "role": "Invest/ISA portfolio and cash balance",
        "auth_method": "Trading 212 Public API key pair",
        "data_scope": "Account cash, positions, dividends and history",
        "action_label": "ADD READ-ONLY KEY",
        "credential_label": "Trading 212 read-only API key",
        "credential_fields": (("api_key", "API Key"),),
        "required_items": [
            "Generate a read-only key pair in Trading 212 API settings.",
            "Restrict the key to trusted IPs where possible.",
            "Do not enable order placement until trading controls exist.",
        ],
        "security_note": "Treat the API secret like a password and rotate it if exposed.",
    },
    "moneybox": {
        "title": "LISA",
        "code": "FIN-LSA",
        "role": "Lifetime ISA balance and contributions",
        "auth_method": "Provider API if available, otherwise statement/CSV import",
        "data_scope": "Balance snapshots, deposits, bonus payments and fees",
        "action_label": "PREPARE IMPORT",
        "credential_fields": (),
        "required_items": [
            "Confirm the LISA provider and export format.",
            "Prefer official API or Open Finance connection where available.",
            "Use manual import rather than screen scraping if there is no API.",
        ],
        "security_note": "No LISA login should be saved in ORION.",
    },
}


def refresh_quotes_async(user_id: int, on_done=None) -> None:
    """Refresh stale Trading 212 live quotes off the UI thread.

    The finance page renders instantly from cached quotes, then calls this so a
    network fetch never blocks the UI. ``on_done`` (optional) is invoked when the
    refresh actually changed something, so the page can re-render with fresh
    values. Failures are swallowed — stale-but-cached beats a frozen UI.
    """
    import threading

    def _run() -> None:
        try:
            from app.integrations.trading212.live_quotes import refresh_live_quotes_if_stale

            result = refresh_live_quotes_if_stale(user_id)
            if on_done and result.get("updated"):
                on_done()
        except Exception:
            pass

    threading.Thread(target=_run, name="orion-quote-refresh", daemon=True).start()


def get_finance_dashboard_snapshot(user_id: int, *, days: int = 30) -> FinanceDashboardSnapshot:
    """Build the finance page payload from normalized local data."""

    nw = services.net_worth_series(user_id, days=days)
    ms = services.monthly_spending(user_id)
    all_accounts = account_readouts(user_id)
    # Credit facilities are £0-balance headroom records; keep them out of the
    # asset/exposure list (surfaced separately as available credit). Risk uses
    # the full set so negative balances still register as debt.
    risk_accounts = [a for a in all_accounts if str(a.get("kind")) != CREDIT_FACILITY_KIND]
    # Account Exposure shows assets only; hard debts have their own panel.
    accounts = [
        a
        for a in risk_accounts
        if str(a.get("kind")) not in LIABILITY_KINDS and float(a["value"]) >= 0
    ]
    txns = services.recent_transactions(user_id, limit=8)
    categories = services.spending_by_category(user_id, days=days)
    providers = provider_plans(user_id)
    allocation = allocation_by_kind(accounts)
    risk = _risk_snapshot(risk_accounts, nw, ms, providers)
    stocks_isa = stocks_and_shares_isa_overview(user_id)
    intelligence = finance_intelligence_snapshot(user_id, stocks_isa=stocks_isa)
    liabilities = liability_readouts(user_id)
    credit_facilities = credit_facility_readouts(user_id)
    total_debt = sum(line.balance for line in liabilities)
    available_credit = sum(line.available for line in credit_facilities)

    capital_series = net_worth_history(user_id, days=days, fallback=risk.net_worth)
    spend_zones = [
        {"label": str(row["category"]), "value": float(row["spend"])}
        for row in categories[:5]
    ]
    setup_tasks = [
        task
        for provider in providers
        if not provider.connected
        for task in provider.required_items[:1]
    ]

    sync_label = (
        f"{risk.live_provider_count}/{risk.provider_count} LIVE"
        if risk.provider_count
        else "NO SOURCES"
    )
    database_label = f"{len(accounts)} ACCOUNTS"
    security_posture = "READ-ONLY DESIGN" if providers else "FINANCE OFFLINE"

    return FinanceDashboardSnapshot(
        metrics=_finance_metrics(risk, capital_series),
        providers=providers,
        setup_tasks=setup_tasks,
        accounts=accounts,
        allocation=allocation,
        capital_series=capital_series,
        spend_zones=spend_zones,
        transactions=txns,
        risk=risk,
        stocks_isa=stocks_isa,
        sync_label=sync_label,
        database_label=database_label,
        security_posture=security_posture,
        liabilities=liabilities,
        credit_facilities=credit_facilities,
        total_debt=total_debt,
        available_credit=available_credit,
        intelligence=intelligence,
    )


def seed_real_finance_data(user_id: int) -> None:
    """Write the user's real manually-maintained balances (2026-06-25).

    Idempotent: re-running updates today's snapshot rather than duplicating.
    LISA is an asset; Abound + phone bill are hard debts; the four cards are
    available-credit headroom (owe £0) and never move net worth.
    """

    upsert_manual_account(
        user_id, "Moneybox Lifetime ISA", kind="savings", balance=1046.35,
        extra={"is_lisa": True, "allowance_saved": 300.0, "allowance_total": 4000.0},
    )
    upsert_manual_account(
        user_id, "Abound loan", kind="loan", balance=-2950.0,
        extra={"liability_type": "loan"},
    )
    upsert_manual_account(
        user_id, "Phone bill", kind="bill", balance=-740.0,
        extra={"liability_type": "bill"},
    )
    for name, limit in [
        ("Zopa", 600.0),
        ("Barclaycard", 400.0),
        ("Capital One", 750.0),
        ("Aqua", 1100.0),
    ]:
        upsert_manual_account(
            user_id, name, kind=CREDIT_FACILITY_KIND, balance=0.0,
            extra={"credit_limit_minor": int(limit * 100), "drawn_minor": 0},
        )


def finance_intelligence_snapshot(
    user_id: int,
    *,
    stocks_isa: StocksAndSharesIsaOverview | None = None,
    days: int = 190,
) -> FinanceIntelligenceSnapshot:
    """Mine local transaction history for spending, funding and projections."""

    rows = _transaction_rows(user_id, days=days)
    if not rows:
        return FinanceIntelligenceSnapshot(None, None, [], [], [], [], [], [])

    period_start = min(row["booked_at"] for row in rows)
    period_end = max(row["booked_at"] for row in rows)
    observed_days = max((period_end - period_start).days + 1, 1)

    outgoing = [row for row in rows if row["amount"] < 0]
    income = [row for row in rows if row["amount"] > 0 and not _is_self_funding(row)]
    spend_rows = [row for row in outgoing if not _is_internal_transfer(row) and not _is_account_funding(row)]
    funding_rows = [row for row in rows if _is_account_funding(row)]

    recurring = _recurring_expenses(outgoing)
    subscriptions = [
        line
        for line in recurring
        if _looks_like_subscription(line.merchant, line.category)
    ]
    patterns = _spending_patterns(spend_rows, income, funding_rows, observed_days)
    alerts = _finance_alerts(rows, recurring, spend_rows, income, funding_rows, observed_days)
    funding_flows = _funding_flows(funding_rows, observed_days)
    projections = _projection_lines(user_id, stocks_isa, funding_flows)

    return FinanceIntelligenceSnapshot(
        period_start=period_start,
        period_end=period_end,
        recurring=recurring[:10],
        subscriptions=subscriptions[:10],
        patterns=patterns,
        alerts=alerts[:8],
        funding_flows=funding_flows,
        projections=projections,
    )


def _transaction_rows(user_id: int, *, days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(
                Transaction.booked_at,
                Transaction.amount_minor,
                Transaction.category,
                Transaction.description,
                Account.name,
                Account.kind,
                DataSource.key,
            )
            .select_from(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .outerjoin(DataSource, DataSource.id == Account.source_id)
            .where(Account.user_id == user_id)
            .where(Transaction.booked_at >= since)
            .order_by(Transaction.booked_at)
        ).all()
    return [
        {
            "booked_at": booked_at,
            "amount": amount_minor / 100.0,
            "category": str(category or "uncategorised"),
            "description": str(description or ""),
            "merchant": _merchant_name(str(description or "")),
            "account": str(account or ""),
            "account_kind": str(kind or ""),
            "source_key": str(source_key or ""),
        }
        for booked_at, amount_minor, category, description, account, kind, source_key in rows
    ]


def _recurring_expenses(rows: list[dict]) -> list[RecurringExpenseLine]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["amount"] >= 0:
            continue
        if _is_internal_transfer(row):
            continue
        if _is_account_funding(row) and _funding_destination(row) != "Debt repayment":
            continue
        if row["category"] in {"groceries", "eating_out", "transport"} and not _looks_like_subscription(row["merchant"], row["category"]):
            continue
        merchant = row["merchant"]
        if not merchant or _is_noise_merchant(merchant):
            continue
        groups[_merchant_key(merchant)].append(row)

    lines: list[RecurringExpenseLine] = []
    for items in groups.values():
        if len(items) < 2:
            continue
        items = sorted(items, key=lambda row: row["booked_at"])
        clusters = _payment_clusters(items)
        recurrence_items = [cluster[0] for cluster in clusters]
        amounts = [abs(float(row["amount"])) for row in recurrence_items]
        dates = [row["booked_at"] for row in recurrence_items]
        gaps = [
            (dates[idx] - dates[idx - 1]).days
            for idx in range(1, len(dates))
            if (dates[idx] - dates[idx - 1]).days > 0
        ]
        if len(recurrence_items) < 2:
            continue
        if len(recurrence_items) < 3 and not _looks_like_subscription(items[-1]["merchant"], items[-1]["category"]):
            continue
        cadence_days = _median(gaps) if gaps else None
        cadence_label = _cadence_label(cadence_days, len(recurrence_items))
        subscription_like = _looks_like_subscription(items[-1]["merchant"], items[-1]["category"])
        stable_amount = _stable_amounts(amounts)
        if cadence_label == "irregular" and not subscription_like:
            continue
        if cadence_days is not None and cadence_days < 5 and not stable_amount:
            continue
        if subscription_like and not stable_amount and cadence_days is not None and cadence_days < 20:
            continue
        if not subscription_like and not stable_amount and cadence_label not in {"monthly", "quarterly"}:
            continue
        avg = sum(amounts) / len(amounts)
        monthly = avg if cadence_days is None else avg * 30.4375 / max(cadence_days, 1)
        next_due = dates[-1] + timedelta(days=int(round(cadence_days))) if cadence_days else None
        category = _mode([row["category"] for row in items])
        lines.append(
            RecurringExpenseLine(
                merchant=items[-1]["merchant"],
                category=category,
                average=round(avg, 2),
                monthly_estimate=round(monthly, 2),
                count=len(recurrence_items),
                cadence_label=cadence_label,
                last_seen=dates[-1],
                next_due=next_due,
            )
        )
    return sorted(lines, key=lambda line: line.monthly_estimate, reverse=True)


def _spending_patterns(
    spend_rows: list[dict],
    income_rows: list[dict],
    funding_rows: list[dict],
    observed_days: int,
) -> list[SpendingPatternLine]:
    spend_total = sum(abs(row["amount"]) for row in spend_rows)
    income_total = sum(row["amount"] for row in income_rows)
    funding_total = sum(abs(row["amount"]) for row in funding_rows if row["amount"] < 0)
    monthly_spend = spend_total * 30.4375 / observed_days
    monthly_income = income_total * 30.4375 / observed_days
    monthly_funding = funding_total * 30.4375 / observed_days
    savings_rate = monthly_funding / monthly_income * 100.0 if monthly_income else 0.0

    by_category: dict[str, float] = defaultdict(float)
    for row in spend_rows:
        by_category[row["category"]] += abs(row["amount"])
    top_category, top_value = ("none", 0.0)
    if by_category:
        top_category, top_value = max(by_category.items(), key=lambda item: item[1])

    by_weekday: dict[int, float] = defaultdict(float)
    for row in spend_rows:
        by_weekday[row["booked_at"].weekday()] += abs(row["amount"])
    weekday_label = "n/a"
    if by_weekday:
        weekday_label = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][max(by_weekday, key=by_weekday.get)]

    return [
        SpendingPatternLine(
            "Monthly spend pace",
            _money2(monthly_spend),
            f"{len(spend_rows)} non-transfer spends across {observed_days} days",
            "neutral",
        ),
        SpendingPatternLine(
            "Income pace",
            _money2(monthly_income),
            f"{len(income_rows)} incoming payments excluding self-funding transfers",
            "good" if monthly_income >= monthly_spend else "warning",
        ),
        SpendingPatternLine(
            "Account funding pace",
            _money2(monthly_funding),
            f"{savings_rate:.1f}% of detected income sent to investments/savings/debt pots",
            "good" if savings_rate >= 15 else "neutral",
        ),
        SpendingPatternLine(
            "Largest category",
            top_category.replace("_", " ").title(),
            f"{_money2(top_value * 30.4375 / observed_days)} monthly pace",
            "warning" if top_value else "neutral",
        ),
        SpendingPatternLine(
            "Heaviest spend day",
            weekday_label,
            "Based on non-transfer card/payment spend",
            "neutral",
        ),
    ]


def _finance_alerts(
    rows: list[dict],
    recurring: list[RecurringExpenseLine],
    spend_rows: list[dict],
    income_rows: list[dict],
    funding_rows: list[dict],
    observed_days: int,
) -> list[FinanceAlertLine]:
    alerts: list[FinanceAlertLine] = []
    monthly_income = sum(row["amount"] for row in income_rows) * 30.4375 / observed_days
    monthly_spend = sum(abs(row["amount"]) for row in spend_rows) * 30.4375 / observed_days
    monthly_funding = sum(abs(row["amount"]) for row in funding_rows if row["amount"] < 0) * 30.4375 / observed_days

    if monthly_spend > monthly_income and monthly_income:
        alerts.append(
            FinanceAlertLine(
                "Spending pace above income",
                f"Detected spend pace is {_money2(monthly_spend)} vs income pace {_money2(monthly_income)}.",
                monthly_spend - monthly_income,
                "critical",
            )
        )
    if monthly_funding < monthly_income * 0.1 and monthly_income:
        alerts.append(
            FinanceAlertLine(
                "Low savings/investment rate",
                f"Only {_money2(monthly_funding)} per month is flowing to savings/investments/debt pots.",
                monthly_funding,
                "warning",
            )
        )

    by_date_merchant_amount: dict[tuple[date, str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if row["amount"] < 0:
            key = (row["booked_at"], _merchant_key(row["merchant"]), int(round(abs(row["amount"]) * 100)))
            by_date_merchant_amount[key].append(row)
    for (_day, _merchant, _amount), items in by_date_merchant_amount.items():
        if len(items) >= 2 and abs(items[0]["amount"]) >= 5:
            alerts.append(
                FinanceAlertLine(
                    f"Possible duplicate: {items[0]['merchant']}",
                    f"{len(items)} same-day charges of {_money2(abs(items[0]['amount']))}.",
                    abs(items[0]["amount"]) * len(items),
                    "warning",
                )
            )

    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["amount"] < 0 and _looks_like_subscription(row["merchant"], row["category"]):
            by_merchant[_merchant_key(row["merchant"])].append(row)
    for items in by_merchant.values():
        clusters = _payment_clusters(sorted(items, key=lambda row: row["booked_at"]))
        for cluster in clusters:
            if len(cluster) >= 3:
                total = sum(abs(row["amount"]) for row in cluster)
                start = min(row["booked_at"] for row in cluster)
                end = max(row["booked_at"] for row in cluster)
                alerts.append(
                    FinanceAlertLine(
                        f"Subscription charge burst: {cluster[-1]['merchant']}",
                        f"{len(cluster)} charges between {start:%d %b} and {end:%d %b}.",
                        total,
                        "warning",
                    )
                )

    for line in recurring:
        if line.monthly_estimate >= 100:
            alerts.append(
                FinanceAlertLine(
                    f"Large recurring outflow: {line.merchant}",
                    f"{line.count} payments; estimated {_money2(line.monthly_estimate)} per month.",
                    line.monthly_estimate,
                    "warning",
                )
            )

    recent_cutoff = date.today() - timedelta(days=14)
    for row in sorted(spend_rows, key=lambda item: abs(item["amount"]), reverse=True)[:6]:
        if row["booked_at"] >= recent_cutoff and abs(row["amount"]) >= 100:
            alerts.append(
                FinanceAlertLine(
                    f"Recent large spend: {row['merchant']}",
                    f"{row['booked_at']:%d %b} · {row['category'].replace('_', ' ')}",
                    abs(row["amount"]),
                    "warning",
                )
            )
    return sorted(alerts, key=lambda line: (line.tone != "critical", -line.amount))


def _funding_flows(rows: list[dict], observed_days: int) -> list[FundingFlowLine]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        destination = _funding_destination(row)
        if destination:
            grouped[destination].append(row)
    out: list[FundingFlowLine] = []
    for destination, items in grouped.items():
        # Outbound transfers are money allocated; Trading 212 imported deposits
        # are positive on the target account, so count absolute value either way.
        total = sum(abs(row["amount"]) for row in items)
        monthly = total * 30.4375 / observed_days
        out.append(
            FundingFlowLine(
                destination=destination,
                monthly_rate=round(monthly, 2),
                total=round(total, 2),
                count=len(items),
                last_seen=max(row["booked_at"] for row in items) if items else None,
                source=_mode([row["account"] for row in items]),
            )
        )
    return sorted(out, key=lambda line: line.monthly_rate, reverse=True)


def _projection_lines(
    user_id: int,
    stocks_isa: StocksAndSharesIsaOverview | None,
    funding_flows: list[FundingFlowLine],
) -> list[ProjectionLine]:
    flows = {line.destination: line for line in funding_flows}
    projections: list[ProjectionLine] = []

    if stocks_isa is not None:
        monthly = flows.get("Stocks & Shares ISA").monthly_rate if flows.get("Stocks & Shares ISA") else 0.0
        current_return = _portfolio_return_pct(stocks_isa)
        annual_rate = current_return / 100.0
        projections.append(
            ProjectionLine(
                label="Stocks & Shares ISA",
                value_1y=_future_value(stocks_isa.value, monthly, annual_rate, 12),
                value_3y=_future_value(stocks_isa.value, monthly, annual_rate, 36),
                value_5y=_future_value(stocks_isa.value, monthly, annual_rate, 60),
                monthly_contribution=round(monthly, 2),
                rate_label=f"{current_return:+.1f}% observed return used as annual proxy",
                note="Market returns are volatile; this is a tracking scenario, not advice.",
            )
        )

    lisa = _lisa_projection_base(user_id)
    if lisa is not None:
        monthly = flows.get("LISA").monthly_rate if flows.get("LISA") else 0.0
        # LISA projection includes the UK 25% government bonus on future
        # qualifying contributions, capped by the stored annual allowance.
        annual_allowance_left = max(lisa["allowance_total"] - lisa["allowance_saved"], 0.0)
        eligible_monthly = min(monthly, annual_allowance_left / 12.0) if annual_allowance_left else monthly
        bonus_monthly = eligible_monthly * 0.25
        projections.append(
            ProjectionLine(
                label="Lifetime ISA",
                value_1y=_future_value(lisa["balance"], monthly + bonus_monthly, 0.0, 12),
                value_3y=_future_value(lisa["balance"], monthly + bonus_monthly, 0.0, 36),
                value_5y=_future_value(lisa["balance"], monthly + bonus_monthly, 0.0, 60),
                monthly_contribution=round(monthly, 2),
                rate_label="0.0% growth + estimated 25% LISA bonus on future contributions",
                note="Investment growth is unknown locally; this uses contribution and bonus only.",
            )
        )
    return projections


def _lisa_projection_base(user_id: int) -> dict | None:
    with session_scope() as s:
        rows = s.execute(
            select(Account, BalanceSnapshot)
            .join(BalanceSnapshot, BalanceSnapshot.account_id == Account.id)
            .outerjoin(DataSource, DataSource.id == Account.source_id)
            .where(Account.user_id == user_id)
            .order_by(desc(BalanceSnapshot.snapshot_date), desc(BalanceSnapshot.id))
        ).all()
    for account, snap in rows:
        extra = account.extra or {}
        if extra.get("is_lisa") or "lisa" in account.name.lower() or "lifetime isa" in account.name.lower():
            return {
                "balance": snap.balance_minor / 100.0,
                "allowance_saved": float(extra.get("allowance_saved") or 0.0),
                "allowance_total": float(extra.get("allowance_total") or 4000.0),
            }
    return None


def _portfolio_return_pct(stocks_isa: StocksAndSharesIsaOverview) -> float:
    cost = 0.0
    value = 0.0
    for holding in stocks_isa.holdings:
        row_value = float(holding.get("value") or 0.0)
        row_return = holding.get("return_value")
        if row_return is None:
            continue
        row_cost = row_value - float(row_return)
        if row_cost > 0:
            cost += row_cost
            value += row_value
    if cost <= 0:
        return 0.0
    return round((value - cost) / cost * 100.0, 2)


def _future_value(start: float, monthly: float, annual_rate: float, months: int) -> float:
    monthly_rate = annual_rate / 12.0
    value = float(start)
    for _ in range(months):
        value = value * (1.0 + monthly_rate) + monthly
    return round(value, 2)


def _is_account_funding(row: dict) -> bool:
    text = f"{row['merchant']} {row['description']}".lower()
    if row["source_key"] == "trading212" and row["category"] in {"deposit", "withdrawal"}:
        return True
    if row["amount"] >= 0:
        return False
    return any(
        key in text
        for key in (
            "trading 212",
            "moneybox",
            "lisa",
            "rent & bills",
            "present pot",
            "buffer",
            "macbook",
            "season ticket",
            "zopa",
            "barclaycard",
            "abound",
        )
    )


def _funding_destination(row: dict) -> str:
    text = f"{row['merchant']} {row['description']}".lower()
    if row["source_key"] == "trading212" and row["category"] == "deposit":
        return "Stocks & Shares ISA"
    if "trading 212" in text:
        return "Stocks & Shares ISA"
    if "moneybox" in text or "lisa" in text:
        return "LISA"
    if any(key in text for key in ("zopa", "barclaycard", "abound")):
        return "Debt repayment"
    if "rent & bills" in text:
        return "Bills space"
    if "present pot" in text:
        return "Present pot"
    if "buffer" in text:
        return "Buffer"
    if "macbook" in text:
        return "MacBook space"
    if "season ticket" in text or "motherwell season ticket" in text:
        return "Season ticket space"
    return ""


def _is_self_funding(row: dict) -> bool:
    return _is_internal_transfer(row) or _is_account_funding(row)


def _is_internal_transfer(row: dict) -> bool:
    text = row["description"].lower()
    return "internal_transfer" in text or " - saving" in text


def _looks_like_subscription(merchant: str, category: str) -> bool:
    text = merchant.lower()
    return category == "subscriptions" or any(
        key in text
        for key in (
            "netflix",
            "disney",
            "anthropic",
            "claude",
            "wetransfer",
            "we transfer",
            "apple",
            "itunes",
            "new york times",
            "nyt",
            "gym",
            "giffgaff",
            "sky mobile",
            "spotify",
            "welltv",
        )
    )


def _merchant_name(description: str) -> str:
    parts = [part.strip() for part in description.split(" - ") if part.strip()]
    first = parts[0] if parts else ""
    if len(parts) > 1 and _looks_like_person_name(first):
        second = parts[1]
        if second.lower() not in {"master_card", "faster_payments_out", "faster_payments_in"} and not second.isupper():
            first = f"{first} - {second}"
    first = re.sub(r"\s+", " ", first)
    aliases = {
        "Wetransfer": "WeTransfer",
        "Apple Itunes": "Apple",
        "Apple App Store": "Apple",
        "The New York Times": "New York Times",
        "Pure Gym": "Gym",
        "The Gym Group": "Gym",
    }
    return aliases.get(first, first or "Unknown")


def _merchant_key(merchant: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", merchant.lower()).strip()
    key = key.replace("apple itunes", "apple").replace("apple app store", "apple")
    key = key.replace("pure gym", "gym").replace("the gym group", "gym")
    return key


def _is_noise_merchant(merchant: str) -> bool:
    return _merchant_key(merchant) in {"unknown", "interest on cash"}


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    mid = len(vals) // 2
    if len(vals) % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def _mode(values: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return max(counts.items(), key=lambda item: item[1])[0] if counts else ""


def _cadence_label(days: float | None, count: int) -> str:
    if days is None:
        return "recurring"
    if 5 <= days <= 9:
        return "weekly"
    if 12 <= days <= 17:
        return "fortnightly"
    if 25 <= days <= 36:
        return "monthly"
    if 80 <= days <= 100:
        return "quarterly"
    if count >= 4:
        return f"every {days:.0f}d"
    return "irregular"


def _stable_amounts(amounts: list[float]) -> bool:
    if not amounts:
        return False
    rounded = [round(value, 2) for value in amounts]
    if len(set(rounded)) <= 2:
        return True
    avg = sum(rounded) / len(rounded)
    if avg <= 0:
        return False
    variance = sum((value - avg) ** 2 for value in rounded) / len(rounded)
    return (variance ** 0.5) / avg <= 0.12


def _payment_clusters(items: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for row in items:
        amount = abs(float(row["amount"]))
        if not clusters:
            clusters.append([row])
            continue
        previous = clusters[-1][-1]
        gap = (row["booked_at"] - previous["booked_at"]).days
        previous_amount = abs(float(previous["amount"]))
        similar = previous_amount == 0 or abs(amount - previous_amount) / previous_amount <= 0.05
        if gap <= 7 and similar:
            clusters[-1].append(row)
        else:
            clusters.append([row])
    return clusters


def _looks_like_person_name(text: str) -> bool:
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    return len(words) in {2, 3} and all(word[:1].isupper() for word in words)


def _money2(value: float) -> str:
    return f"£{value:,.2f}"


def provider_plans(user_id: int) -> list[FinanceProviderPlan]:
    """Return readiness cards for the finance connectors ORION supports."""

    with session_scope() as s:
        rows = {
            src.key: src
            for src in s.scalars(
                select(DataSource).where(
                    DataSource.user_id == user_id,
                    DataSource.domain == Domain.finance,
                )
            ).all()
        }

    plans: list[FinanceProviderPlan] = []
    for key, config in _PROVIDER_CATALOG.items():
        source = rows.get(key)
        connected = bool(source and source.status == SourceStatus.connected)
        credential_state = _credential_state(source, config)
        if connected:
            label, tone = "LIVE", "good"
        elif source and source.status == SourceStatus.error:
            label, tone = "ATTENTION", "bad"
        elif credential_state == "stored":
            label, tone = "KEY STORED", "neutral"
        elif credential_state == "token_stored":
            label, tone = "TOKEN STORED", "neutral"
        elif credential_state == "partial":
            label, tone = "PARTIAL KEY", "bad"
        else:
            label, tone = "WAITING", "neutral"
        last_synced = "NEVER"
        if source and source.last_synced_at:
            last_synced = source.last_synced_at.strftime("%d %b %H:%M").upper()
        plans.append(
            FinanceProviderPlan(
                key=key,
                title=config["title"],
                code=config["code"],
                role=config["role"],
                auth_method=config["auth_method"],
                data_scope=config["data_scope"],
                status_label=label,
                tone=tone,
                action_label=(
                    "ROTATE TOKEN"
                    if credential_state == "token_stored"
                    else "ROTATE KEY"
                    if credential_state == "stored"
                    else config["action_label"]
                ),
                required_items=config["required_items"],
                security_note=config["security_note"],
                credential_label=config.get("credential_label", ""),
                credential_fields=tuple(config.get("credential_fields", ())),
                connected=connected,
                source_name=source.name if source else config["title"],
                last_synced_label=last_synced,
            )
        )
    return plans


def store_provider_credential(
    user_id: int,
    provider_key: str,
    field: str,
    secret_value: str,
) -> str:
    """Store one provider credential in Keychain and save only its reference."""

    return store_provider_credentials(user_id, provider_key, {field: secret_value})[field]


def store_provider_credentials(
    user_id: int,
    provider_key: str,
    secrets: dict[str, str],
) -> dict[str, str]:
    """Store provider credentials in Keychain and save only their references."""

    if provider_key not in _PROVIDER_CATALOG:
        raise ValueError(f"Unknown finance provider: {provider_key}")
    allowed_fields = {
        field
        for field, _ in _PROVIDER_CATALOG[provider_key].get("credential_fields", ())
    }
    if not allowed_fields:
        raise ValueError(f"{provider_key} does not accept local credentials yet.")
    unknown = set(secrets) - allowed_fields
    if unknown:
        raise ValueError(f"Unsupported credential field(s): {', '.join(sorted(unknown))}")

    clean_secrets = {field: value.strip() for field, value in secrets.items() if value.strip()}
    missing = allowed_fields - set(clean_secrets)
    if missing:
        raise ValueError(f"Missing credential field(s): {', '.join(sorted(missing))}")

    refs: dict[str, str] = {}
    for field, value in clean_secrets.items():
        secret_name = f"finance.{provider_key}.{field}"
        refs[field] = store_secret(secret_name, value)

    with session_scope() as s:
        source = s.scalars(
            select(DataSource).where(
                DataSource.user_id == user_id,
                DataSource.key == provider_key,
            )
        ).first()
        if source is None:
            source = DataSource(
                user_id=user_id,
                key=provider_key,
                name=_PROVIDER_CATALOG[provider_key]["title"],
                domain=Domain.finance,
                status=SourceStatus.disconnected,
            )
            s.add(source)
            s.flush()
        extra = dict(source.extra or {})
        credential_refs = dict(extra.get("credential_refs") or {})
        credential_refs.update(refs)
        extra["credential_refs"] = credential_refs
        if provider_key == "open_banking" and "access_token" in credential_refs:
            extra["credential_state"] = "token_stored"
        else:
            extra["credential_state"] = (
                "stored" if allowed_fields <= set(credential_refs) else "partial"
            )
        extra["credential_stored_at"] = utcnow().isoformat()
        source.extra = extra
    return refs


def _credential_state(source: DataSource | None, config: dict) -> str:
    if source is None:
        return ""
    stored_state = (source.extra or {}).get("credential_state", "")
    if stored_state == "token_stored":
        return stored_state
    required = {field for field, _ in config.get("credential_fields", ())}
    if not required:
        return stored_state
    refs = (source.extra or {}).get("credential_refs") or {}
    present = required & set(refs)
    if present == required:
        return "stored"
    if present:
        return "partial"
    return ""


def account_readouts(user_id: int) -> list[dict]:
    """Latest account balances with source metadata for the finance page."""

    since = date.today() - timedelta(days=3650)
    with session_scope() as s:
        rows = s.execute(
            select(
                Account.id,
                Account.name,
                Account.kind,
                Account.currency,
                DataSource.key,
                DataSource.name,
                DataSource.status,
                Account.extra,
                BalanceSnapshot.snapshot_date,
                BalanceSnapshot.balance_minor,
            )
            .join(BalanceSnapshot, BalanceSnapshot.account_id == Account.id)
            .outerjoin(DataSource, DataSource.id == Account.source_id)
            .where(Account.user_id == user_id)
            .where(BalanceSnapshot.snapshot_date >= since)
            .order_by(desc(BalanceSnapshot.snapshot_date), desc(BalanceSnapshot.id))
        ).all()
    if not rows:
        return []

    df = pd.DataFrame(
        rows,
        columns=[
            "account_id",
            "name",
            "kind",
            "currency",
            "source_key",
            "source_name",
            "source_status",
            "extra",
            "snapshot_date",
            "balance_minor",
        ],
    )
    latest = df.sort_values("snapshot_date").groupby("account_id", as_index=False).tail(1)
    latest = latest.copy()
    latest["value"] = latest["balance_minor"] / 100.0
    latest["source_status_label"] = latest["source_status"].map(
        lambda status: status.value.upper() if hasattr(status, "value") else "LOCAL"
    )
    return latest.sort_values("value", ascending=False)[
        [
            "account_id",
            "name",
            "kind",
            "currency",
            "source_key",
            "source_name",
            "source_status_label",
            "extra",
            "snapshot_date",
            "value",
        ]
    ].to_dict("records")


# --------------------------------------------------------------------------- #
# Manually-maintained accounts (no provider API): LISA, loans, bills, cards.
# Stored under a single "manual" DataSource so they survive connector syncs.
# --------------------------------------------------------------------------- #

MANUAL_SOURCE_KEY = "manual_finance"

# Account kinds that represent money owed (subtract from net worth).
LIABILITY_KINDS = {"liability", "loan", "bill"}
# Account kind for a revolving credit limit (headroom only; not asset/debt).
CREDIT_FACILITY_KIND = "credit_facility"


def _ensure_manual_source(session, user_id: int) -> DataSource:
    source = session.scalars(
        select(DataSource).where(
            DataSource.user_id == user_id, DataSource.key == MANUAL_SOURCE_KEY
        )
    ).first()
    if source is None:
        source = DataSource(
            user_id=user_id,
            key=MANUAL_SOURCE_KEY,
            name="Manual entry",
            domain=Domain.finance,
            status=SourceStatus.connected,
        )
        session.add(source)
        session.flush()
    return source


def upsert_manual_account(
    user_id: int,
    name: str,
    *,
    kind: str,
    balance: float,
    extra: dict | None = None,
    snapshot_date: date | None = None,
) -> int:
    """Create/update a manually-maintained account and record today's balance.

    ``balance`` is in major units and may be negative (a debt). Returns the
    account id. A matching account is found by (manual source, name).
    """

    snapshot_date = snapshot_date or date.today()
    balance_minor = int(round(balance * 100))
    with session_scope() as s:
        source = _ensure_manual_source(s, user_id)
        account = s.scalars(
            select(Account).where(
                Account.user_id == user_id,
                Account.source_id == source.id,
                Account.name == name,
            )
        ).first()
        if account is None:
            account = Account(
                user_id=user_id,
                source_id=source.id,
                name=name,
                kind=kind,
                currency="GBP",
                extra=extra or {},
            )
            s.add(account)
            s.flush()
        else:
            account.kind = kind
            if extra:
                merged = dict(account.extra or {})
                merged.update(extra)
                account.extra = merged
        existing = s.scalars(
            select(BalanceSnapshot).where(
                BalanceSnapshot.account_id == account.id,
                BalanceSnapshot.snapshot_date == snapshot_date,
            )
        ).first()
        if existing is None:
            s.add(
                BalanceSnapshot(
                    account_id=account.id,
                    snapshot_date=snapshot_date,
                    balance_minor=balance_minor,
                    currency="GBP",
                )
            )
        else:
            existing.balance_minor = balance_minor
        return account.id


def liability_readouts(user_id: int) -> list[LiabilityLine]:
    """Hard debts (loans/bills/cards held with a negative balance)."""

    lines: list[LiabilityLine] = []
    for account in account_readouts(user_id):
        kind = str(account.get("kind") or "")
        value = float(account["value"])
        if kind in LIABILITY_KINDS or value < 0:
            if kind == CREDIT_FACILITY_KIND:
                continue
            lines.append(
                LiabilityLine(
                    name=str(account["name"]),
                    balance=abs(value),
                    kind=kind if kind in LIABILITY_KINDS else "debt",
                    source_label=str(account.get("source_key") or "manual").upper(),
                )
            )
    return sorted(lines, key=lambda r: r.balance, reverse=True)


def credit_facility_readouts(user_id: int) -> list[CreditFacilityLine]:
    """Available credit headroom on cards — spending power, never net worth."""

    lines: list[CreditFacilityLine] = []
    with session_scope() as s:
        rows = s.scalars(
            select(Account).where(
                Account.user_id == user_id, Account.kind == CREDIT_FACILITY_KIND
            )
        ).all()
        for account in rows:
            extra = account.extra or {}
            limit = float(extra.get("credit_limit_minor", 0)) / 100.0
            drawn = float(extra.get("drawn_minor", 0)) / 100.0
            lines.append(
                CreditFacilityLine(
                    name=account.name,
                    available=max(limit - drawn, 0.0),
                    drawn=drawn,
                )
            )
    return sorted(lines, key=lambda r: r.available, reverse=True)


def net_worth_history(user_id: int, *, days: int = 30, fallback: float = 0.0) -> list[float]:
    """Reconstruct daily net worth across the window.

    For each day we take the most recent balance snapshot *as of that day* for
    every account (carrying the last-known value forward), then sum them. This
    draws a continuous trajectory even when accounts snapshot on different days
    or only once — which is why the old "sum snapshots dated exactly today"
    approach left the chart blank. Credit-facility headroom is excluded.
    """

    with session_scope() as s:
        rows = s.execute(
            select(
                BalanceSnapshot.account_id,
                BalanceSnapshot.snapshot_date,
                BalanceSnapshot.balance_minor,
                Account.kind,
            )
            .join(Account, Account.id == BalanceSnapshot.account_id)
            .where(Account.user_id == user_id)
            .where(Account.kind != CREDIT_FACILITY_KIND)
            .order_by(BalanceSnapshot.snapshot_date)
        ).all()

    if not rows:
        return [fallback, fallback]

    # snapshots[account_id] = sorted list of (date, value_major)
    snapshots: dict[int, list[tuple[date, float]]] = {}
    for account_id, snap_date, balance_minor, _kind in rows:
        snapshots.setdefault(account_id, []).append((snap_date, balance_minor / 100.0))

    today = date.today()
    start = today - timedelta(days=days)
    series: list[float] = []
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        total = 0.0
        seen = False
        for points in snapshots.values():
            # latest snapshot on or before `day`
            value = None
            for snap_date, val in points:
                if snap_date <= day:
                    value = val
                else:
                    break
            if value is not None:
                total += value
                seen = True
        if seen:
            series.append(round(total, 2))

    if len(series) < 2:
        # Not enough history yet: anchor a flat 2-point line at current value.
        latest = series[-1] if series else fallback
        return [latest, latest]
    return series


def allocation_by_kind(accounts: list[dict]) -> dict[str, float]:
    allocation: dict[str, float] = {}
    for account in accounts:
        value = max(float(account["value"]), 0.0)
        if not value:
            continue
        key = _allocation_bucket(account)
        allocation[key] = allocation.get(key, 0.0) + value
    return allocation


def _is_lisa(source_key: str, name: str) -> bool:
    name = name.lower()
    return source_key == "moneybox" or "lisa" in name or "lifetime isa" in name


def _allocation_bucket(account: dict) -> str:
    source_key = str(account.get("source_key") or "")
    name = str(account.get("name") or "").lower()
    kind = str(account.get("kind") or "account").replace("_", " ")
    if _is_lisa(source_key, name):
        return "LISA"
    if "cash isa" in name:
        return "Cash ISA"
    if source_key == "trading212":
        return "Investments"
    if kind in {"current", "savings"}:
        return "Cash"
    return kind.title()


def stocks_and_shares_isa_overview(user_id: int) -> StocksAndSharesIsaOverview | None:
    """Live-quote-backed Trading 212 Stocks & Shares ISA overview.

    Read-only: this NEVER hits the network — it returns whatever quotes are
    already cached in the DB so the finance page renders instantly. Refreshing
    stale quotes is done off the UI thread via ``refresh_quotes_async`` (the page
    schedules it and re-renders when fresh values land).
    """

    with session_scope() as s:
        trading212 = s.scalars(
            select(DataSource).where(DataSource.user_id == user_id, DataSource.key == "trading212")
        ).first()
        if trading212 is None:
            return None
        accounts = s.scalars(
            select(Account).where(Account.user_id == user_id, Account.source_id == trading212.id)
        ).all()
        account = next(
            (
                row
                for row in accounts
                if (row.extra or {}).get("statement_label") == "ISA Account"
                or "stocks & shares isa" in row.name.lower()
            ),
            None,
        )
        if account is None:
            return None
        latest = s.scalars(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == account.id)
            .order_by(desc(BalanceSnapshot.snapshot_date), desc(BalanceSnapshot.id))
            .limit(1)
        ).first()
        if latest is None:
            return None
        txns = s.scalars(select(Transaction).where(Transaction.account_id == account.id)).all()

        deposits = sum(t.amount_minor for t in txns if t.category == "deposit" and t.amount_minor > 0)
        withdrawals = abs(sum(t.amount_minor for t in txns if t.category == "withdrawal"))
        interest = sum(t.amount_minor for t in txns if t.category == "interest")
        net_cash_flow = sum(t.amount_minor for t in txns)
        extra = account.extra or {}
        holdings = extra.get("holdings") if isinstance(extra.get("holdings"), list) else []
        investments_minor = extra.get("investments_value_minor")
        investments_value = (
            float(investments_minor) / 100.0
            if investments_minor is not None
            else sum(float(row.get("value") or 0.0) for row in holdings)
        )
        latest_value = latest.balance_minor / 100.0
        cash_minor = extra.get("cash_value_minor")
        cash_value = (
            float(cash_minor) / 100.0
            if cash_minor is not None
            else max(0.0, latest_value - investments_value)
        )
        day_change = round(sum(float(row.get("day_change_value") or 0.0) for row in holdings), 2)
        previous_value = investments_value - day_change
        day_change_pct = round(day_change / previous_value * 100.0, 2) if previous_value else 0.0
        return StocksAndSharesIsaOverview(
            account_name=account.name,
            value=latest_value,
            investments_value=investments_value,
            cash_estimate=cash_value,
            currency=latest.currency,
            snapshot_date=latest.snapshot_date,
            period_start=_date_from_extra(extra.get("statement_period_start")),
            period_end=_date_from_extra(extra.get("statement_period_end")),
            generated_on=_date_from_extra(extra.get("statement_generated_on")),
            deposits=deposits / 100.0,
            withdrawals=withdrawals / 100.0,
            interest=interest / 100.0,
            net_cash_flow=net_cash_flow / 100.0,
            movement_count=len(txns),
            holdings_status=str(extra.get("holdings_status") or "unknown"),
            holdings_captured_on=_date_from_extra(extra.get("holdings_captured_on")),
            quote_refreshed_at=_datetime_from_extra(extra.get("quote_refreshed_at")),
            quote_source=str(extra.get("quote_source") or ""),
            day_change=day_change,
            day_change_pct=day_change_pct,
            holdings=sorted(holdings, key=lambda row: float(row.get("value") or 0.0), reverse=True),
        )


def _risk_snapshot(
    accounts: list[dict],
    net_worth: pd.DataFrame,
    monthly_spend: pd.DataFrame,
    providers: list[FinanceProviderPlan],
) -> FinanceRiskSnapshot:
    cash = sum(
        max(float(a["value"]), 0.0)
        for a in accounts
        if str(a["kind"]) in {"current", "savings"}
        and not _is_lisa(str(a.get("source_key") or ""), str(a.get("name", "")))
    )
    invested = sum(
        max(float(a["value"]), 0.0)
        for a in accounts
        if str(a["kind"]) in {"investment", "crypto"}
        or (str(a.get("source_key")) in {"trading212", "coinbase"} and str(a["kind"]) != "savings")
    )
    lisa = sum(
        max(float(a["value"]), 0.0)
        for a in accounts
        if _is_lisa(str(a.get("source_key") or ""), str(a.get("name", "")))
    )
    debt = abs(sum(min(float(a["value"]), 0.0) for a in accounts))
    burn = float(monthly_spend["spend"].iloc[-1]) if not monthly_spend.empty else 0.0
    total_assets = cash + invested + lisa
    # Net worth is current assets minus current debt — not the daily-sum series,
    # which double-counts/undercounts when accounts snapshot on different days.
    latest = total_assets - debt
    # Trend: compare against the earliest point in the window if we have one.
    first = float(net_worth["value"].iloc[0]) if not net_worth.empty else latest
    delta_pct = (latest - first) / first * 100 if first else 0.0
    runway = cash / burn if burn else 12.0
    live = sum(1 for provider in providers if provider.connected)
    return FinanceRiskSnapshot(
        cash=cash,
        invested=invested,
        lisa=lisa,
        debt=debt,
        monthly_burn=burn,
        runway_months=runway,
        total_assets=total_assets,
        net_worth=latest,
        net_worth_delta_pct=delta_pct,
        live_provider_count=live,
        provider_count=len(providers),
    )


def _finance_metrics(risk: FinanceRiskSnapshot, series: list[float]) -> list[Metric]:
    trend = "up" if risk.net_worth_delta_pct > 0 else "down" if risk.net_worth_delta_pct < 0 else "flat"
    return [
        Metric(
            "Net Worth",
            _money(risk.net_worth),
            f"{risk.net_worth_delta_pct:+.1f}%",
            trend,
            series,
        ),
        Metric("Cash", _money(risk.cash), trend="flat"),
        Metric("Invested", _money(risk.invested), trend="flat"),
        Metric("LISA", _money(risk.lisa), trend="flat"),
        Metric(
            "Debt",
            _money(risk.debt),
            trend="down" if risk.debt else "flat",
            tone="bad" if risk.debt else "neutral",
        ),
    ]


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _date_from_extra(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _datetime_from_extra(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
