"""Command-centre side navigation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.widgets import OrionLogo
from app.ui.navigation import NAV_ITEMS


class Sidebar(QWidget):
    navigate = Signal(str)  # emits NavItem.key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(232)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 22, 16, 18)
        lay.setSpacing(6)

        brand = OrionLogo(tagline=True)
        lay.addWidget(brand)
        lay.addSpacing(18)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for item in NAV_ITEMS:
            btn = QPushButton(f"  {item.icon}   {item.label}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=item.key: self.navigate.emit(k))
            self._group.addButton(btn)
            self._buttons[item.key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)
        status = QLabel("● SYSTEMS NOMINAL")
        status.setObjectName("Faint")
        status.setStyleSheet("color:#3ad6a0; font-size:10px; letter-spacing:1px;")
        lay.addWidget(status)

    def select(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
