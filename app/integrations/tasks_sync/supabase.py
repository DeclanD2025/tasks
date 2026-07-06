"""Minimal Supabase (PostgREST) client for the tasks table.

Wraps the handful of REST calls the two-way sync needs. The default project URL
and anon key match the companion tasks web app (they ship publicly in its
``index.html``); both can be overridden via ``ORION_TASKS_SUPABASE_URL`` /
``ORION_TASKS_SUPABASE_KEY`` env vars.

Kept dependency-light (``httpx``) and import-safe so the connector and tests can
run even when offline — network errors surface as exceptions the connector
catches.
"""

from __future__ import annotations

import os

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

# Public anon credentials from the companion tasks app's index.html.
_DEFAULT_URL = "https://hpgalybhcztwzfqoluts.supabase.co"
_DEFAULT_KEY = "sb_publishable_DYz9X1kXSCe15q3xHZ0PMg_R9A2JwSt"


def _config() -> tuple[str, str]:
    url = os.environ.get("ORION_TASKS_SUPABASE_URL", _DEFAULT_URL).rstrip("/")
    key = os.environ.get("ORION_TASKS_SUPABASE_KEY", _DEFAULT_KEY)
    return url, key


class SupabaseTasks:
    """Thin REST wrapper over the Supabase ``tasks`` table."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._url, self._key = _config()
        self._timeout = timeout

    @property
    def base(self) -> str:
        return f"{self._url}/rest/v1/tasks"

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        h = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    # --- reads ------------------------------------------------------------ #
    def list_tasks(self) -> list[dict]:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(
                self.base, params={"select": "*"}, headers=self._headers()
            )
            r.raise_for_status()
            return r.json()

    def ping(self) -> bool:
        """Cheap reachability check used by Settings / connect()."""
        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.get(
                    self.base,
                    params={"select": "id", "limit": 1},
                    headers=self._headers(),
                )
                return r.status_code == 200
        except Exception as exc:  # offline / DNS / etc.
            log.warning("Supabase ping failed: %s", exc)
            return False

    # --- writes ----------------------------------------------------------- #
    def insert(self, row: dict) -> dict | None:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                self.base,
                json=row,
                headers=self._headers(prefer="return=representation"),
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else None

    def update(self, ext_id: str, patch: dict) -> None:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.patch(
                self.base,
                params={"id": f"eq.{ext_id}"},
                json=patch,
                headers=self._headers(prefer="return=minimal"),
            )
            r.raise_for_status()

    def delete(self, ext_id: str) -> None:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.delete(
                self.base,
                params={"id": f"eq.{ext_id}"},
                headers=self._headers(prefer="return=minimal"),
            )
            r.raise_for_status()
