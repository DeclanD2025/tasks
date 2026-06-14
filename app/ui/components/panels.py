"""Composite HUD panels and the mission header.

  SystemHeader          — mission header: title, timestamp, sync state, DB status
  BiometricPanel        — medical-HUD biometric radar/silhouette placeholder
  FinanceTerminalPanel  — market-intelligence allocation donut + readouts
  VitalsStrip           — a row of compact metric cells inside a HudPanel
  ZoneDistribution      — a horizontal stacked-zone bar (training zones / risk)

These compose the primitives in `hud.py` and `viz.py`.
"""

from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.hud import HudPanel, MetricCell, StatusPill
from app.services import Metric
from app.ui.themes.theme import PALETTE, TYPE


# --------------------------------------------------------------------------- #
# Mission header
# --------------------------------------------------------------------------- #
class SystemHeader(QWidget):
    """A full-width mission header bar for module pages."""

    def __init__(self, title: str, code: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 8)
        lay.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(1)
        t = QLabel(title.upper())
        t.setStyleSheet(
            f"color:{PALETTE.text}; font-size:{TYPE.h1}px; font-weight:700; letter-spacing:2px;"
        )
        sub = QLabel(f"MODULE {code}  ·  ORION OBSERVATORY")
        sub.setObjectName("Mono")
        left.addWidget(t)
        left.addWidget(sub)
        lay.addLayout(left)
        lay.addStretch(1)

        self._clock = QLabel("")
        self._clock.setObjectName("Mono")
        lay.addWidget(self._clock)
        lay.addWidget(_VSep())
        lay.addWidget(StatusPill("SYNC OK", PALETTE.positive))
        lay.addWidget(StatusPill("DB LOCAL", PALETTE.accent))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()

    def _refresh(self):
        self._clock.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S  UTC%z").strip())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        y = self.height() - 3
        pen = QPen(QColor(PALETTE.border))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(2, y, self.width() - 2, y)
        # accent tick at the left
        p.setPen(QPen(QColor(PALETTE.accent), 2.0))
        p.drawLine(2, y, 60, y)
        p.end()


class _VSep(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(1)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(0, 4, 1, self.height() - 8, QColor(PALETTE.border))
        p.end()


# --------------------------------------------------------------------------- #
# Vitals strip
# --------------------------------------------------------------------------- #
class VitalsStrip(HudPanel):
    """A HudPanel containing a horizontal row of MetricCells."""

    def __init__(self, title: str, code: str, cells: list[tuple[str, Metric]], parent=None):
        super().__init__(title, code, parent)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        for i, (cell_code, metric) in enumerate(cells):
            if i:
                hl.addWidget(_VSep())
                hl.addSpacing(12)
            cell = MetricCell(metric, cell_code)
            hl.addWidget(cell, 1)
            if i < len(cells) - 1:
                hl.addSpacing(12)
        self.body.addWidget(row)


# --------------------------------------------------------------------------- #
# Biometric panel (medical HUD)
# --------------------------------------------------------------------------- #
class BiometricPanel(HudPanel):
    """Central biometric panel: a radar-style scan over a human silhouette."""

    def __init__(self, scores: dict[str, float], parent=None):
        super().__init__("BIOMETRIC SCAN", "HLT-CORE", parent, status="LIVE")
        self._scan = _BiometricScan(scores)
        self.body.addWidget(self._scan)


class _BiometricScan(QWidget):
    def __init__(self, scores: dict[str, float], parent=None):
        super().__init__(parent)
        self._scores = scores
        self._t = 0.0
        self.setMinimumHeight(300)
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
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.42

        # concentric scan rings
        for i, rr in enumerate((radius, radius * 0.72, radius * 0.44)):
            ring = QColor(PALETTE.accent)
            ring.setAlpha(40 - i * 8)
            p.setPen(QPen(ring, 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        # rotating sweep wedge
        sweep_angle = self._t * 40 % 360
        sweep = QColor(PALETTE.accent)
        sweep.setAlpha(70)
        p.setPen(QPen(sweep, 1.6))
        a = math.radians(sweep_angle)
        p.drawLine(QPointF(cx, cy), QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a)))

        # crosshairs
        cross = QColor(PALETTE.border)
        cross.setAlpha(160)
        p.setPen(QPen(cross, 1.0))
        p.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        p.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))

        # simple human silhouette (head + torso) as a glyph
        sil = QColor(PALETTE.accent)
        sil.setAlpha(120)
        p.setPen(QPen(sil, 1.6))
        p.setBrush(Qt.NoBrush)
        head_r = radius * 0.13
        p.drawEllipse(QPointF(cx, cy - radius * 0.42), head_r, head_r)
        p.drawLine(QPointF(cx, cy - radius * 0.42 + head_r), QPointF(cx, cy + radius * 0.32))
        p.drawLine(QPointF(cx, cy - radius * 0.18), QPointF(cx - radius * 0.26, cy + radius * 0.04))
        p.drawLine(QPointF(cx, cy - radius * 0.18), QPointF(cx + radius * 0.26, cy + radius * 0.04))
        p.drawLine(QPointF(cx, cy + radius * 0.32), QPointF(cx - radius * 0.18, cy + radius * 0.62))
        p.drawLine(QPointF(cx, cy + radius * 0.32), QPointF(cx + radius * 0.18, cy + radius * 0.62))

        # vital markers pinned around the body
        markers = list(self._scores.items())
        for i, (name, score) in enumerate(markers):
            ma = -math.pi / 2 + 2 * math.pi * i / max(1, len(markers))
            mx = cx + radius * 0.9 * math.cos(ma)
            my = cy + radius * 0.9 * math.sin(ma)
            col = (
                PALETTE.positive
                if score >= 0.66
                else (PALETTE.orange if score >= 0.4 else PALETTE.coral)
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(mx, my), 3, 3)
            p.setPen(QColor(PALETTE.text_dim))
            f = p.font()
            f.setPointSize(TYPE.nano)
            p.setFont(f)
            p.drawText(QPointF(mx - 14, my - 6), name.upper())
        p.end()


