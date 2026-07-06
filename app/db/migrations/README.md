# Migrations

## MVP (now)

ORION's MVP uses SQLAlchemy `Base.metadata.create_all()` as a lightweight,
zero-config migration mechanism. On launch the app calls
`app.db.database.init_db()` which creates any missing tables. The
`JSON`/`extra` escape-hatch columns on most tables mean additive changes rarely
require a schema change at all.

The CloudKit sync foundation now adds a small versioned SQLite migration layer
on top of this. `app.sync.ensure_sync_foundation()` creates sync devices,
record-name mappings, checkpoints, tombstones, and the pending outbox, then sets
SQLite `PRAGMA user_version` to at least `1`. It is safe to run repeatedly.

To wipe and rebuild the local SQLite DB during development:

```bash
uv run python -m app.db.seed --reset
```

## Scaling up (later)

When the schema starts evolving in non-additive ways, or when switching to
PostgreSQL for the "scalable database option," introduce **Alembic**:

```bash
uv add alembic
alembic init app/db/migrations/alembic
# point sqlalchemy.url at app.core.config.get_settings().resolved_database_url
# set target_metadata = app.db.models.Base.metadata
alembic revision --autogenerate -m "init"
alembic upgrade head
```

At that point, replace the `init_db()` call in `app/main.py` with
`alembic upgrade head`. The models in `app/db/models.py` are the single source
of truth either way.
