"""Health dashboard service boundary."""

from __future__ import annotations

from app import services
from app.domains.health.health_schema import HealthDashboardSnapshot
from app.domains.health.local_health_repository import LocalHealthRepository


def get_health_dashboard_snapshot(user_id: int | None = None) -> HealthDashboardSnapshot:
    """Return the read model consumed by the Health telemetry page.

    Hydrated from real local data only (Health Auto Export → SQLite). Missing
    metrics render as "—"/NO DATA rather than fabricated values.
    """
    uid = user_id if user_id is not None else services.get_default_user_id()
    return LocalHealthRepository().dashboard_snapshot(uid)
