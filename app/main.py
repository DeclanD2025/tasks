"""ORION desktop application entry point.

Launches the native Qt window, ensures the local database exists (and is seeded
with demo data on first run), starts the background scheduler, and shows the
star-field login screen followed by the command-centre shell.

Run:
    uv run orion
    # or
    uv run python -m app.main
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from app.core.config import asset_path, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.database import init_db
from app.db.seed import seed
from app.jobs import JobScheduler
from app.services import get_default_user_id
from app.ui.screens.login import LoginScreen
from app.ui.screens.shell import AppShell
from app.ui.themes.theme import build_stylesheet

log = get_logger(__name__)


class RootWindow(QMainWindow):
    def __init__(self, scheduler: JobScheduler):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle("ORION — Personal Observability Platform")
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)

        self._scheduler = scheduler
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._login = LoginScreen()
        self._login.unlocked.connect(self._enter)
        self._stack.addWidget(self._login)
        self._stack.setCurrentWidget(self._login)

    def _enter(self) -> None:
        shell = AppShell(self._scheduler)
        self._stack.addWidget(shell)
        self._stack.setCurrentWidget(shell)


def _bootstrap_data() -> None:
    """Ensure schema + demo data exist on first launch (idempotent)."""
    init_db()
    if get_default_user_id() is None:
        log.info("First run: seeding demo data.")
        seed()


def main() -> int:
    configure_logging()
    settings = get_settings()
    log.info("Starting ORION (%s)", settings.env)

    _bootstrap_data()

    app = QApplication(sys.argv)
    app.setApplicationName("ORION")
    icon_file = asset_path("ui", "assets", "orion.icns")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))
    app.setStyleSheet(build_stylesheet())

    scheduler = JobScheduler()
    scheduler.start()
    app.aboutToQuit.connect(scheduler.shutdown)

    window = RootWindow(scheduler)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
