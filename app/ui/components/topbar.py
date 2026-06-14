"""Top bar: page title/subtitle on the left, status + sync on the right."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.themes.theme import PALETTE, TYPE


class TopBar(QWidget):
    sync_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(72)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self._title = QLabel("Overview")
        self._title.setObjectName("PageTitle")
        self._subtitle = QLabel("Mission status across all systems")
        self._subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self._title)
        titles.addWidget(self._subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)

        self._clock = QLabel("")
        self._clock.setStyleSheet(
            f"color:{PALETTE.text_faint}; font-family:{TYPE.mono}; font-size:{TYPE.small}px;"
        )
        lay.addWidget(self._clock)

        sync = QPushButton("⟳  Sync now")
        sync.setObjectName("GhostButton")
        sync.clicked.connect(self.sync_requested.emit)
        lay.addSpacing(14)
        lay.addWidget(sync)
        self._refresh_clock()

    def set_page(self, title: str, subtitle: str) -> None:
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._refresh_clock()

    def _refresh_clock(self) -> None:
        self._clock.setText(datetime.now().strftime("%a %d %b · %H:%M"))
