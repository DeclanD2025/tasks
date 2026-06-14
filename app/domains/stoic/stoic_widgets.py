"""Bespoke painted widgets for the Stoic observatory.

  EudaimoniaGauge   — a large radial index gauge (0..100) with an animated sweep
  ControlGauge      — the dichotomy-of-control split bar (up-to-us vs not)
  LifeWeeksGrid     — memento-mori grid: one cell per week of an assumed lifespan
  MaximPlate        — a quiet, centred maxim with attribution

All custom-painted, deterministic, no network. They reuse the HUD palette.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.themes.theme import PALETTE, TYPE


class EudaimoniaGauge(QWidget):
    """A radial gauge for the composite eudaimonia index (0..100)."""

    def __init__(self, value: float | None, parent=None):
        super().__init__(parent)
        self._has_data = value is not None
        self._value = max(0.0, min(100.0, value or 0.0))
        self._t = 0.0
        self.setMinimumHeight(230)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._t += 0.05
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 + 6
        radius = min(w, h) * 0.38
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        start = 220 * 16          # start angle (lower-left)
        full = -260 * 16          # sweep clockwise
        # track
        track = QPen(QColor(PALETTE.border))
        track.setWidthF(10)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(rect, start, full)
        # value arc
        frac = self._value / 100.0
        col = (PALETTE.coral if self._value < 40 else
               PALETTE.orange if self._value < 60 else PALETTE.accent)
        val = QPen(QColor(col))
        val.setWidthF(10)
        val.setCapStyle(Qt.RoundCap)
        p.setPen(val)
        p.drawArc(rect, start, int(full * frac))

        # animated leading tick
        ang = math.radians(220 - 260 * frac)
        glow = QColor(col)
        glow.setAlpha(int(120 + 80 * (0.5 + 0.5 * math.sin(self._t * 2))))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        lx, ly = cx + radius * math.cos(ang), cy - radius * math.sin(ang)
        p.drawEllipse(QPointF(lx, ly), 6, 6)

        # central readout
        p.setPen(QColor(PALETTE.text))
        f = p.font()
        f.setPointSize(34)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - radius, cy - 30, radius * 2, 44),
                   Qt.AlignCenter, f"{self._value:.0f}" if self._has_data else "—")
        p.setPen(QColor(PALETTE.text_faint))
        f.setPointSize(TYPE.nano)
        f.setBold(False)
        f.setFamily(TYPE.mono.split(",")[0])
        p.setFont(f)
        p.drawText(QRectF(cx - radius, cy + 14, radius * 2, 16),
                   Qt.AlignCenter, "EUDAIMONIA INDEX")
        p.end()


class ControlGauge(QWidget):
    """Dichotomy of control: a split bar of up-to-us vs not-up-to-us."""

    def __init__(self, ratio: float, parent=None):
        super().__init__(parent)
        self._ratio = max(0.0, min(1.0, ratio))
        self.setMinimumHeight(64)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        y, bar_h = 16, 18
        split = int(w * self._ratio)

        p.fillRect(0, y, split - 2, bar_h, QColor(PALETTE.accent))
        p.fillRect(split, y, w - split, bar_h, QColor(PALETTE.bg_elevated))
        # marker
        p.setPen(QPen(QColor(PALETTE.text), 1.4))
        p.drawLine(split, y - 4, split, y + bar_h + 4)

        p.setPen(QColor(PALETTE.accent))
        f = p.font()
        f.setPointSize(TYPE.nano)
        f.setBold(True)
        f.setFamily(TYPE.mono.split(",")[0])
        p.setFont(f)
        p.drawText(0, y + bar_h + 16, f"UP TO US · {self._ratio * 100:.0f}%")
        p.setPen(QColor(PALETTE.text_faint))
        f.setBold(False)
        p.setFont(f)
        msg = "NOT UP TO US · " + f"{(1 - self._ratio) * 100:.0f}%"
        p.drawText(w - 150, y + bar_h + 16, 150, 14, Qt.AlignRight, msg)
        p.end()


class LifeWeeksGrid(QWidget):
    """Memento mori: a grid where each cell is one week of an assumed lifespan."""

    def __init__(self, lived: int, total: int, parent=None):
        super().__init__(parent)
        self._lived = max(0, lived)
        self._total = max(self._lived + 1, total)
        self.setMinimumHeight(150)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        cols = 52                                  # one row per year
        rows = math.ceil(self._total / cols)
        cell = min((w - 6) / cols, (h - 6) / max(rows, 1))
        gap = max(1.0, cell * 0.18)
        size = cell - gap

        for i in range(self._total):
            r, c = divmod(i, cols)
            x = 3 + c * cell
            y = 3 + r * cell
            if i < self._lived:
                col = QColor(PALETTE.accent_dim)
                col.setAlpha(190)
            else:
                col = QColor(PALETTE.border)
                col.setAlpha(120)
            p.fillRect(QRectF(x, y, size, size), col)
        p.end()


class MaximPlate(QWidget):
    """A quiet, centred Stoic maxim with attribution."""

    def __init__(self, text: str, author: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(8)
        quote = QLabel(f"“{text}”")
        quote.setWordWrap(True)
        quote.setAlignment(Qt.AlignCenter)
        quote.setStyleSheet(
            f"color:{PALETTE.text}; font-size:{TYPE.h2}px; font-style:italic;"
        )
        author_l = QLabel(f"— {author.upper()}")
        author_l.setAlignment(Qt.AlignCenter)
        author_l.setObjectName("Mono")
        lay.addStretch(1)
        lay.addWidget(quote)
        lay.addWidget(author_l)
        lay.addStretch(1)
