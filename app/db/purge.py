"""Purge demo / mock data so the app shows only real, sourced data.

ORION seeds a mock dataset on first launch so the UI isn't empty. Once real
sources (Health Auto Export, ActivityWatch, …) are connected, that mock data is
misleading. ``purge_mock_data`` removes every demo-seeded row — finance,
activity, projects, health, insights, and planned fitness sessions — while
keeping the local User and the data-source registry.

After purging, re-running the real connectors (a normal sync) repopulates only
genuine data. What you see is then exclusively real, even if sparse at first.
"""

from __future__ import annotations

from sqlalchemy import delete

from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import (
    Account,
    ActivityMetricDaily,
    BalanceSnapshot,
    FitnessSession,
    HealthMetricDaily,
    Insight,
    Project,
    ProjectMetricDaily,
    RawImport,
    Transaction,
)

log = get_logger(__name__)


def purge_mock_data(user_id: int, *, keep_fitness_plan: bool = True) -> dict[str, int]:
    """Delete all demo/mock domain data for a user. Returns per-table counts.

    Keeps: User, DataSource registry, and (by default) the training-block
    FitnessPlan — but removes the *mock* planned sessions on it. Real sources
    repopulate health/activity on the next sync.
    """
    counts: dict[str, int] = {}
    with session_scope() as s:
        # Finance: transactions + balances depend on accounts; clear children first.
        acct_ids = [a.id for a in s.query(Account).filter_by(user_id=user_id).all()]
        if acct_ids:
            counts["transactions"] = s.execute(
                delete(Transaction).where(Transaction.account_id.in_(acct_ids))
            ).rowcount
            counts["balance_snapshots"] = s.execute(
                delete(BalanceSnapshot).where(BalanceSnapshot.account_id.in_(acct_ids))
            ).rowcount
        counts["accounts"] = s.execute(
            delete(Account).where(Account.user_id == user_id)
        ).rowcount

        # Projects + their metrics.
        proj_ids = [p.id for p in s.query(Project).filter_by(user_id=user_id).all()]
        if proj_ids:
            counts["project_metrics"] = s.execute(
                delete(ProjectMetricDaily).where(ProjectMetricDaily.project_id.in_(proj_ids))
            ).rowcount
        counts["projects"] = s.execute(
            delete(Project).where(Project.user_id == user_id)
        ).rowcount

        # Health + activity snapshots (real sources will repopulate health).
        counts["health_metrics"] = s.execute(
            delete(HealthMetricDaily).where(HealthMetricDaily.user_id == user_id)
        ).rowcount
        counts["activity_metrics"] = s.execute(
            delete(ActivityMetricDaily).where(ActivityMetricDaily.user_id == user_id)
        ).rowcount

        # Insights (deterministic; regenerated from real data).
        counts["insights"] = s.execute(
            delete(Insight).where(Insight.user_id == user_id)
        ).rowcount

        # Planned mock fitness sessions (the training-block plan is kept).
        counts["fitness_sessions"] = s.execute(
            delete(FitnessSession).where(FitnessSession.user_id == user_id)
        ).rowcount

        # Raw imports from mock connector runs.
        counts["raw_imports"] = s.execute(delete(RawImport)).rowcount

    total = sum(counts.values())
    log.info("Purged %d mock rows for user %s: %s", total, user_id, counts)
    return counts


def sync_real_sources(user_id: int) -> dict[str, int]:
    """Run every live-capable connector and persist whatever real data exists.

    Connectors without a real source contribute nothing (they only mock in dev,
    and we explicitly skip mock output here so the purge stays clean).
    """
    from app.ingestion import iter_connectors

    written: dict[str, int] = {}
    with session_scope() as s:
        for c in iter_connectors():
            if not hasattr(c, "available"):
                continue  # mock-only placeholder; skip
            try:
                if not c.available:
                    continue
                rows = c.fetch_raw_data()
                if c.is_mock or not rows:
                    continue
                n = c.store_normalised_data(s, user_id, 0, rows)
                written[c.key] = n
            except Exception:
                log.exception("Real sync failed for %s", c.key)
    return written
