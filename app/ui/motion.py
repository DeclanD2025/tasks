"""Motion preference helpers for ORION UI animations."""

from __future__ import annotations

from functools import lru_cache
import os
import platform
import subprocess


@lru_cache(maxsize=1)
def prefers_reduced_motion() -> bool:
    """Return True when the user has requested calmer UI motion.

    Qt exposes contrast accessibility hints but not a portable reduce-motion
    property in the PySide version ORION ships with. We honour an env override
    for tests/development and the macOS system preference used by the desktop
    app's primary target.
    """
    override = os.environ.get("ORION_REDUCED_MOTION")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}

    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.2,
            )
        except Exception:
            return False
        return result.stdout.strip() in {"1", "true", "TRUE"}

    return False
