"""Chart panels built on pyqtgraph (fast, native, offline).

  ChartPanel    — titled glass panel wrapping a line/bar plot
  RadarPanel    — a constellation-style radar / spider chart
  TimelinePanel — a horizontal timeline of dated events

All rendering is local; no web view, no network. pyqtgraph is configured to
match the ORION dark palette.
"""

from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.ui.components.widgets import GlassPanel
from app.ui.themes.theme import PALETTE

pg.setConfigOptions(antialias=True, background=None, foreground=PALETTE.text_dim)


def _panel_header(panel: GlassPanel, title: str, note: str = "") -> None:
    row = QHBoxLayout()
    t = QLabel(title)
    t.setObjectName("PanelTitle")
    row.addWidget(t)
    row.addStretch(1)
    if note:
        n = QLabel(note)
        n.setObjectName("Pill")
        row.addWidget(n)
    panel.body.addLayout(row)


class ChartPanel(GlassPanel):
    """Line or bar chart in a glass panel."""

    def __init__(self, title: str, parent=None, *, note: str = ""):
        super().__init__(parent)
        self.setObjectName("ChartPanel")
        _panel_header(self, title, note)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("bottom").setPen(PALETTE.border)
        self.plot.getAxis("left").setPen(PALETTE.border)
        self.plot.getAxis("bottom").setTextPen(PALETTE.text_faint)
        self.plot.getAxis("left").setTextPen(PALETTE.text_faint)
        self.plot.setMinimumHeight(220)
        self.body.addWidget(self.plot)

    def line(self, y, x=None, color: str = PALETTE.accent, fill: bool = True) -> None:
        x = list(range(len(y))) if x is None else x
        pen = pg.mkPen(QColor(color), width=2)
        item = self.plot.plot(x, y, pen=pen)
        if fill:
            fillc = QColor(color)
            fillc.setAlpha(40)
            self.plot.plot(x, y, pen=pen, fillLevel=min(y) if y else 0,
                           brush=pg.mkBrush(fillc))
        return item

    def bars(self, y, x=None, color: str = PALETTE.accent_2) -> None:
        x = list(range(len(y))) if x is None else x
        bg = pg.BarGraphItem(x=x, height=y, width=0.6, brush=QColor(color))
        self.plot.addItem(bg)


class RadarPanel(GlassPanel):
    """Constellation-style radar chart (custom painted)."""

    def __init__(self, title: str, axes: list[str], values: list[float], parent=None):
        super().__init__(parent)
        _panel_header(self, title)
        self._radar = _RadarWidget(axes, values)
        self.body.addWidget(self._radar)


class _RadarWidget(QWidget):
    def __init__(self, axes: list[str], values: list[float], parent=None):
        super().__init__(parent)
        self._axes = axes
        self._values = values  # each 0..1
        self.setMinimumHeight(260)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.36
        n = len(self._axes)
        if n < 3:
            return

        # Concentric rings.
        ring_pen = QPen(QColor(PALETTE.border))
        ring_pen.setWidthF(1.0)
        p.setPen(ring_pen)
        for frac in (0.33, 0.66, 1.0):
            pts = [
                QPointF(cx + radius * frac * math.cos(a), cy + radius * frac * math.sin(a))
                for a in [(-math.pi / 2 + 2 * math.pi * i / n) for i in range(n)]
            ]
            p.drawPolygon(QPolygonF(pts))

        # Spokes + labels.
        for i, axis in enumerate(self._axes):
            a = -math.pi / 2 + 2 * math.pi * i / n
            ex, ey = cx + radius * math.cos(a), cy + radius * math.sin(a)
            p.setPen(QPen(QColor(PALETTE.border)))
            p.drawLine(QPointF(cx, cy), QPointF(ex, ey))
            p.setPen(QPen(QColor(PALETTE.text_faint)))
            lx, ly = cx + (radius + 16) * math.cos(a), cy + (radius + 16) * math.sin(a)
            p.drawText(QPointF(lx - 24, ly), axis[:10])

        # Value polygon.
        vpts = []
        for i, v in enumerate(self._values):
            a = -math.pi / 2 + 2 * math.pi * i / n
            r = radius * max(0.0, min(1.0, v))
            vpts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        poly = QPolygonF(vpts)
        fill = QColor(PALETTE.accent)
        fill.setAlpha(60)
        p.setBrush(fill)
        p.setPen(QPen(QColor(PALETTE.accent), 2))
        p.drawPolygon(poly)
        p.end()


class TimelinePanel(GlassPanel):
    """Horizontal timeline of dated events."""

    def __init__(self, title: str, events: list[tuple[str, str]], parent=None):
        # events: list of (date_label, text)
        super().__init__(parent)
        _panel_header(self, title)
        for date_label, text in events:
            row = QHBoxLayout()
            dot = QLabel("◆")
            dot.setStyleSheet(f"color:{PALETTE.accent_2}; font-size:10px;")
            d = QLabel(date_label)
            d.setObjectName("CardLabel")
            d.setFixedWidth(90)
            t = QLabel(text)
            t.setObjectName("Muted")
            t.setWordWrap(True)
            row.addWidget(dot)
            row.addWidget(d)
            row.addWidget(t, 1)
            self.body.addLayout(row)
