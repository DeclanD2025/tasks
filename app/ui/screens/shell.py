"""AppShell — the main command-centre window after unlock.

Layout: a dimmed constellation backdrop behind a sidebar + top bar + a stacked
page area. Navigation swaps the visible page and updates the top bar.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.jobs import JobScheduler
from app.services import get_default_user_id
from app.ui.components.hud_background import HudBackground
from app.ui.components.sidebar import Sidebar
from app.ui.components.topbar import TopBar
from app.ui.navigation import NAV_ITEMS
from app.ui.screens.pages import (
    FitnessPage,
    InsightsPage,
    ModulePage,
    OverviewPage,
    SettingsPage,
    StoicPage,
)


class AppShell(QWidget):
    def __init__(self, scheduler: JobScheduler, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._user_id = get_default_user_id()
        self._nav_lookup = {n.key: n for n in NAV_ITEMS}

        # App-wide HUD backdrop behind all mission-control surfaces.
        self._bg = HudBackground(self, density=150, dim=0.62)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.navigate.connect(self.show_page)
        root.addWidget(self._sidebar)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._topbar = TopBar()
        self._topbar.sync_requested.connect(self._sync_now)
        rl.addWidget(self._topbar)

        self._stack = QStackedWidget()
        rl.addWidget(self._stack, 1)
        root.addWidget(right, 1)

        # Build pages lazily into the stack, keyed by nav key.
        self._pages: dict[str, QWidget] = {}
        self._overview = OverviewPage(self._user_id)
        self._overview.open_module.connect(self.show_page)
        self._register("overview", self._overview)
        self._register("insights", InsightsPage(self._user_id))
        self._register("settings", SettingsPage())
        self._stoic = StoicPage(self._user_id)
        self._register("stoic", self._stoic)
        self._register("fitness", FitnessPage(self._user_id))
        for item in NAV_ITEMS:
            if item.key in self._pages:
                continue
            self._register(item.key, ModulePage(item.key, self._user_id))

        self.show_page("overview")

    def _register(self, key: str, widget: QWidget) -> None:
        self._pages[key] = widget
        self._stack.addWidget(widget)

    def show_page(self, key: str) -> None:
        if key not in self._pages:
            return
        self._stack.setCurrentWidget(self._pages[key])
        self._sidebar.select(key)
        item = self._nav_lookup[key]
        self._topbar.set_page(item.label, item.subtitle)

    def _sync_now(self) -> None:
        self._scheduler.run_now("sync_sources")
        self._scheduler.run_now("refresh_insights")
        # Refresh data-backed pages.
        self._overview._user_id = get_default_user_id()
        self._overview.refresh()
        insights = self._pages.get("insights")
        if isinstance(insights, InsightsPage):
            insights.refresh()
        if isinstance(self._pages.get("stoic"), StoicPage):
            self._stoic._user_id = get_default_user_id()
            self._stoic.refresh()

    def resizeEvent(self, event):  # noqa: N802
        self._bg.setGeometry(self.rect())
        self._bg.lower()
        super().resizeEvent(event)
