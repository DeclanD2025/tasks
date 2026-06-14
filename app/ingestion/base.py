"""Generic connector interface.

Every integration implements the same lifecycle so the scheduler and UI can
treat them uniformly. The pipeline mirrors ORION's data layers:

    connect()              -> establish/verify access (OAuth, token, file path)
    fetch_raw_data()       -> pull untouched payloads from the source     (L1)
    store_raw_data()       -> persist them as RawImport rows              (L1)
    normalise_data()       -> map payloads to normalised records          (L2)
    store_normalised_data()-> persist normalised records                  (L2)
    update_snapshots()     -> roll up into daily snapshots                (L3)
    generate_metrics()     -> compute derived metrics                     (L4)

`run()` executes the whole pipeline and returns a ConnectorResult.

For this scaffold phase, concrete connectors return mock data and most steps
are no-ops or simple persistence. Real API calls are intentionally NOT made.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Domain, RawImport, SourceStatus

log = get_logger(__name__)


@dataclass
class ConnectorResult:
    connector_key: str
    raw_records: int = 0
    normalised_records: int = 0
    snapshots: int = 0
    metrics: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    ok: bool = True
    detail: str = ""


class Connector(abc.ABC):
    """Base class for all ORION data connectors."""

    #: stable identifier, e.g. "trading212"
    key: str = "base"
    #: human label, e.g. "Trading 212"
    name: str = "Base Connector"
    #: which ORION domain this feeds
    domain: Domain = Domain.finance
    #: whether this connector currently only produces mock data
    is_mock: bool = True

    # --- lifecycle hooks (override in subclasses) -------------------------- #
    def connect(self) -> bool:
        """Verify access. Mock connectors are always 'connected'.

        TODO(security): real connectors should load tokens from the OS keychain
        (keyring), never from the DB or logs, and perform OAuth/consent flows.
        """
        return True

    @abc.abstractmethod
    def fetch_raw_data(self) -> list[dict]:
        """Return a list of raw payload dicts (mock data in this phase)."""

    def store_raw_data(self, session: Session, source_id: int, payloads: list[dict]) -> int:
        rows = [RawImport(source_id=source_id, payload=p) for p in payloads]
        session.add_all(rows)
        session.flush()
        return len(rows)

    def normalise_data(self, payloads: list[dict]) -> list[dict]:
        """Map raw payloads to normalised dict records. Default: passthrough."""
        return payloads

    def store_normalised_data(
        self, session: Session, user_id: int, source_id: int, records: list[dict]
    ) -> int:
        """Persist normalised records. Default no-op; override per domain."""
        return 0

    def update_snapshots(self, session: Session, user_id: int) -> int:
        """Roll normalised records into daily snapshots. Default no-op."""
        return 0

    def generate_metrics(self, session: Session, user_id: int) -> int:
        """Compute derived metrics. Default no-op."""
        return 0

    # --- orchestration ----------------------------------------------------- #
    def run(self, session: Session, user_id: int, source_id: int) -> ConnectorResult:
        result = ConnectorResult(connector_key=self.key)
        try:
            if not self.connect():
                result.ok = False
                result.detail = "connect() failed"
                return result

            payloads = self.fetch_raw_data()
            result.raw_records = self.store_raw_data(session, source_id, payloads)

            records = self.normalise_data(payloads)
            result.normalised_records = self.store_normalised_data(
                session, user_id, source_id, records
            )
            result.snapshots = self.update_snapshots(session, user_id)
            result.metrics = self.generate_metrics(session, user_id)
            result.detail = "mock run" if self.is_mock else "live run"
        except Exception as exc:  # pragma: no cover - defensive
            result.ok = False
            result.detail = f"{type(exc).__name__}: {exc}"
            log.exception("Connector %s failed", self.key)
        finally:
            result.finished_at = datetime.now(timezone.utc)
        return result

    @property
    def status(self) -> SourceStatus:
        return SourceStatus.mock if self.is_mock else SourceStatus.connected
