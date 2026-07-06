"""Backfill completed workouts from the configured Health Auto Export folder."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import services  # noqa: E402
from app.db.database import init_db, session_scope  # noqa: E402
from app.integrations.health_auto_export.connector import HealthAutoExportConnector  # noqa: E402
from app.integrations.health_auto_export.workouts import import_workouts_from_folder  # noqa: E402


def main() -> None:
    init_db()
    user_id = services.get_default_user_id()
    if user_id is None:
        raise SystemExit("No ORION user exists yet.")

    connector = HealthAutoExportConnector()
    folder = connector.folder()
    if folder is None:
        raise SystemExit("No Health Auto Export folder is configured.")

    with session_scope() as session:
        count = import_workouts_from_folder(folder, session, user_id)

    print(f"Imported/updated {count} HAE workouts from {folder}")


if __name__ == "__main__":
    main()
