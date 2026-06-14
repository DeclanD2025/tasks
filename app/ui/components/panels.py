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
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
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

        self._paint_body_scan(p, cx, cy, radius)

        # Vital markers pinned to anatomical regions with short readout leads.
        marker_layout = {
            "sleep": ((0.0, -0.54), (0.0, -0.74), Qt.AlignmentFlag.AlignCenter),
            "hrv": ((0.19, -0.07), (0.54, -0.16), Qt.AlignmentFlag.AlignLeft),
            "pulse": ((0.12, 0.02), (0.50, 0.22), Qt.AlignmentFlag.AlignLeft),
            "strain": ((-0.12, 0.55), (-0.54, 0.62), Qt.AlignmentFlag.AlignRight),
            "move": ((-0.32, 0.10), (-0.56, -0.02), Qt.AlignmentFlag.AlignRight),
        }
        lead = QColor(PALETTE.accent_dim)
        lead.setAlpha(150)
        p.setPen(QPen(lead, 1.0))
        for name, score in self._scores.items():
            target_pos, label_pos, align = marker_layout.get(
                name, ((0.0, 0.0), (0.52, 0.0), Qt.AlignmentFlag.AlignLeft)
            )
            target = self._pt(cx, cy, radius, *target_pos)
            label = self._pt(cx, cy, radius, *label_pos)
            p.drawLine(target, label)
            col = (
                PALETTE.positive
                if score >= 0.66
                else (PALETTE.orange if score >= 0.4 else PALETTE.coral)
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(target, 3.0, 3.0)
            p.drawEllipse(label, 3.2, 3.2)
            p.setPen(QColor(PALETTE.text_dim))
            f = p.font()
            f.setPointSize(TYPE.nano)
            p.setFont(f)
            label_width = 68
            x = (
                label.x() - label_width - 8
                if align == Qt.AlignmentFlag.AlignRight
                else label.x() + 8
            )
            if align == Qt.AlignmentFlag.AlignCenter:
                x = label.x() - label_width / 2
            p.drawText(int(x), int(label.y() - 8), label_width, 14, align, name.upper())
        p.end()

    def _pt(self, cx: float, cy: float, radius: float, x: float, y: float) -> QPointF:
        return QPointF(cx + radius * x, cy + radius * y)

    def _path(self, cx: float, cy: float, radius: float, points: list[tuple[float, float]]):
        path = QPainterPath(self._pt(cx, cy, radius, *points[0]))
        for x, y in points[1:]:
            path.lineTo(self._pt(cx, cy, radius, x, y))
        path.closeSubpath()
        return path

    def _paint_body_scan(self, p: QPainter, cx: float, cy: float, radius: float) -> None:
        fill = QColor(PALETTE.accent)
        fill.setAlpha(18)
        outline = QColor(PALETTE.accent)
        outline.setAlpha(150)
        inner = QColor(PALETTE.accent_dim)
        inner.setAlpha(105)

        p.setPen(QPen(outline, 1.5))
        p.setBrush(fill)

        # Head and neck.
        head = self._pt(cx, cy, radius, 0.0, -0.44)
        p.drawEllipse(head, radius * 0.12, radius * 0.14)
        neck = self._path(
            cx,
            cy,
            radius,
            [(-0.055, -0.30), (0.055, -0.30), (0.075, -0.20), (-0.075, -0.20)],
        )
        p.drawPath(neck)

        # Torso: broad shoulders, narrowed waist, hip bowl.
        torso = QPainterPath(self._pt(cx, cy, radius, 0.0, -0.26))
        torso.cubicTo(
            self._pt(cx, cy, radius, -0.18, -0.25),
            self._pt(cx, cy, radius, -0.28, -0.17),
            self._pt(cx, cy, radius, -0.31, -0.05),
        )
        torso.cubicTo(
            self._pt(cx, cy, radius, -0.28, 0.14),
            self._pt(cx, cy, radius, -0.18, 0.28),
            self._pt(cx, cy, radius, -0.16, 0.40),
        )
        torso.cubicTo(
            self._pt(cx, cy, radius, -0.08, 0.47),
            self._pt(cx, cy, radius, 0.08, 0.47),
            self._pt(cx, cy, radius, 0.16, 0.40),
        )
        torso.cubicTo(
            self._pt(cx, cy, radius, 0.18, 0.28),
            self._pt(cx, cy, radius, 0.28, 0.14),
            self._pt(cx, cy, radius, 0.31, -0.05),
        )
        torso.cubicTo(
            self._pt(cx, cy, radius, 0.28, -0.17),
            self._pt(cx, cy, radius, 0.18, -0.25),
            self._pt(cx, cy, radius, 0.0, -0.26),
        )
        p.drawPath(torso)

        limb_specs = [
            [
                (-0.30, -0.11),
                (-0.43, 0.08),
                (-0.37, 0.27),
                (-0.26, 0.37),
                (-0.20, 0.30),
                (-0.27, 0.08),
            ],
            [(0.30, -0.11), (0.43, 0.08), (0.37, 0.27), (0.26, 0.37), (0.20, 0.30), (0.27, 0.08)],
            [
                (-0.13, 0.40),
                (-0.22, 0.60),
                (-0.17, 0.82),
                (-0.27, 0.88),
                (-0.04, 0.88),
                (-0.03, 0.58),
            ],
            [(0.13, 0.40), (0.22, 0.60), (0.17, 0.82), (0.27, 0.88), (0.04, 0.88), (0.03, 0.58)],
        ]
        for spec in limb_specs:
            p.drawPath(self._path(cx, cy, radius, spec))

        # Interior scan details: spine, clavicle, rib arcs, joints.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(inner, 1.1))
        p.drawLine(self._pt(cx, cy, radius, 0.0, -0.27), self._pt(cx, cy, radius, 0.0, 0.43))
        p.drawLine(self._pt(cx, cy, radius, -0.24, -0.11), self._pt(cx, cy, radius, 0.24, -0.11))
        for y, width in [(-0.02, 0.18), (0.08, 0.21), (0.18, 0.18)]:
            p.drawArc(
                int(cx - radius * width),
                int(cy + radius * y - radius * 0.055),
                int(radius * width * 2),
                int(radius * 0.11),
                0,
                180 * 16,
            )

        joint = QColor(PALETTE.accent)
        joint.setAlpha(180)
        p.setPen(QPen(joint, 1.0))
        for x, y in [
            (-0.29, -0.11),
            (0.29, -0.11),
            (-0.38, 0.22),
            (0.38, 0.22),
            (-0.15, 0.42),
            (0.15, 0.42),
            (-0.17, 0.62),
            (0.17, 0.62),
        ]:
            p.drawRect(int(cx + radius * x - 3), int(cy + radius * y - 3), 6, 6)


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
