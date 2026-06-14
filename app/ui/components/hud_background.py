"""App-wide cinematic HUD backdrop.

Layered, painted behind the whole application:
  1. deep radial vignette
  2. faint coordinate grid (minor + major lines) with edge tick marks
  3. concentric radar rings + sweep ticks around a focal point
  4. a calm twinkling star field
  5. occasional brighter "data points" that pulse and fade
  6. a very subtle noise/dither texture

Low CPU: ~20 fps, fixed-seed field so it doesn't churn. Drawn with
WA_TransparentForMouseEvents so it never intercepts clicks.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.ui.themes.theme import PALETTE


class _Star:
    __slots__ = ("x", "y", "r", "base", "phase", "speed")

    def __init__(self, x, y, r, base):
        self.x, self.y, self.r, self.base = x, y, r, base
        self.phase = random.uniform(0, math.tau)
        self.speed = random.uniform(0.5, 1.7)


class _DataPoint:
    __slots__ = ("x", "y", "phase", "speed", "color")

    def __init__(self, x, y, color):
        self.x, self.y, self.color = x, y, color
        self.phase = random.uniform(0, math.tau)
        self.speed = random.uniform(0.4, 1.0)


class HudBackground(QWidget):
    def __init__(self, parent=None, *, density: int = 160, dim: float = 0.7,
                 grid: bool = True, radar: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._density = density
        self._dim = dim
        self._grid = grid
        self._radar = radar
        self._stars: list[_Star] = []
        self._points: list[_DataPoint] = []
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._t += 0.05
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        self._regenerate()
        super().resizeEvent(event)

    def _regenerate(self):
        rng = random.Random(11)
        w, h = max(self.width(), 1), max(self.height(), 1)
        self._stars = [
            _Star(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.4, 1.3),
                  rng.uniform(0.08, 0.5))
            for _ in range(self._density)
        ]
        palette = [PALETTE.accent, PALETTE.violet, PALETTE.orange, PALETTE.accent]
        self._points = [
            _DataPoint(rng.uniform(0, w), rng.uniform(0, h), rng.choice(palette))
            for _ in range(max(6, self._density // 22))
        ]

    # --- paint ------------------------------------------------------------ #
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if not self._stars:
            self._regenerate()

        # 1. vignette
        grad = QRadialGradient(w * 0.62, h * 0.4, max(w, h) * 0.8)
        grad.setColorAt(0.0, QColor("#05121a"))
        grad.setColorAt(1.0, QColor(PALETTE.bg_void))
        p.fillRect(self.rect(), grad)

        if self._grid:
            self._paint_grid(p, w, h)
        if self._radar:
            self._paint_radar(p, w, h)
        self._paint_stars(p)
        self._paint_data_points(p)
        self._paint_noise(p, w, h)
        p.end()

    def _paint_grid(self, p: QPainter, w: int, h: int):
        step = 46
        minor = QColor(PALETTE.grid)
        minor.setAlpha(int(90 * self._dim))
        p.setPen(QPen(minor, 1.0))
        x = 0
        while x < w:
            p.drawLine(x, 0, x, h)
            x += step
        y = 0
        while y < h:
            p.drawLine(0, y, w, y)
            y += step
        # major lines every 5th
        major = QColor(PALETTE.scan)
        major.setAlpha(int(60 * self._dim))
        p.setPen(QPen(major, 1.0))
        x = 0
        i = 0
        while x < w:
            if i % 5 == 0:
                p.drawLine(x, 0, x, h)
            x += step
            i += 1

    def _paint_radar(self, p: QPainter, w: int, h: int):
        cx, cy = w * 0.62, h * 0.42
        ring = QColor(PALETTE.scan)
        ring.setAlpha(int(55 * self._dim))
        p.setPen(QPen(ring, 1.0))
        for rr in (140, 260, 400, 560):
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        # rotating sweep ticks
        sweep = QColor(PALETTE.accent)
        sweep.setAlpha(int(40 * self._dim))
        p.setPen(QPen(sweep, 1.0))
        for k in range(36):
            a = math.radians(k * 10) + self._t * 0.1
            r1, r2 = 556, 566
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)),
                       QPointF(cx + r2 * math.cos(a), cy + r2 * math.sin(a)))

    def _paint_stars(self, p: QPainter):
        col = QColor(PALETTE.star)
        p.setPen(Qt.NoPen)
        for s in self._stars:
            tw = 0.5 + 0.5 * math.sin(self._t * s.speed + s.phase)
            col.setAlpha(max(0, min(255, int(255 * s.base * tw * self._dim))))
            p.setBrush(col)
            p.drawEllipse(QPointF(s.x, s.y), s.r, s.r)

    def _paint_data_points(self, p: QPainter):
        p.setPen(Qt.NoPen)
        for dp in self._points:
            pulse = 0.5 + 0.5 * math.sin(self._t * dp.speed + dp.phase)
            glow = QRadialGradient(QPointF(dp.x, dp.y), 9)
            c = QColor(dp.color)
            c.setAlpha(int(120 * pulse * self._dim))
            glow.setColorAt(0.0, c)
            edge = QColor(dp.color)
            edge.setAlpha(0)
            glow.setColorAt(1.0, edge)
            p.setBrush(glow)
            p.drawEllipse(QPointF(dp.x, dp.y), 9, 9)
            core = QColor(dp.color)
            core.setAlpha(int(220 * pulse * self._dim))
            p.setBrush(core)
            p.drawEllipse(QPointF(dp.x, dp.y), 1.5, 1.5)

    def _paint_noise(self, p: QPainter, w: int, h: int):
        # cheap static dither: a sparse fixed pattern of faint dots
        rng = random.Random(99)
        nc = QColor(PALETTE.text_faint)
        nc.setAlpha(int(10 * self._dim))
        p.setPen(Qt.NoPen)
        p.setBrush(nc)
        for _ in range(int(w * h / 9000)):
            p.drawRect(QRectF(rng.uniform(0, w), rng.uniform(0, h), 1, 1))
