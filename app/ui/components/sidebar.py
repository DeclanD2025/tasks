"""Technical control-rail navigation.

A mission-control navigation rail: brand block, nav buttons each with a glyph,
label, module code and a small status indicator, an active-module glow (drawn
under the checked button), and a pulsing "SYSTEMS NOMINAL" footer.
"""

from __future__ import annotations

import random

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.widgets import OrionLogo
from app.ui.navigation import NAV_ITEMS
from app.ui.themes.theme import PALETTE, TYPE

# Mock per-module status (deterministic) for the indicator dots.
_STATUS = {
    "overview": ("nominal", PALETTE.positive),
    "finance": ("nominal", PALETTE.positive),
    "health": ("watch", PALETTE.orange),
    "productivity": ("nominal", PALETTE.positive),
    "creative": ("idle", PALETTE.text_faint),
    "calendar": ("nominal", PALETTE.positive),
    "learning": ("idle", PALETTE.text_faint),
    "stoic": ("active", PALETTE.violet),
    "projects": ("nominal", PALETTE.positive),
    "insights": ("active", PALETTE.accent),
    "settings": ("nominal", PALETTE.positive),
}


class _NavButton(QPushButton):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self._item = item
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(9)

        glyph = QLabel(item.icon)
        glyph.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:14px;")
        lay.addWidget(glyph)

        col = QVBoxLayout()
        col.setSpacing(0)
        label = QLabel(item.label)
        label.setStyleSheet(f"color:inherit; font-size:{TYPE.body}px;")
        code = QLabel(item.code)
        code.setObjectName("ModuleCode")
        col.addWidget(label)
        col.addWidget(code)
        lay.addLayout(col)
        lay.addStretch(1)

        _, color = _STATUS.get(item.key, ("nominal", PALETTE.positive))
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:8px;")
        lay.addWidget(dot)


class Sidebar(QWidget):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(240)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(4)

        lay.addWidget(OrionLogo(tagline=False))
        sysline = QLabel("OBSERVATORY · LOCAL NODE")
        sysline.setObjectName("Mono")
        lay.addWidget(sysline)
        lay.addSpacing(14)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for item in NAV_ITEMS:
            btn = _NavButton(item)
            btn.clicked.connect(lambda _=False, k=item.key: self.navigate.emit(k))
            self._group.addButton(btn)
            self._buttons[item.key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)
        lay.addWidget(_SystemFooter())

    def select(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


class _SystemFooter(QWidget):
    """Pulsing SYSTEMS NOMINAL footer with mini telemetry readouts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)
        self._cpu = random.randint(8, 22)

    def _tick(self):
        self._t += 0.06
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        # top divider
        p.setPen(QPen(QColor(PALETTE.border), 1.0))
        p.drawLine(0, 0, w, 0)

        pulse = 0.5 + 0.5 * math.sin(self._t * 2.2)
        dot = QColor(PALETTE.positive)
        dot.setAlpha(int(140 + 115 * pulse))
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(2, 14, 7, 7)
        glow = QColor(PALETTE.positive)
        glow.setAlpha(int(60 * pulse))
        p.setBrush(glow)
        p.drawEllipse(-1, 11, 13, 13)

        p.setPen(QColor(PALETTE.positive))
        f = p.font()
        f.setPointSize(TYPE.nano)
        f.setBold(True)
        f.setFamily(TYPE.mono.split(",")[0])
        p.setFont(f)
        p.drawText(16, 22, "SYSTEMS NOMINAL")

        p.setPen(QColor(PALETTE.text_faint))
        f.setBold(False)
        p.setFont(f)
        p.drawText(16, 38, f"CPU {self._cpu}%  ·  MEM 41%  ·  JOBS 2")
        p.drawText(16, 50, "UPLINK · LOCAL ONLY")
        p.end()
