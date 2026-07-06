"""Database engine and session management.

Local-first: defaults to a SQLite file under the per-user app-data directory.
Set ``ORION_DATABASE_URL`` to a PostgreSQL URL to scale out later without code
changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Base

log = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _build_engine() -> Engine:
    settings = get_settings()
    url = settings.resolved_database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # Qt runs DB work off the UI thread via jobs/services; allow cross-thread use.
        connect_args["check_same_thread"] = False
    engine = create_engine(url, echo=False, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _rec):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    log.info("Database engine ready (%s)", url.split("://", 1)[0])
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context manager."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (idempotent).

    For the MVP this is the migration mechanism (``create_all``). See
    ``app/db/migrations`` for how this scales to Alembic later.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_additive_columns(engine)
    _ensure_sync_foundation(engine)
    log.info("Schema ensured (create_all).")


def reset_db() -> None:
    """Drop and recreate all tables. Used by the seeder's --reset and tests."""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _ensure_sync_foundation(engine)
    log.info("Schema reset (drop_all + create_all).")


def _ensure_sync_foundation(engine: Engine) -> None:
    """Run sync metadata migrations after the core schema exists."""
    from app.sync.foundation import ensure_sync_foundation

    ensure_sync_foundation(engine)


def _ensure_additive_columns(engine: Engine) -> None:
    """Apply tiny additive SQLite migrations for existing local databases."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    statements: list[str] = []
    if "fitness_sessions" in tables:
        cols = {col["name"] for col in inspector.get_columns("fitness_sessions")}
        if "notes" not in cols:
            statements.append("ALTER TABLE fitness_sessions ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "completed" not in cols:
            statements.append(
                "ALTER TABLE fitness_sessions ADD COLUMN completed BOOLEAN NOT NULL DEFAULT 0"
            )
        if "label" not in cols:
            statements.append(
                "ALTER TABLE fitness_sessions ADD COLUMN label VARCHAR(60) NOT NULL DEFAULT ''"
            )
    if "accounts" in tables:
        cols = {col["name"] for col in inspector.get_columns("accounts")}
        if "extra" not in cols:
            statements.append("ALTER TABLE accounts ADD COLUMN extra JSON NOT NULL DEFAULT '{}'")
    if "fitness_plans" in tables:
        cols = {col["name"] for col in inspector.get_columns("fitness_plans")}
        plan_columns = {
            "purpose": "VARCHAR(120) NOT NULL DEFAULT ''",
            "focus": "VARCHAR(16) NOT NULL DEFAULT 'hybrid'",
            "goal": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in plan_columns.items():
            if name not in cols:
                statements.append(f"ALTER TABLE fitness_plans ADD COLUMN {name} {ddl}")
    if "fitness_card_templates" in tables:
        cols = {col["name"] for col in inspector.get_columns("fitness_card_templates")}
        if "category" not in cols:
            statements.append(
                "ALTER TABLE fitness_card_templates ADD COLUMN category VARCHAR(16) NOT NULL DEFAULT 'cardio'"
            )
    if "mental_checkins" in tables:
        cols = {col["name"] for col in inspector.get_columns("mental_checkins")}
        checkin_columns = {
            "intention": "VARCHAR(300) NOT NULL DEFAULT ''",
            "day_rating": "INTEGER",
            "evening_note": "TEXT NOT NULL DEFAULT ''",
            "extra": "JSON NOT NULL DEFAULT '{}'",
        }
        for name, ddl in checkin_columns.items():
            if name not in cols:
                statements.append(f"ALTER TABLE mental_checkins ADD COLUMN {name} {ddl}")
    if "career_profiles" in tables:
        cols = {col["name"] for col in inspector.get_columns("career_profiles")}
        career_profile_columns = {
            "role_title": "VARCHAR(120) NOT NULL DEFAULT ''",
            "employer": "VARCHAR(120) NOT NULL DEFAULT ''",
            "started_on": "DATE",
            "satisfaction": "INTEGER NOT NULL DEFAULT 50",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "jeopardy": "JSON NOT NULL DEFAULT '{}'",
            "resilience": "JSON NOT NULL DEFAULT '{}'",
            "updated_at": "DATETIME",
        }
        for name, ddl in career_profile_columns.items():
            if name not in cols:
                statements.append(f"ALTER TABLE career_profiles ADD COLUMN {name} {ddl}")
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    log.info("Applied %d additive SQLite migration statements.", len(statements))
