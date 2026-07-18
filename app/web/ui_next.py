"""Serve the Next.js front end (`frontend/`) as pre-built static files.

The redesigned UI is exported with `output: "export"` (no Node at runtime), so
the whole thing is plain HTML/JS/CSS that FastAPI can serve directly. This
keeps ORION a single Python container.

It is mounted at a base path (default ``/v2``) rather than at ``/`` because the
legacy Jinja routes (``/health``, ``/training``, ``/money``, …) collide with the
Next routes of the same name, and FastAPI resolves registered routes before
mounts — mounting at ``/`` would leave the Jinja pages shadowing it. Once the
Next UI is wired to real data and the Jinja routers are retired, set
``ORION_UI_BASE_PATH=""`` on both the build and the server to flip it to root.

The mount sits *inside* the session middleware, so the redesigned UI is behind
the same passphrase as everything else.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.logging import get_logger

log = get_logger(__name__)

# Where the export lands. In the container the build stage copies it here; in
# local dev it is `frontend/out` at the repo root.
_CANDIDATES = (
    Path(os.environ.get("ORION_UI_DIR", "")) if os.environ.get("ORION_UI_DIR") else None,
    Path(__file__).resolve().parents[2] / "frontend" / "out",
    Path("/srv/orion/ui"),
)


def ui_base_path() -> str:
    """Base path the Next build was compiled for. Empty string means root."""
    return os.environ.get("ORION_UI_BASE_PATH", "/v2").rstrip("/")


def find_ui_dir() -> Path | None:
    for candidate in _CANDIDATES:
        if candidate and (candidate / "index.html").is_file():
            return candidate
    return None


def mount_next_ui(app: FastAPI) -> str | None:
    """Mount the exported UI if it has been built. Returns the path, or None.

    A missing build is not an error: the Python app is still fully usable via
    the Jinja UI, which is what happens in a plain `pip install` dev checkout
    where nobody has run `pnpm build`.
    """
    ui_dir = find_ui_dir()
    if ui_dir is None:
        log.info("Next UI not built — skipping mount (run `pnpm build` in frontend/)")
        return None

    base = ui_base_path() or "/"
    # html=True resolves `/plan/` to `plan/index.html`, which is the layout the
    # export produces under `trailingSlash: true`.
    app.mount(base, StaticFiles(directory=str(ui_dir), html=True), name="ui_next")
    log.info("Next UI mounted at %s from %s", base, ui_dir)
    return base
