"""Core HUD primitives — the technical building blocks of the ORION interface.

  CornerFrame   — paints L-shaped corner brackets + thin border around content
  HudPanel      — a titled HUD panel: small uppercase title, module code, corner
                  brackets, thin border, header tick row, optional status signal
  StatusPill    — a compact mono status chip with a coloured dot
  MetricCell    — a compact metric readout (label / code / value / delta /
                  micro-signal) used in stacks and strips
  Divider       — a faint dashed divider line with end ticks

These intentionally avoid rounded "SaaS card" styling: square-ish corners, thin
borders, mono labels, corner accents.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services import Metric
from app.ui.themes.theme import PALETTE

_SEVERITY = {
    "info": PALETTE.accent,
    "positive": PALETTE.positive,
    "warning": PALETTE.orange,
    "critical": PALETTE.coral,
}


def severity_color(name: str) -> str:
    return _SEVERITY.get(name, PALETTE.accent)


class CornerFrame(QFrame):
    """A bordered frame that paints L-shaped corner brackets."""

    def __init__(self, parent=None, *, accent: str | None = None, bracket: int = 12):
        super().__init__(parent)
        self._accent = accent or PALETTE.accent
        self._bracket = bracket

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        b = self._bracket
        pen = QPen(QColor(self._accent))
        pen.setWidthF(1.4)
        p.setPen(pen)
        m = 1  # inset
        # four corners
        p.drawLine(m, m, m + b, m)
        p.drawLine(m, m, m, m + b)
        p.drawLine(w - m, m, w - m - b, m)
        p.drawLine(w - m, m, w - m, m + b)
        p.drawLine(m, h - m, m + b, h - m)
        p.drawLine(m, m + (h - 2 * m), m, h - m - b)
        p.drawLine(w - m, h - m, w - m - b, h - m)
        p.drawLine(w - m, h - m, w - m, h - m - b)
        p.end()


class HudPanel(CornerFrame):
    """A titled HUD panel with module code and corner brackets.

    Compose content into ``self.body`` (a QVBoxLayout).
    """

    def __init__(
        self,
        title: str,
        code: str = "",
        parent=None,
        *,
        accent: str | None = None,
        status: str | None = None,
    ):
        super().__init__(parent, accent=accent or PALETTE.border)
        self.setObjectName("HudPanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 11, 14, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        t = QLabel(title.upper())
        t.setObjectName("PanelTitle")
        header.addWidget(t)
        if code:
            c = QLabel(code)
            c.setObjectName("ModuleCode")
            header.addWidget(c)
        header.addStretch(1)
        if status:
            header.addWidget(StatusPill(status, severity_color("info")))
        outer.addLayout(header)
        outer.addWidget(Divider())

        inner = QWidget()
        inner.setObjectName("PanelInner")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 2, 0, 0)
        self.body.setSpacing(7)
        outer.addWidget(inner, 1)


class StatusPill(QWidget):
    """A mono status chip: ● LABEL, with a coloured dot."""

    def __init__(self, label: str, color: str | None = None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color or PALETTE.accent}; font-size:8px;")
        text = QLabel(label.upper())
        text.setObjectName("Pill")
        lay.addWidget(dot)
        lay.addWidget(text)


class Divider(QWidget):
    """A faint dashed horizontal divider with end ticks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        w = self.width()
        y = self.height() / 2
        pen = QPen(QColor(PALETTE.border))
        pen.setWidthF(1.0)
        pen.setDashPattern([1, 4])
        p.setPen(pen)
        p.drawLine(8, int(y), w - 8, int(y))
        # end ticks
        tick = QPen(QColor(PALETTE.accent_dim))
        tick.setWidthF(1.2)
        p.setPen(tick)
        p.drawLine(2, int(y - 2), 2, int(y + 2))
        p.drawLine(w - 2, int(y - 2), w - 2, int(y + 2))
        p.end()


class MicroSignal(QWidget):
    """A tiny inline signal line (sparkline) for metric cells."""

    def __init__(self, series: list[float] | None = None, color: str | None = None, parent=None):
        super().__init__(parent)
        self._series = series or []
        self._color = color or PALETTE.accent
        self.setMinimumHeight(22)
        self.setMaximumHeight(28)

    def paintEvent(self, event):  # noqa: N802
        if len(self._series) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        lo, hi = min(self._series), max(self._series)
        rng = (hi - lo) or 1.0
        n = len(self._series)
        pen = QPen(QColor(self._color))
        pen.setWidthF(1.4)
        p.setPen(pen)
        prev = None
        for i, v in enumerate(self._series):
            x = i / (n - 1) * (w - 2) + 1
            y = h - 2 - (v - lo) / rng * (h - 4)
            if prev is not None:
                p.drawLine(QPointF(prev[0], prev[1]), QPointF(x, y))
            prev = (x, y)
        # leading dot
        if prev:
            p.setBrush(QColor(self._color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(prev[0], prev[1]), 2, 2)
        p.end()


class MetricCell(QWidget):
    """Compact metric readout for stacks/strips: code · label · value · delta · signal."""

    def __init__(self, metric: Metric, code: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        label = QLabel(metric.label.upper())
        label.setObjectName("CardLabel")
        top.addWidget(label)
        top.addStretch(1)
        if code:
            c = QLabel(code)
            c.setObjectName("ModuleCode")
            top.addWidget(c)
        lay.addLayout(top)

        valrow = QHBoxLayout()
        valrow.setSpacing(8)
        value = QLabel(metric.value)
        value.setObjectName("CardValue")
        valrow.addWidget(value)
        valrow.addStretch(1)
        if metric.delta:
            arrow = {"up": "▲", "down": "▼", "flat": "■"}[metric.trend]
            d = QLabel(f"{arrow} {metric.delta}")
            d.setObjectName(
                {"up": "DeltaUp", "down": "DeltaDown", "flat": "DeltaFlat"}[metric.trend]
            )
            valrow.addWidget(d, 0, Qt.AlignBottom)
        lay.addLayout(valrow)

        if metric.series and len(metric.series) > 1:
            color = {"up": PALETTE.positive, "down": PALETTE.coral, "flat": PALETTE.accent}[
                metric.trend
            ]
            lay.addWidget(MicroSignal(metric.series, color))
