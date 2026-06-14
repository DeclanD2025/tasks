"""Logging configuration for ORION.

Logs go to stderr and a rotating file under the per-user log directory.

IMPORTANT (security): never log raw integration payloads (bank transactions,
health records, tokens) at INFO level in production. Use DEBUG for payload
dumps and keep production at INFO or higher. See `core.security.redact`.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Idempotently configure root logging for the app."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    log_file = settings.log_dir / "orion.log"
    file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
