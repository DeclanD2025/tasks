"""Test fixtures: each test runs against an isolated in-memory-ish SQLite DB.

We point ORION_DATABASE_URL at a temp file before importing the DB layer so the
real per-user database is never touched.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def _temp_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["ORION_DATABASE_URL"] = f"sqlite:///{tmp.name}"
    os.environ["ORION_ENV"] = "development"

    # Import after env is set so settings pick it up.
    from app.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from app.db.seed import seed

    seed(reset=True)
    yield
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
