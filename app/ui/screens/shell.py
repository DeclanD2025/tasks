"""AppShell — the main command-centre window after unlock.

Layout: a dimmed constellation backdrop behind a sidebar + top bar + a stacked
page area. Navigation swaps the visible page and updates the top bar.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
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
from app.ui.motion import prefers_reduced_motion
from app.ui.navigation import NAV_ITEMS
from app.ui.screens.pages import (
    CareerPage,
    DiplomaPage,
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
        self._assembly_effects: dict[QWidget, QGraphicsOpacityEffect] = {}
        self._assembly_anims: list[QParallelAnimationGroup] = []

        # App-wide HUD backdrop behind all mission-control surfaces.
        self._bg = HudBackground(self, density=90, dim=0.62)

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
        self._topbar.settings_requested.connect(lambda: self.show_page("settings"))
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
        self._register("career", CareerPage(self._user_id))
        self._register("diploma", DiplomaPage(self._user_id))
        for item in NAV_ITEMS:
            if item.key in self._pages:
                continue
            self._register(item.key, ModulePage(item.key, self._user_id))

        self.show_page("overview")
        self._prepare_assembly()
        QTimer.singleShot(40, self.play_assembly)

    def _register(self, key: str, widget: QWidget) -> None:
        self._pages[key] = widget
        self._stack.addWidget(widget)

    def show_page(self, key: str) -> None:
        if key not in self._pages:
            return
        self._stack.setCurrentWidget(self._pages[key])
        self._sidebar.select(key)
        item = self._nav_lookup[key]
        if key == "overview":
            self._topbar.set_page("Today", "Your day at a glance.")
        else:
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

    def _prepare_assembly(self) -> None:
        for widget in (self._sidebar, self._topbar):
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            self._assembly_effects[widget] = effect
        if hasattr(self._overview, "prepare_assembly"):
            self._overview.prepare_assembly()

    def play_assembly(self) -> None:
        reduced = prefers_reduced_motion()
        self._animate_surface(
            self._sidebar,
            delay=0,
            offset=QPoint(0, 0) if reduced else QPoint(-34, 0),
            duration=220 if reduced else 520,
        )
        self._animate_surface(
            self._topbar,
            delay=70 if reduced else 180,
            offset=QPoint(0, 0) if reduced else QPoint(0, -22),
            duration=220 if reduced else 500,
        )
        if hasattr(self._overview, "play_assembly"):
            self._overview.play_assembly(reduced=reduced, base_delay=180 if reduced else 430)

    def _animate_surface(
        self,
        widget: QWidget,
        *,
        delay: int,
        offset: QPoint,
        duration: int,
    ) -> None:
        effect = self._assembly_effects.get(widget)
        if effect is None:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            self._assembly_effects[widget] = effect
        final_pos = widget.pos()
        widget.move(final_pos + offset)

        def _start() -> None:
            group = QParallelAnimationGroup(self)
            fade = QPropertyAnimation(effect, b"opacity", group)
            fade.setDuration(duration)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(fade)
            if offset != QPoint(0, 0):
                slide = QPropertyAnimation(widget, b"pos", group)
                slide.setDuration(duration)
                slide.setStartValue(final_pos + offset)
                slide.setEndValue(final_pos)
                slide.setEasingCurve(QEasingCurve.Type.OutCubic)
                group.addAnimation(slide)
            group.finished.connect(lambda: self._assembly_anims.remove(group)
                                   if group in self._assembly_anims else None)
            self._assembly_anims.append(group)
            group.start()

        QTimer.singleShot(delay, _start)
