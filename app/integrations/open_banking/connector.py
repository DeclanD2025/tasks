"""Starling Bank Personal Access Token connector.

Reads accounts, balances and feed items from Starling's Public API using a
Personal Access Token stored in macOS Keychain. The connector keeps the legacy
``open_banking`` key so existing ORION finance rows continue to work, but the
provider is Starling rather than an aggregator.

Raw bank API payloads are not persisted to SQLite. ORION stores normalized
accounts, balance snapshots and transactions only.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import read_secret
from app.db.models import Account, BalanceSnapshot, Domain, Transaction
from app.ingestion.base import Connector

log = get_logger(__name__)

API_BASE = os.environ.get("ORION_STARLING_API_BASE", "https://api.starlingbank.com/api/v2")
TIMEOUT = 12.0
ACCESS_SECRET = "finance.open_banking.access_token"


class OpenBankingConnector(Connector):
    key = "open_banking"
    name = "Starling Bank"
    domain = Domain.finance
    is_mock = True

    def connect(self) -> bool:
        if _live_disabled_for_tests():
            self.is_mock = True
            return True
        has_token = bool(read_secret(ACCESS_SECRET))
        self.is_mock = not has_token
        return has_token or not get_settings().is_production

    def fetch_raw_data(self) -> list[dict]:
        if not _live_disabled_for_tests():
            token = read_secret(ACCESS_SECRET)
            if token:
                self.is_mock = False
                return self._fetch_live(token)
        self.is_mock = True
        if get_settings().is_production:
            return []
        return self._fetch_mock()

    def store_raw_data(self, session, source_id: int, payloads: list[dict]) -> int:
        """Do not persist full bank API payloads; normalized rows are enough."""
        return 0

    def store_normalised_data(self, session, user_id, source_id, records) -> int:
        accounts: dict[str, Account] = {}
        written = 0

        for record in records:
            if record.get("record_type") != "account":
                continue
            provider_id = record["provider_account_id"]
            account = self._account_for_provider_id(session, user_id, source_id, provider_id)
            if account is None:
                account = Account(
                    user_id=user_id,
                    source_id=source_id,
                    name=record["name"],
                    kind=record["kind"],
                    currency=record["currency"],
                    extra={},
                )
                session.add(account)
                session.flush()
            account.name = record["name"]
            account.kind = record["kind"]
            account.currency = record["currency"]
            extra = dict(account.extra or {})
            extra.update(
                {
                    "provider": "starling_bank",
                    "provider_account_id": provider_id,
                    "default_category_uid": record.get("default_category_uid"),
                    "account_type": record.get("account_type"),
                }
            )
            account.extra = extra
            accounts[provider_id] = account
            written += 1

        for record in records:
            provider_id = record.get("provider_account_id")
            account = accounts.get(provider_id)
            if account is None and provider_id:
                account = self._account_for_provider_id(session, user_id, source_id, provider_id)
                if account is not None:
                    accounts[provider_id] = account
            if account is None:
                continue

            if record.get("record_type") == "balance":
                extra = dict(account.extra or {})
                for source_key, dest_key in [
                    ("available_to_spend_minor", "starling_available_to_spend_minor"),
                    ("spaces_balance_minor", "starling_spaces_balance_minor"),
                    ("cleared_balance_minor", "starling_cleared_balance_minor"),
                    ("total_effective_balance_minor", "starling_total_effective_balance_minor"),
                ]:
                    if record.get(source_key) is not None:
                        extra[dest_key] = record[source_key]
                if record.get("spaces") is not None:
                    extra["starling_spaces"] = record["spaces"]
                extra["starling_balance_basis"] = record.get("balance_basis", "total_effective_balance")
                account.extra = extra

                existing = session.scalars(
                    select(BalanceSnapshot).where(
                        BalanceSnapshot.account_id == account.id,
                        BalanceSnapshot.snapshot_date == record["snapshot_date"],
                    )
                ).first()
                if existing is None:
                    session.add(
                        BalanceSnapshot(
                            account_id=account.id,
                            snapshot_date=record["snapshot_date"],
                            balance_minor=record["balance_minor"],
                            currency=record["currency"],
                        )
                    )
                else:
                    existing.balance_minor = record["balance_minor"]
                    existing.currency = record["currency"]
                written += 1

            elif record.get("record_type") == "transaction":
                if self._transaction_exists(session, account.id, record):
                    continue
                session.add(
                    Transaction(
                        account_id=account.id,
                        booked_at=record["booked_at"],
                        amount_minor=record["amount_minor"],
                        currency=record["currency"],
                        category=record["category"],
                        description=record["description"][:255],
                        extra={
                            "provider": "starling_bank",
                            "external_id": record["external_id"],
                            "fingerprint": record["fingerprint"],
                            "booking_status": record.get("booking_status", "booked"),
                        },
                    )
                )
                written += 1
        session.flush()
        return written

    def _fetch_live(self, token: str) -> list[dict]:
        accounts_payload = self._get(token, "/accounts")
        accounts = accounts_payload.get("accounts") or []
        rows: list[dict] = []

        for account in accounts:
            account_uid = str(account.get("accountUid") or "").strip()
            if not account_uid:
                continue
            category_uid = str(
                account.get("defaultCategory")
                or account.get("defaultCategoryUid")
                or account.get("categoryUid")
                or ""
            ).strip()
            currency = str(account.get("currency") or "GBP")
            rows.append(
                {
                    "record_type": "account",
                    "provider_account_id": account_uid,
                    "default_category_uid": category_uid,
                    "account_type": account.get("accountType"),
                    "name": _account_label(account),
                    "kind": _account_kind(account),
                    "currency": currency,
                }
            )
            spaces = self._fetch_savings_goals(token, account_uid)
            rows.extend(self._fetch_balance(token, account_uid, currency, spaces))
            if category_uid:
                rows.extend(self._fetch_feed_items(token, account_uid, category_uid, currency))

        log.info("Starling Bank: fetched %d account(s)", len(accounts))
        return rows

    def _fetch_balance(
        self,
        token: str,
        account_uid: str,
        default_currency: str,
        spaces: list[dict] | None = None,
    ) -> list[dict]:
        payload = self._get(token, f"/accounts/{account_uid}/balance")
        total_effective = payload.get("totalEffectiveBalance") or {}
        effective = payload.get("effectiveBalance") or {}
        cleared = payload.get("clearedBalance") or payload.get("amount") or payload.get("balance") or {}
        amount = total_effective or effective or cleared
        amount_minor = _minor_units(amount)
        if amount_minor is None:
            return []
        available_minor = _minor_units(effective)
        total_effective_minor = _minor_units(total_effective)
        cleared_minor = _minor_units(cleared)
        space_rows = spaces or []
        spaces_minor = sum(int(row.get("saved_minor") or 0) for row in space_rows)
        if total_effective_minor is not None and available_minor is not None:
            spaces_minor = max(total_effective_minor - available_minor, spaces_minor)
        return [
            {
                "record_type": "balance",
                "provider_account_id": account_uid,
                "snapshot_date": date.today(),
                "balance_minor": amount_minor,
                "currency": amount.get("currency") or default_currency,
                "balance_basis": "total_effective_balance" if total_effective else "effective_balance",
                "available_to_spend_minor": available_minor,
                "spaces_balance_minor": spaces_minor,
                "cleared_balance_minor": cleared_minor,
                "total_effective_balance_minor": total_effective_minor,
                "spaces": space_rows,
            }
        ]

    def _fetch_savings_goals(self, token: str, account_uid: str) -> list[dict]:
        payload = self._get_optional(token, f"/account/{account_uid}/savings-goals")
        goals = payload.get("savingsGoalList") or []
        out: list[dict] = []
        for goal in goals:
            if str(goal.get("state") or "").upper() not in {"", "ACTIVE"}:
                continue
            amount = goal.get("totalSaved") or goal.get("savedAmount") or goal.get("amount") or {}
            saved_minor = _minor_units(amount)
            if saved_minor is None:
                continue
            out.append(
                {
                    "uid_tail": str(goal.get("savingsGoalUid") or goal.get("uid") or "")[-6:],
                    "name": str(goal.get("name") or "Space")[:80],
                    "saved_minor": saved_minor,
                    "currency": amount.get("currency") or "GBP",
                }
            )
        return out

    def _fetch_feed_items(
        self,
        token: str,
        account_uid: str,
        category_uid: str,
        default_currency: str,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=90)
        query = urlencode(
            {
                "minTransactionTimestamp": _starling_timestamp(start),
                "maxTransactionTimestamp": _starling_timestamp(now),
            }
        )
        payload = self._get(
            token,
            f"/feed/account/{account_uid}/category/{category_uid}/transactions-between?{query}",
        )
        return [
            row
            for item in payload.get("feedItems") or []
            if (row := _transaction_record(account_uid, item, default_currency)) is not None
        ]

    def _get(self, token: str, path: str) -> dict:
        req = Request(
            f"{API_BASE}{path}",
            headers={
                "accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="GET",
        )
        with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (fixed HTTPS API host)
            return json.loads(resp.read().decode("utf-8"))

    def _get_optional(self, token: str, path: str) -> dict:
        try:
            return self._get(token, path)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.info("Starling Bank: optional endpoint unavailable for %s (%s)", path, type(exc).__name__)
            return {}

    @staticmethod
    def _account_for_provider_id(session, user_id: int, source_id: int, provider_id: str):
        rows = session.scalars(
            select(Account).where(Account.user_id == user_id, Account.source_id == source_id)
        ).all()
        for row in rows:
            if (row.extra or {}).get("provider_account_id") == provider_id:
                return row
        return None

    @staticmethod
    def _transaction_exists(session, account_id: int, record: dict) -> bool:
        rows = session.scalars(
            select(Transaction).where(
                Transaction.account_id == account_id,
                Transaction.booked_at == record["booked_at"],
            )
        ).all()
        for row in rows:
            extra = row.extra or {}
            if extra.get("external_id") == record["external_id"]:
                return True
            if extra.get("fingerprint") == record["fingerprint"]:
                return True
        return False

    def _fetch_mock(self) -> list[dict]:
        today = date.today()
        merchants = [
            ("Tesco", "groceries", -3500),
            ("Pret", "eating_out", -650),
            ("Spotify", "subscriptions", -1199),
            ("Salary", "income", 250000),
            ("TfL", "transport", -540),
        ]
        rows = [
            {
                "record_type": "account",
                "provider_account_id": "mock-starling-current",
                "default_category_uid": "mock-category",
                "account_type": "PRIMARY",
                "name": "Starling Current Account",
                "kind": "current",
                "currency": "GBP",
            }
        ]
        running = 320_000
        for i in range(30):
            day = today - timedelta(days=i)
            name, cat, base = random.choice(merchants)
            jitter = 0 if cat == "income" else random.randint(-300, 300)
            amount = base + jitter
            running += amount
            tx = {
                "record_type": "transaction",
                "provider_account_id": "mock-starling-current",
                "booked_at": day,
                "amount_minor": amount,
                "currency": "GBP",
                "category": cat,
                "description": name,
                "external_id": f"mock-{day.isoformat()}-{i}",
                "fingerprint": f"mock-{day.isoformat()}-{i}",
                "booking_status": "booked",
            }
            rows.append(tx)
            rows.append(
                {
                    "record_type": "balance",
                    "provider_account_id": "mock-starling-current",
                    "snapshot_date": day,
                    "balance_minor": running,
                    "currency": "GBP",
                }
            )
        return rows


def _transaction_record(account_uid: str, item: dict, default_currency: str) -> dict | None:
    amount = item.get("amount") or item.get("sourceAmount") or {}
    amount_minor = _minor_units(amount)
    if amount_minor is None:
        return None
    if str(item.get("direction") or "").upper() == "OUT":
        amount_minor = -abs(amount_minor)
    elif str(item.get("direction") or "").upper() == "IN":
        amount_minor = abs(amount_minor)

    booked_at = _parse_date(
        item.get("transactionTime")
        or item.get("settlementTime")
        or item.get("updatedAt")
        or item.get("createdAt")
    )
    description = _transaction_description(item)
    external_id = _transaction_external_id(item)
    fingerprint = _fingerprint(
        account_uid,
        booked_at.isoformat(),
        str(amount_minor),
        amount.get("currency") or default_currency,
        description,
        external_id,
    )
    return {
        "record_type": "transaction",
        "provider_account_id": account_uid,
        "booked_at": booked_at,
        "amount_minor": amount_minor,
        "currency": amount.get("currency") or default_currency,
        "category": _category(item, description, amount_minor),
        "description": description,
        "external_id": external_id or fingerprint,
        "fingerprint": fingerprint,
        "booking_status": str(item.get("status") or "booked").lower(),
    }


def _minor_units(amount: dict) -> int | None:
    value = amount.get("minorUnits")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value) -> date:
    if not value:
        return date.today()
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return datetime.now(timezone.utc).date()


def _account_label(account: dict) -> str:
    label = (
        account.get("name")
        or account.get("accountType")
        or account.get("accountIdentifier")
        or "Starling Account"
    )
    return str(label).replace("_", " ").title()[:120]


def _account_kind(account: dict) -> str:
    text = " ".join(
        str(account.get(k) or "")
        for k in ("accountType", "name", "accountSubType")
    ).lower()
    if "saving" in text or "space" in text:
        return "savings"
    if "credit" in text or "card" in text:
        return "credit"
    return "current"


def _transaction_description(item: dict) -> str:
    parts = [
        item.get("counterPartyName"),
        item.get("reference"),
        item.get("source"),
        item.get("spendingCategory"),
    ]
    text = " - ".join(str(p).strip() for p in parts if str(p or "").strip())
    return text or "Starling transaction"


def _transaction_external_id(item: dict) -> str:
    for key in ("feedItemUid", "transactionUid", "paymentOrderUid", "roundUpGoalUid"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _category(item: dict, description: str, amount_minor: int) -> str:
    starling_category = str(item.get("spendingCategory") or "").lower()
    if amount_minor > 0:
        return "income"
    if starling_category in {"groceries", "shopping", "eating_out", "transport"}:
        return starling_category
    text = description.lower()
    if any(k in text for k in ("tesco", "sainsbury", "asda", "aldi", "lidl", "morrisons")):
        return "groceries"
    if any(k in text for k in ("tfl", "train", "uber", "bolt", "transport")):
        return "transport"
    if any(k in text for k in ("spotify", "netflix", "apple.com", "subscription")):
        return "subscriptions"
    if any(k in text for k in ("pret", "cafe", "restaurant", "deliveroo", "ubereats")):
        return "eating_out"
    return "uncategorised"


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _starling_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _live_disabled_for_tests() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)
