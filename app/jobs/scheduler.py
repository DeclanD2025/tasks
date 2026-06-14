"""APScheduler-based background job framework.

The scheduler runs inside the desktop app process on a background thread so the
Qt UI stays responsive. Two job types are registered for the MVP:

  * ``sync_sources``     — runs every connector's mock pipeline and refreshes data
  * ``refresh_insights`` — re-runs the deterministic analytics engine

Each run is recorded in ``scheduled_job_runs`` for observability. Jobs emit no
hosted-LLM calls.

This is structured so it can later be swapped for Celery (the run() functions
are plain callables) without touching the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.analytics import generate_insights
from app.core.logging import get_logger
from app.db.database import session_scope
from app.db.models import (
    DataSource,
    JobStatus,
    ScheduledJobRun,
    SourceStatus,
)
from app.ingestion import iter_connectors
from app.services import get_default_user_id

log = get_logger(__name__)


def _record_run(job_key: str, fn) -> None:
    """Execute ``fn`` and bookkeep a ScheduledJobRun row."""
    with session_scope() as s:
        run = ScheduledJobRun(job_key=job_key, status=JobStatus.running)
        s.add(run)
        s.flush()
        run_id = run.id
    detail, status = "", JobStatus.success
    try:
        detail = fn() or ""
    except Exception as exc:  # pragma: no cover - defensive
        status = JobStatus.failed
        detail = f"{type(exc).__name__}: {exc}"
        log.exception("Job %s failed", job_key)
    with session_scope() as s:
        run = s.get(ScheduledJobRun, run_id)
        if run:
            run.finished_at = datetime.now(timezone.utc)
            run.status = status
            run.detail = detail[:2000]


def job_sync_sources() -> str:
    """Run each connector's pipeline against mock data and update sources."""
    user_id = get_default_user_id()
    if user_id is None:
        return "no user"
    synced = 0
    for connector in iter_connectors():
        with session_scope() as s:
            source = (
                s.query(DataSource)
                .filter_by(user_id=user_id, key=connector.key)
                .one_or_none()
            )
            if source is None:
                source = DataSource(
                    user_id=user_id,
                    key=connector.key,
                    name=connector.name,
                    domain=connector.domain,
                    status=connector.status,
                )
                s.add(source)
                s.flush()
            result = connector.run(s, user_id, source.id)
            source.last_synced_at = datetime.now(timezone.utc)
            source.status = SourceStatus.mock if connector.is_mock else (
                SourceStatus.connected if result.ok else SourceStatus.error
            )
            synced += 1
    return f"synced {synced} sources"


def job_refresh_insights() -> str:
    user_id = get_default_user_id()
    if user_id is None:
        return "no user"
    count = generate_insights(user_id)
    return f"generated {count} insights"


class JobScheduler:
    """Thin wrapper around APScheduler for the app lifecycle."""

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        # Mock sync + insight refresh. Intervals are generous; this is local.
        self._scheduler.add_job(
            lambda: _record_run("sync_sources", job_sync_sources),
            "interval",
            minutes=30,
            id="sync_sources",
            replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: _record_run("refresh_insights", job_refresh_insights),
            "interval",
            minutes=60,
            id="refresh_insights",
            replace_existing=True,
        )
        self._scheduler.start()
        log.info("Scheduler started (sync_sources/30m, refresh_insights/60m).")

    def run_now(self, job_key: str) -> None:
        """Trigger a job immediately (used by the Settings 'Sync now' button)."""
        mapping = {
            "sync_sources": job_sync_sources,
            "refresh_insights": job_refresh_insights,
        }
        if job_key in mapping:
            _record_run(job_key, mapping[job_key])

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("Scheduler stopped.")
