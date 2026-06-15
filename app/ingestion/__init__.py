"""Ingestion: the generic connector interface and pipeline orchestration."""

from app.ingestion.base import Connector, ConnectorResult  # noqa: F401


def __getattr__(name: str):
    # Lazily expose the registry helpers so importing this package (or any
    # connector module) doesn't eagerly build the registry and create import
    # cycles with the integration connectors.
    if name in ("get_connector", "iter_connectors"):
        from app.ingestion import registry

        return getattr(registry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
