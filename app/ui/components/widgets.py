"""Reusable ORION UI components.

These are the building blocks the screens compose:
  GlassPanel    — a bordered glassmorphism container
  OrionLogo     — the ORION wordmark
  MetricCard    — compact metric tile (label / value / delta / sparkline)
  InsightCard   — a deterministic insight with severity accent
  ModuleCard    — a module entry tile for the overview grid
  Sparkline     — tiny inline trend line

Chart panels (line / radar / timeline) live in `charts.py`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services import Metric
from app.ui.themes.theme import PALETTE, TYPE

_SEVERITY_COLOR = {
    "info": PALETTE.accent,
    "positive": PALETTE.positive,
    "warning": PALETTE.warning,
    "critical": PALETTE.critical,
}


class GlassPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        self.body = lay


class OrionLogo(QWidget):
    """ORION wordmark with optional tagline."""

    def __init__(self, parent=None, *, big: bool = False, tagline: bool = False):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        word = QLabel("ORION")
        size = TYPE.display if big else TYPE.h1
        word.setStyleSheet(
            f"font-size:{size}px; font-weight:700; letter-spacing:{10 if big else 6}px;"
            f" color:{PALETTE.text};"
        )
        lay.addWidget(word)
        if tagline:
            sub = QLabel("PERSONAL OBSERVABILITY PLATFORM")
            sub.setStyleSheet(
                f"color:{PALETTE.text_faint}; font-size:{TYPE.micro}px; letter-spacing:3px;"
            )
            lay.addWidget(sub)


class Sparkline(QWidget):
    def __init__(self, series: list[float] | None = None, parent=None, *, color: str | None = None):
        super().__init__(parent)
        self._series = series or []
        self._color = color or PALETTE.accent
        self.setMinimumHeight(34)

    def set_series(self, series: list[float]) -> None:
        self._series = series
        self.update()

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
        pen.setWidthF(1.6)
        p.setPen(pen)
        prev = None
        for i, v in enumerate(self._series):
            x = i / (n - 1) * (w - 4) + 2
            y = h - 3 - (v - lo) / rng * (h - 6)
            if prev is not None:
                p.drawLine(prev[0], prev[1], x, y)
            prev = (x, y)
        p.end()


class MetricCard(GlassPanel):
    def __init__(self, metric: Metric, parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setMinimumWidth(190)

        label = QLabel(metric.label.upper())
        label.setObjectName("CardLabel")
        self.body.addWidget(label)

        value = QLabel(metric.value)
        value.setObjectName("CardValue")
        value.setWordWrap(True)
        self.body.addWidget(value)

        if metric.delta:
            arrow = {"up": "▲", "down": "▼", "flat": "■"}[metric.trend]
            d = QLabel(f"{arrow} {metric.delta}")
            d.setObjectName(
                {"up": "DeltaUp", "down": "DeltaDown", "flat": "DeltaFlat"}[metric.trend]
            )
            self.body.addWidget(d)

        if metric.series and len(metric.series) > 1:
            color = {"up": PALETTE.positive, "down": PALETTE.critical, "flat": PALETTE.accent}[
                metric.trend
            ]
            self.body.addWidget(Sparkline(metric.series, color=color))
        self.body.addStretch(1)


class InsightCard(GlassPanel):
    def __init__(self, insight: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("InsightCard")
        accent = _SEVERITY_COLOR.get(insight["severity"], PALETTE.accent)

        header = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{accent}; font-size:11px;")
        header.addWidget(dot)
        domain = QLabel(insight["domain"].upper())
        domain.setObjectName("CardLabel")
        header.addWidget(domain)
        header.addStretch(1)
        self.body.addLayout(header)

        title = QLabel(insight["title"])
        title.setStyleSheet(f"font-size:{TYPE.h2}px; font-weight:600; color:{PALETTE.text};")
        title.setWordWrap(True)
        self.body.addWidget(title)

        if insight.get("body"):
            body = QLabel(insight["body"])
            body.setObjectName("Muted")
            body.setWordWrap(True)
            self.body.addWidget(body)


class ModuleCard(GlassPanel):
    """A clickable module tile for the Overview grid."""

    def __init__(self, icon: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ModuleCard")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout()
        glyph = QLabel(icon)
        glyph.setStyleSheet(f"font-size:22px; color:{PALETTE.accent};")
        row.addWidget(glyph)
        col = QVBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(f"font-size:{TYPE.h2}px; font-weight:600;")
        s = QLabel(subtitle)
        s.setObjectName("Faint")
        s.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(s)
        row.addLayout(col, 1)
        self.body.addLayout(row)
