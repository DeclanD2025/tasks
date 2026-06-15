"""Mock data seeder.

Populates the local database with a realistic demo dataset so the desktop UI
has something to show on first launch. Pulls payloads from each placeholder
connector's ``fetch_raw_data()`` and maps them into the normalised /
snapshot tables.

Usage:
    uv run python -m app.db.seed            # seed if empty
    uv run python -m app.db.seed --reset    # drop, recreate, reseed
    uv run python -m app.db.seed --force    # reseed without dropping schema

This separates demo data from real data: everything written here is mock and
clearly originates from connectors with status=mock.
"""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import select

from app.analytics import generate_insights
from app.core.logging import get_logger
from app.db.database import init_db, reset_db, session_scope
from app.db.models import (
    Account,
    ActivityMetricDaily,
    BalanceSnapshot,
    DataSource,
    HealthMetricDaily,
    Project,
    ProjectMetricDaily,
    SourceStatus,
    Transaction,
    User,
)
from app.ingestion import get_connector, iter_connectors

log = get_logger(__name__)

DEMO_EMAIL = "operator@orion.local"


def _ensure_user(s) -> User:
    user = s.scalars(select(User).where(User.email == DEMO_EMAIL)).first()
    if user is None:
        user = User(email=DEMO_EMAIL, display_name="Operator")
        s.add(user)
        s.flush()
    return user


def _ensure_sources(s, user_id: int) -> dict[str, int]:
    keys: dict[str, int] = {}
    for c in iter_connectors():
        src = s.scalars(
            select(DataSource).where(DataSource.user_id == user_id, DataSource.key == c.key)
        ).first()
        if src is None:
            src = DataSource(
                user_id=user_id, key=c.key, name=c.name, domain=c.domain,
                status=SourceStatus.mock,
            )
            s.add(src)
            s.flush()
        keys[c.key] = src.id
    return keys


def _seed_finance(s, user_id: int, source_ids: dict[str, int]) -> None:
    # Current account from Open Banking transactions.
    current = Account(user_id=user_id, source_id=source_ids["open_banking"],
                      name="Current Account", kind="current", currency="GBP")
    s.add(current)
    s.flush()
    txns = get_connector("open_banking").fetch_raw_data()
    running = 320_000
    by_day: dict[date, int] = {}
    for t in sorted(txns, key=lambda x: x["date"]):
        d = date.fromisoformat(t["date"])
        s.add(Transaction(account_id=current.id, booked_at=d,
                          amount_minor=t["amount_minor"], currency="GBP",
                          category=t["category"], description=t["merchant"]))
        running += t["amount_minor"]
        by_day[d] = running
    for d, bal in by_day.items():
        s.add(BalanceSnapshot(account_id=current.id, snapshot_date=d,
                              balance_minor=bal, currency="GBP"))

    # Investment / crypto / savings balance accounts.
    for key, name, kind in [
        ("trading212", "Trading 212", "investment"),
        ("coinbase", "Coinbase", "crypto"),
        ("moneybox", "Moneybox", "savings"),
    ]:
        acct = Account(user_id=user_id, source_id=source_ids[key], name=name,
                       kind=kind, currency="GBP")
        s.add(acct)
        s.flush()
        for row in get_connector(key).fetch_raw_data():
            s.add(BalanceSnapshot(account_id=acct.id,
                                  snapshot_date=date.fromisoformat(row["day"]),
                                  balance_minor=row["balance_minor"], currency="GBP"))


def _seed_health(s, user_id: int) -> None:
    for row in get_connector("apple_health").fetch_raw_data():
        extra = {}
        for k in ("mood", "mindful_minutes", "distance_km", "vo2max"):
            if row.get(k) is not None:
                extra[k] = row[k]
        s.add(HealthMetricDaily(
            user_id=user_id, day=date.fromisoformat(row["day"]),
            sleep_minutes=row["sleep_minutes"], hrv_ms=row["hrv_ms"],
            resting_hr=row["resting_hr"], weight_kg=row["weight_kg"],
            extra=extra,
        ))


def _seed_activity(s, user_id: int) -> None:
    # Merge ActivityWatch (deep work) with FM training load by day.
    aw = {r["day"]: r for r in get_connector("activitywatch").fetch_raw_data()}
    fm = {r["day"]: r for r in get_connector("football_manager").fetch_raw_data()}
    for day_iso, r in aw.items():
        load = fm.get(day_iso, {}).get("training_load")
        s.add(ActivityMetricDaily(
            user_id=user_id, day=date.fromisoformat(day_iso),
            steps=r.get("steps"), active_minutes=r.get("active_minutes"),
            deep_work_minutes=r.get("deep_work_minutes"), training_load=load,
        ))


def _seed_projects(s, user_id: int) -> None:
    notion = get_connector("notion").fetch_raw_data()
    for pname in ["ORION", "Fitba Foundry", "ARGUS"]:
        proj = Project(user_id=user_id, name=pname, status="active")
        s.add(proj)
        s.flush()
        for row in notion:
            words = row["words_written"]
            tasks = row["tasks_done"]
            # Momentum 0..100 from words + tasks (deterministic, no LLM).
            momentum = min(100.0, words / 18.0 + tasks * 4.0)
            s.add(ProjectMetricDaily(
                project_id=proj.id, day=date.fromisoformat(row["day"]),
                words_written=words, tasks_done=tasks,
                commits=tasks, momentum=round(momentum, 1),
            ))


def seed(*, reset: bool = False, force: bool = False) -> None:
    if reset:
        reset_db()
    else:
        init_db()

    with session_scope() as s:
        user = _ensure_user(s)
        already = s.scalars(
            select(BalanceSnapshot).limit(1)
        ).first() is not None
        if already and not force and not reset:
            log.info("Data already present; skipping seed (use --force/--reset).")
            return
        source_ids = _ensure_sources(s, user.id)
        _seed_finance(s, user.id, source_ids)
        _seed_health(s, user.id)
        _seed_activity(s, user.id)
        _seed_projects(s, user.id)
        user_id = user.id

    count = generate_insights(user_id)
    log.info("Seed complete. Generated %d insights.", count)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ORION with mock demo data.")
    parser.add_argument("--reset", action="store_true", help="drop & recreate schema")
    parser.add_argument("--force", action="store_true", help="reseed even if data exists")
    args = parser.parse_args()
    seed(reset=args.reset, force=args.force)


if __name__ == "__main__":
    main()
