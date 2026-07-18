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
    # Strength training. `create_all` builds the new tables (programmes, days,
    # items, planned sessions, progression events) but cannot widen the ones
    # that already exist, so every column added to a pre-existing strength
    # table has to be listed here or it silently will not appear in a deployed
    # database — where the tables were created months ago.
    for table, columns in _STRENGTH_COLUMNS.items():
        if table not in tables:
            continue  # create_all will build it complete
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    if not statements:
        _ensure_strength_indexes(engine, tables)
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    log.info("Applied %d additive SQLite migration statements.", len(statements))
    _ensure_strength_indexes(engine, tables)


# SQLite's ALTER TABLE ADD COLUMN cannot add a UNIQUE column and cannot take a
# non-constant default, so uniqueness is applied afterwards as an index and
# JSON columns default to their empty literal.
_STRENGTH_COLUMNS: dict[str, dict[str, str]] = {
    "strength_exercises": {
        "display_name": "VARCHAR(160) NOT NULL DEFAULT ''",
        "aliases": "JSON NOT NULL DEFAULT '[]'",
        "family_slug": "VARCHAR(120) NOT NULL DEFAULT ''",
        "is_compound": "BOOLEAN NOT NULL DEFAULT 0",
        "laterality": "VARCHAR(24) NOT NULL DEFAULT 'bilateral'",
        "load_type": "VARCHAR(24) NOT NULL DEFAULT 'external'",
        "measurement": "VARCHAR(16) NOT NULL DEFAULT 'reps'",
        "default_unit": "VARCHAR(8) NOT NULL DEFAULT 'kg'",
        "increment_kg": "FLOAT NOT NULL DEFAULT 2.5",
        "bar_weight_kg": "FLOAT",
        "instructions": "TEXT NOT NULL DEFAULT ''",
        "setup_notes": "TEXT NOT NULL DEFAULT ''",
        "rom_notes": "TEXT NOT NULL DEFAULT ''",
        "tracking_config": "JSON NOT NULL DEFAULT '{}'",
        "archived_at": "DATETIME",
    },
    "strength_workout_templates": {
        "user_id": "INTEGER REFERENCES users(id)",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "estimated_duration_min": "INTEGER",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "archived_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "strength_template_exercises": {
        "section": "VARCHAR(20) NOT NULL DEFAULT 'main'",
        "superset_group": "VARCHAR(8)",
        "rep_min": "INTEGER",
        "rep_max": "INTEGER",
        "target_weight_kg": "FLOAT",
        "target_rpe": "FLOAT",
        "target_rir": "FLOAT",
        "rest_seconds": "INTEGER",
        "tempo": "VARCHAR(16) NOT NULL DEFAULT ''",
        "progression_rule": "VARCHAR(24) NOT NULL DEFAULT 'manual'",
        "progression_config": "JSON NOT NULL DEFAULT '{}'",
    },
    "strength_workouts": {
        "planned_session_id": "INTEGER REFERENCES strength_planned_sessions(id)",
        "programme_id": "INTEGER REFERENCES strength_programmes(id)",
        "programme_week": "INTEGER",
        "location": "VARCHAR(120) NOT NULL DEFAULT ''",
        "bodyweight_kg": "FLOAT",
        "readiness_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "energy_before": "INTEGER",
        "mood_before": "INTEGER",
        "session_rpe": "FLOAT",
        "pain_notes": "TEXT NOT NULL DEFAULT ''",
        "abandoned_reason": "VARCHAR(200) NOT NULL DEFAULT ''",
        "source": "VARCHAR(24) NOT NULL DEFAULT 'manual'",
        "import_id": "VARCHAR(160)",
        "workout_id": "INTEGER REFERENCES workouts(id)",
    },
    "strength_workout_exercises": {
        "programme_item_id": "INTEGER REFERENCES strength_programme_items(id)",
        "section": "VARCHAR(20) NOT NULL DEFAULT 'main'",
        "superset_group": "VARCHAR(8)",
        "prescription": "JSON NOT NULL DEFAULT '{}'",
        "classification_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "substituted_from_id": "INTEGER REFERENCES strength_exercises(id)",
        "substitution_reason": "VARCHAR(200) NOT NULL DEFAULT ''",
        "technique_rating": "INTEGER",
        "pain_rating": "INTEGER",
        "equipment_variation": "VARCHAR(120) NOT NULL DEFAULT ''",
        "machine_settings": "JSON NOT NULL DEFAULT '{}'",
    },
    "strength_set_entries": {
        "duration_seconds": "FLOAT",
        "distance_m": "FLOAT",
        "bodyweight_factor": "FLOAT",
        "assistance_kg": "FLOAT",
        "bodyweight_kg": "FLOAT",
        "left_reps": "INTEGER",
        "right_reps": "INTEGER",
        "left_weight_kg": "FLOAT",
        "right_weight_kg": "FLOAT",
        "rir": "FLOAT",
        "tempo": "VARCHAR(16) NOT NULL DEFAULT ''",
        "rest_seconds": "FLOAT",
        "to_failure": "BOOLEAN NOT NULL DEFAULT 0",
        "has_partials": "BOOLEAN NOT NULL DEFAULT 0",
        "rom_quality": "VARCHAR(16) NOT NULL DEFAULT ''",
        "parent_set_id": "INTEGER REFERENCES strength_set_entries(id)",
        "superset_group": "VARCHAR(8)",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "source": "VARCHAR(24) NOT NULL DEFAULT 'manual'",
        "client_key": "VARCHAR(64)",
        "voided_at": "DATETIME",
        "void_reason": "VARCHAR(200) NOT NULL DEFAULT ''",
        "edit_history": "JSON NOT NULL DEFAULT '[]'",
    },
    "strength_personal_records": {
        "programme_id": "INTEGER REFERENCES strength_programmes(id)",
        "unit": "VARCHAR(8) NOT NULL DEFAULT 'kg'",
        "qualifier": "FLOAT",
        "calculation_method": "VARCHAR(24) NOT NULL DEFAULT 'measured'",
        "previous_value": "FLOAT",
        "previous_record_id": "INTEGER REFERENCES strength_personal_records(id)",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "invalidated_at": "DATETIME",
    },
}

