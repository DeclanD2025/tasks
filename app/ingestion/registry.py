"""Connector registry.

Central place that knows about every available connector. The scheduler, the
seeder, and the Settings UI all discover connectors through here, so adding an
integration is a one-line change.
"""

from __future__ import annotations

from app.ingestion.base import Connector
from app.integrations.activitywatch.connector import ActivityWatchConnector
from app.integrations.apple_calendar.connector import AppleCalendarConnector
from app.integrations.apple_health.connector import AppleHealthConnector
from app.integrations.coinbase.connector import CoinbaseConnector
from app.integrations.football_manager.connector import FootballManagerConnector
from app.integrations.google_calendar.connector import GoogleCalendarConnector
from app.integrations.health_auto_export.connector import HealthAutoExportConnector
from app.integrations.moneybox.connector import MoneyboxConnector
from app.integrations.notion.connector import NotionConnector
from app.integrations.open_banking.connector import OpenBankingConnector
from app.integrations.tasks_sync.connector import TasksSyncConnector
from app.integrations.trading212.connector import Trading212Connector

_CONNECTOR_CLASSES: list[type[Connector]] = [
    OpenBankingConnector,
    Trading212Connector,
    CoinbaseConnector,
    MoneyboxConnector,
    HealthAutoExportConnector,
    AppleHealthConnector,
    ActivityWatchConnector,
    AppleCalendarConnector,
    GoogleCalendarConnector,
    NotionConnector,
    TasksSyncConnector,
    FootballManagerConnector,
]

_REGISTRY: dict[str, Connector] = {cls.key: cls() for cls in _CONNECTOR_CLASSES}


def get_connector(key: str) -> Connector:
    return _REGISTRY[key]


def iter_connectors() -> list[Connector]:
    return list(_REGISTRY.values())
