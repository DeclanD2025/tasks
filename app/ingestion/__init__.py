"""Ingestion: the generic connector interface and pipeline orchestration."""

from app.ingestion.base import Connector, ConnectorResult  # noqa: F401
from app.ingestion.registry import get_connector, iter_connectors  # noqa: F401
