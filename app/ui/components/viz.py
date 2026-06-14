"""HUD data-visualisation components (custom-painted, no web view).

  SignalLineChart   — a technical line/area chart: grid, ticks, axis readouts,
                      glowing trace + leading marker. Replaces the plain pyqtgraph
                      panel for the HUD look.
  DomainConstellation — a network/constellation map of life domains; node size
                      encodes momentum/importance, lines encode cross-domain links.
  InsightFeed       — a stacked feed of deterministic insight rows with severity
                      labels, module codes and timestamps.
  RadarDial         — a small constellation-style radar (spider) used in panels.

All local; pandas/numbers in, pixels out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.components.hud import severity_color
from app.ui.themes.theme import PALETTE, TYPE


# --------------------------------------------------------------------------- #
# Signal line chart
# --------------------------------------------------------------------------- #
class SignalLineChart(QWidget):
    def __init__(
        self,
        series: list[float],
        parent=None,
        *,
        color: str | None = None,
        unit: str = "",
        height: int = 150,
    ):
        super().__init__(parent)
        self._series = list(series)
        self._color = color or PALETTE.accent
        self._unit = unit
        self.setMinimumHeight(height)

    def set_series(self, series: list[float]):
        self._series = list(series)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 4, 44, 8, 16

        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        # background grid
        grid = QColor(PALETTE.grid)
        grid.setAlpha(150)
        p.setPen(QPen(grid, 1.0))
        for i in range(5):
            y = pad_t + plot_h * i / 4
            p.drawLine(QPointF(pad_l, y), QPointF(pad_l + plot_w, y))
        for i in range(7):
            x = pad_l + plot_w * i / 6
            p.drawLine(QPointF(x, pad_t), QPointF(x, pad_t + plot_h))

        if len(self._series) < 2:
            p.end()
            return

        lo, hi = min(self._series), max(self._series)
        rng = (hi - lo) or 1.0
        n = len(self._series)
        pts = [
            QPointF(pad_l + i / (n - 1) * plot_w, pad_t + plot_h - (v - lo) / rng * plot_h)
            for i, v in enumerate(self._series)
        ]

        # area fill
        fill = QColor(self._color)
        fill.setAlpha(38)
        area = QPolygonF(
            [QPointF(pts[0].x(), pad_t + plot_h)] + pts + [QPointF(pts[-1].x(), pad_t + plot_h)]
        )
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawPolygon(area)

        # trace
        pen = QPen(QColor(self._color))
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))

        # leading marker + glow
        last = pts[-1]
        glow = QColor(self._color)
        glow.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(last, 5, 5)
        p.setBrush(QColor(self._color))
        p.drawEllipse(last, 2.4, 2.4)

        # axis readouts (hi/lo) on the right
        p.setPen(QColor(PALETTE.text_faint))
        f = p.font()
        f.setPointSize(TYPE.nano)
        f.setFamily(TYPE.mono.split(",")[0])
        p.setFont(f)
        p.drawText(QPointF(pad_l + plot_w + 6, pad_t + 8), f"{hi:,.0f}{self._unit}")
        p.drawText(QPointF(pad_l + plot_w + 6, pad_t + plot_h), f"{lo:,.0f}{self._unit}")
        p.end()


# --------------------------------------------------------------------------- #
# Domain constellation / network map
# --------------------------------------------------------------------------- #
@dataclass
class DomainNode:
    key: str
    label: str
    momentum: float  # 0..1 -> node size / brightness


_DEFAULT_LINKS = [
    ("health", "productivity"),
    ("productivity", "projects"),
    ("projects", "creative"),
    ("creative", "learning"),
    ("finance", "projects"),
    ("calendar", "productivity"),
    ("learning", "finance"),
    ("health", "calendar"),
]


class DomainConstellation(QWidget):
    """Animated network map: domains as nodes, relationships as links."""

    def __init__(self, nodes: list[DomainNode], parent=None, links=None):
        super().__init__(parent)
        self._nodes = nodes
        self._links = links or _DEFAULT_LINKS
        self._t = 0.0
        self.setMinimumHeight(360)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._t += 0.05
        self.update()

    def _layout(self, w, h):
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.34
        pos = {}
        n = len(self._nodes)
        for i, node in enumerate(self._nodes):
            a = -math.pi / 2 + 2 * math.pi * i / n
            # slight breathing motion
            rr = radius * (1 + 0.02 * math.sin(self._t + i))
            pos[node.key] = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
        return pos, QPointF(cx, cy)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        pos, centre = self._layout(w, h)

        # central core ring
        ring = QColor(PALETTE.accent)
        ring.setAlpha(50)
        p.setPen(QPen(ring, 1.0))
        p.setBrush(Qt.NoBrush)
        for rr in (26, 40):
            p.drawEllipse(centre, rr, rr)
        core_glow = QColor(PALETTE.accent)
        core_glow.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(core_glow)
        p.drawEllipse(centre, 12, 12)
        p.setBrush(QColor(PALETTE.accent))
        p.drawEllipse(centre, 3.5, 3.5)

        # spokes from core to each node
        spoke = QColor(PALETTE.border)
        spoke.setAlpha(120)
        p.setPen(QPen(spoke, 1.0))
        for node in self._nodes:
            p.drawLine(centre, pos[node.key])

        # cross-domain links (violet, animated dash)
        link = QColor(PALETTE.violet)
        link.setAlpha(110)
        lpen = QPen(link, 1.2)
        lpen.setDashPattern([4, 6])
        lpen.setDashOffset(-self._t * 8)
        p.setPen(lpen)
        for a, b in self._links:
            if a in pos and b in pos:
                p.drawLine(pos[a], pos[b])

        # nodes
        for node in self._nodes:
            pt = pos[node.key]
            size = 5 + node.momentum * 12
            pulse = 0.6 + 0.4 * math.sin(self._t * 1.4 + hash(node.key) % 5)
            glow = QColor(PALETTE.accent)
            glow.setAlpha(int(90 * node.momentum * pulse))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(pt, size * 2.4, size * 2.4)
            p.setBrush(QColor(PALETTE.bg_panel))
            p.setPen(QPen(QColor(PALETTE.accent), 1.4))
            p.drawEllipse(pt, size, size)
            # label
            p.setPen(QColor(PALETTE.text_dim))
            f = p.font()
            f.setPointSize(TYPE.nano)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QPointF(pt.x() - 24, pt.y() + size + 13), node.label.upper())
            # momentum readout
            p.setPen(QColor(PALETTE.text_faint))
            f.setBold(False)
            p.setFont(f)
            p.drawText(QPointF(pt.x() - 24, pt.y() + size + 24), f"{node.momentum * 100:.0f}%")
        p.end()


# --------------------------------------------------------------------------- #
# Insight feed
# --------------------------------------------------------------------------- #
class InsightFeed(QWidget):
    """A vertical feed of insight rows with severity labels + codes."""

    def __init__(self, insights: list[dict], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        if not insights:
            empty = QLabel("NO ACTIVE SIGNALS")
            empty.setObjectName("Mono")
            lay.addWidget(empty)
        for i, ins in enumerate(insights):
            lay.addWidget(_InsightRow(ins, i))
        lay.addStretch(1)


class _InsightRow(QWidget):
    def __init__(self, insight: dict, idx: int, parent=None):
        super().__init__(parent)
        self._color = severity_color(insight["severity"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 8)
        lay.setSpacing(3)

        head = QLabel(
            f"{insight['severity'].upper()}  ·  {insight['domain'].upper()}-{idx + 1:02d}"
        )
        head.setObjectName("Mono")
        head.setStyleSheet(
            f"color:{self._color}; font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            " letter-spacing:1px;"
        )
        lay.addWidget(head)

        title = QLabel(insight["title"])
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.body}px; font-weight:600;")
        title.setWordWrap(True)
        lay.addWidget(title)

        if insight.get("body"):
            body = QLabel(insight["body"])
            body.setObjectName("Faint")
            body.setWordWrap(True)
            lay.addWidget(body)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # severity bar on the left + faint panel
        bg = QColor(PALETTE.bg_panel_alt)
        bg.setAlpha(150)
        p.fillRect(self.rect(), bg)
        p.fillRect(0, 0, 2, self.height(), QColor(self._color))
        border = QColor(PALETTE.border)
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.end()


# --------------------------------------------------------------------------- #
# Radar dial (small spider chart)
# --------------------------------------------------------------------------- #
class RadarDial(QWidget):
    def __init__(
        self, axes: list[str], values: list[float], parent=None, *, color: str | None = None
    ):
        super().__init__(parent)
        self._axes = axes
        self._values = values
        self._color = color or PALETTE.accent
        self.setMinimumHeight(200)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.34
        n = len(self._axes)
        if n < 3:
            p.end()
            return
        angles = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]

        ring = QColor(PALETTE.border)
        p.setPen(QPen(ring, 1.0))
        p.setBrush(Qt.NoBrush)
        for frac in (0.4, 0.7, 1.0):
            pts = [
                QPointF(cx + radius * frac * math.cos(a), cy + radius * frac * math.sin(a))
                for a in angles
            ]
            p.drawPolygon(QPolygonF(pts))
        for a, axis in zip(angles, self._axes):
            ex, ey = cx + radius * math.cos(a), cy + radius * math.sin(a)
            p.setPen(QPen(ring, 1.0))
            p.drawLine(QPointF(cx, cy), QPointF(ex, ey))
            p.setPen(QColor(PALETTE.text_faint))
            f = p.font()
            f.setPointSize(TYPE.nano)
            p.setFont(f)
            p.drawText(
                QPointF(cx + (radius + 12) * math.cos(a) - 18, cy + (radius + 12) * math.sin(a)),
                axis[:8].upper(),
            )

        vpts = [
            QPointF(
                cx + radius * max(0, min(1, v)) * math.cos(a),
                cy + radius * max(0, min(1, v)) * math.sin(a),
            )
            for a, v in zip(angles, self._values)
        ]
        fill = QColor(self._color)
        fill.setAlpha(55)
        p.setBrush(fill)
        p.setPen(QPen(QColor(self._color), 1.8))
        p.drawPolygon(QPolygonF(vpts))
        p.setBrush(QColor(self._color))
        p.setPen(Qt.NoPen)
        for pt in vpts:
            p.drawEllipse(pt, 2.2, 2.2)
        p.end()