# Indexes the ORM declares on tables that already existed. `create_all` skips
# an existing table entirely, so these would otherwise never be built on a
# deployed database and every history query would fall back to a table scan.
_STRENGTH_INDEXES: tuple[tuple[str, str], ...] = (
    ("strength_exercises", "CREATE INDEX IF NOT EXISTS ix_strength_exercises_family_slug ON strength_exercises (family_slug)"),
    ("strength_exercises", "CREATE INDEX IF NOT EXISTS ix_strength_exercises_load_type ON strength_exercises (load_type)"),
    ("strength_exercises", "CREATE INDEX IF NOT EXISTS ix_strength_exercises_movement_pattern ON strength_exercises (movement_pattern)"),
    ("strength_workouts", "CREATE INDEX IF NOT EXISTS ix_strength_workout_user_started ON strength_workouts (user_id, started_at)"),
    ("strength_workouts", "CREATE INDEX IF NOT EXISTS ix_strength_workouts_import_id ON strength_workouts (import_id)"),
    ("strength_set_entries", "CREATE INDEX IF NOT EXISTS ix_strength_set_type_completed ON strength_set_entries (set_type, completed)"),
    # Idempotency for set creation: a retry from a phone that lost signal
    # mid-request must collide here rather than write a second set.
    ("strength_set_entries", "CREATE UNIQUE INDEX IF NOT EXISTS uq_strength_set_client_key ON strength_set_entries (client_key) WHERE client_key IS NOT NULL"),
    ("strength_personal_records", "CREATE INDEX IF NOT EXISTS ix_strength_pr_lookup ON strength_personal_records (user_id, exercise_id, record_type, is_active)"),
)


def _ensure_strength_indexes(engine: Engine, tables: set[str]) -> None:
    built = 0
    with engine.begin() as conn:
        for table, statement in _STRENGTH_INDEXES:
            if table not in tables:
                continue
            conn.execute(text(statement))
            built += 1
    if built:
        log.debug("Ensured %d strength indexes.", built)
