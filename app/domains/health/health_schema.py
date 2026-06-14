"""Typed read models for the Health dashboard.

The UI consumes these dataclasses only. Mock data, local database data, and a
future Apple Health importer can all hydrate this same shape.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthMetricCard:
    key: str
    label: str
    code: str
    side: str
    value: str
    unit: str
    secondary_value: str
    secondary_label: str
    score: float
    target_region: str
    sparkline: tuple[float, ...]
    status: str = ""
    warning: bool = False


@dataclass(frozen=True)
class BioSystemBar:
    label: str
    value: int


@dataclass(frozen=True)
class HealthDashboardSnapshot:
    title: str
    subtitle: str
    scan_status: str
    sync_status: str
    database_status: str
    last_sync_time: str
    last_sync_date: str
    data_sources_online: int
    data_sources_total: int
    anomaly_count: int
    body_battery_value: str
    body_battery_status: str
    metric_cards: tuple[HealthMetricCard, ...]
    bio_systems: tuple[BioSystemBar, ...]
    live_feed: tuple[float, ...]