# --------------------------------------------------------------------------- #
# Finance terminal panel (allocation donut)
# --------------------------------------------------------------------------- #
class FinanceTerminalPanel(HudPanel):
    def __init__(self, allocation: dict[str, float], parent=None):
        super().__init__("ASSET ALLOCATION", "FIN-ALLOC", parent, status="LIVE")
        self._donut = _AllocationDonut(allocation)
        self.body.addWidget(self._donut)


class _AllocationDonut(QWidget):
    _COLORS = [PALETTE.accent, PALETTE.violet, PALETTE.positive, PALETTE.orange, PALETTE.coral]

    def __init__(self, allocation: dict[str, float], parent=None):
        super().__init__(parent)
        self._alloc = allocation
        self.setMinimumHeight(240)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w * 0.34, h / 2
        radius = min(w, h) * 0.36
        total = sum(self._alloc.values()) or 1.0

        start = 90 * 16
        for i, (name, val) in enumerate(self._alloc.items()):
            span = -int(360 * 16 * val / total)
            col = QColor(self._COLORS[i % len(self._COLORS)])
            pen = QPen(col)
            pen.setWidthF(radius * 0.34)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rect = (int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
            p.drawArc(*rect, start, span)
            start += span

        # centre readout
        p.setPen(QColor(PALETTE.text))
        f = p.font()
        f.setPointSize(TYPE.h2)
        f.setBold(True)
        p.setFont(f)
        p.drawText(int(cx - 62), int(cy - 4), 124, 18, Qt.AlignCenter, "PORTFOLIO")
        p.setPen(QColor(PALETTE.text_faint))
        f.setPointSize(TYPE.nano)
        f.setBold(False)
        p.setFont(f)
        p.drawText(int(cx - 62), int(cy + 12), 124, 14, Qt.AlignCenter, "ALLOCATION")

        # legend on the right
        lx, ly = w * 0.62, cy - radius
        f.setPointSize(TYPE.small)
        p.setFont(f)
        for i, (name, val) in enumerate(self._alloc.items()):
            col = QColor(self._COLORS[i % len(self._COLORS)])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRect(int(lx), int(ly + i * 26), 9, 9)
            p.setPen(QColor(PALETTE.text_dim))
            p.drawText(
                int(lx + 16), int(ly + i * 26 + 9), f"{name.upper()}  {val / total * 100:.0f}%"
            )
        p.end()


# --------------------------------------------------------------------------- #
# Zone distribution bar
# --------------------------------------------------------------------------- #
class ZoneDistribution(HudPanel):
    def __init__(self, title: str, code: str, zones: list[tuple[str, float, str]], parent=None):
        # zones: (label, fraction 0..1, color)
        super().__init__(title, code, parent)
        self._bar = _ZoneBar(zones)
        self.body.addWidget(self._bar)


class _ZoneBar(QWidget):
    def __init__(self, zones, parent=None):
        super().__init__(parent)
        self._zones = zones
        self.setMinimumHeight(54)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        bar_h = 16
        y = 8
        x = 0
        total = sum(z[1] for z in self._zones) or 1.0
        for label, frac, color in self._zones:
            seg = (frac / total) * w
            p.fillRect(int(x), y, int(seg) - 2, bar_h, QColor(color))
            p.setPen(QColor(PALETTE.text_faint))
            f = p.font()
            f.setPointSize(TYPE.nano)
            p.setFont(f)
            p.drawText(int(x), y + bar_h + 14, f"{label.upper()} {frac / total * 100:.0f}%")
            x += seg
        p.end()
