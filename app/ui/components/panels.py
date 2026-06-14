"""Composite HUD panels and the mission header.

  SystemHeader          — mission header: title, timestamp, sync state, DB status
  BiometricPanel        — full-height medical/military HUD body scan
  FinanceTerminalPanel  — market-intelligence allocation donut + readouts
  VitalsStrip           — a row of compact metric cells inside a HudPanel
  ZoneDistribution      — a horizontal stacked-zone bar (training zones / risk)

These compose the primitives in `hud.py` and `viz.py`.
"""

from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
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
    """Central biometric panel: a full-height technical body scan."""

    def __init__(self, telemetry: list[dict], parent=None):
        super().__init__("BIOMETRIC SCAN", "HLT-CORE", parent, status="LIVE")
        self._scan = _BiometricScan(telemetry)
        self.body.addWidget(self._scan)


class _BiometricScan(QWidget):
    def __init__(self, telemetry: list[dict], parent=None):
        super().__init__(parent)
        self._telemetry = telemetry
        self._t = 0.0
        self.setMinimumHeight(620)
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
        body_h = h * 0.84
        body_w = min(w * 0.26, body_h * 0.28)

        self._paint_scan_field(p, w, h, cx, cy, body_h)
        body = self._body_points(cx, cy, body_w, body_h)
        self._paint_wireframe_body(p, body)
        self._paint_telemetry(p, w, h, body)
        p.end()

    def _paint_scan_field(
        self, p: QPainter, w: int, h: int, cx: float, cy: float, body_h: float
    ) -> None:
        grid = QColor(PALETTE.grid)
        grid.setAlpha(130)
        p.setPen(QPen(grid, 1.0))
        for i in range(9):
            x = w * (0.12 + i * 0.095)
            p.drawLine(QPointF(x, h * 0.06), QPointF(x, h * 0.94))
        for i in range(11):
            y = h * (0.08 + i * 0.084)
            p.drawLine(QPointF(w * 0.08, y), QPointF(w * 0.92, y))

        ring = QColor(PALETTE.accent_dim)
        ring.setAlpha(70)
        p.setPen(QPen(ring, 1.0))
        for rr in (body_h * 0.20, body_h * 0.34, body_h * 0.48):
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        cross = QColor(PALETTE.border)
        cross.setAlpha(170)
        p.setPen(QPen(cross, 1.0))
        p.drawLine(QPointF(cx - body_h * 0.28, cy), QPointF(cx + body_h * 0.28, cy))
        p.drawLine(QPointF(cx, cy - body_h * 0.48), QPointF(cx, cy + body_h * 0.48))

        scan_y = h * 0.08 + (0.5 + 0.5 * math.sin(self._t * 1.6)) * h * 0.84
        sweep = QColor(PALETTE.accent)
        sweep.setAlpha(135)
        p.setPen(QPen(sweep, 1.6))
        p.drawLine(QPointF(w * 0.20, scan_y), QPointF(w * 0.80, scan_y))
        glow = QColor(PALETTE.accent)
        glow.setAlpha(28)
        p.fillRect(QRectF(w * 0.20, scan_y - 8, w * 0.60, 16), glow)

    def _body_points(
        self, cx: float, cy: float, body_w: float, body_h: float
    ) -> dict[str, QPointF]:
        top = cy - body_h / 2
        return {
            "head": QPointF(cx, top + body_h * 0.085),
            "neck": QPointF(cx, top + body_h * 0.175),
            "sternum": QPointF(cx, top + body_h * 0.285),
            "pelvis": QPointF(cx, top + body_h * 0.535),
            "left_shoulder": QPointF(cx - body_w * 0.47, top + body_h * 0.205),
            "right_shoulder": QPointF(cx + body_w * 0.47, top + body_h * 0.205),
            "left_elbow": QPointF(cx - body_w * 0.72, top + body_h * 0.385),
            "right_elbow": QPointF(cx + body_w * 0.72, top + body_h * 0.385),
            "left_hand": QPointF(cx - body_w * 0.58, top + body_h * 0.575),
            "right_hand": QPointF(cx + body_w * 0.58, top + body_h * 0.575),
            "left_hip": QPointF(cx - body_w * 0.24, top + body_h * 0.535),
            "right_hip": QPointF(cx + body_w * 0.24, top + body_h * 0.535),
            "left_knee": QPointF(cx - body_w * 0.28, top + body_h * 0.745),
            "right_knee": QPointF(cx + body_w * 0.28, top + body_h * 0.745),
            "left_foot": QPointF(cx - body_w * 0.34, top + body_h * 0.965),
            "right_foot": QPointF(cx + body_w * 0.34, top + body_h * 0.965),
        }

    def _paint_wireframe_body(self, p: QPainter, body: dict[str, QPointF]) -> None:
        outline = QColor(PALETTE.accent)
        outline.setAlpha(165)
        dim = QColor(PALETTE.accent_dim)
        dim.setAlpha(105)
        faint = QColor(PALETTE.border)
        faint.setAlpha(170)

        head = body["head"]
        head_r = abs(body["neck"].y() - head.y()) * 0.78
        p.setPen(QPen(outline, 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(head, head_r * 0.72, head_r)
        p.drawLine(body["head"], body["neck"])
        p.drawLine(body["neck"], body["sternum"])
        p.drawLine(body["sternum"], body["pelvis"])

        skeleton_lines = [
            ("left_shoulder", "right_shoulder"),
            ("left_shoulder", "left_elbow"),
            ("left_elbow", "left_hand"),
            ("right_shoulder", "right_elbow"),
            ("right_elbow", "right_hand"),
            ("left_shoulder", "sternum"),
            ("right_shoulder", "sternum"),
            ("sternum", "left_hip"),
            ("sternum", "right_hip"),
            ("left_hip", "right_hip"),
            ("left_hip", "left_knee"),
            ("left_knee", "left_foot"),
            ("right_hip", "right_knee"),
            ("right_knee", "right_foot"),
        ]
        for a, b in skeleton_lines:
            p.drawLine(body[a], body[b])

        torso = QPainterPath(body["neck"])
        torso.cubicTo(
            body["left_shoulder"],
            QPointF(body["left_hip"].x() - 18, body["sternum"].y() + 80),
            body["left_hip"],
        )
        torso.lineTo(body["right_hip"])
        torso.cubicTo(
            QPointF(body["right_hip"].x() + 18, body["sternum"].y() + 80),
            body["right_shoulder"],
            body["neck"],
        )
        fill = QColor(PALETTE.accent)
        fill.setAlpha(12)
        p.setBrush(fill)
        p.setPen(QPen(faint, 1.0))
        p.drawPath(torso)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(dim, 1.0))
        rib_top = body["sternum"].y() - 8
        rib_width = abs(body["right_shoulder"].x() - body["left_shoulder"].x()) * 0.58
        for i in range(5):
            y = rib_top + i * 18
            p.drawArc(
                int(body["sternum"].x() - rib_width / 2),
                int(y),
                int(rib_width),
                26,
                0,
                180 * 16,
            )

        p.setPen(QPen(outline, 1.0))
        for key, pt in body.items():
            if key == "head":
                continue
            p.drawRect(int(pt.x() - 3), int(pt.y() - 3), 6, 6)

        p.setPen(QPen(dim, 0.9))
        for offset in (-8, 8):
            p.drawLine(
                QPointF(body["sternum"].x() + offset, body["neck"].y()),
                QPointF(body["pelvis"].x() + offset * 0.35, body["pelvis"].y()),
            )

        label = QColor(PALETTE.text_faint)
        p.setPen(label)
        f = p.font()
        f.setPointSize(TYPE.nano)
        f.setFamily(TYPE.mono.split(",")[0])
        p.setFont(f)
        p.drawText(int(body["head"].x() - 38), int(body["head"].y() - head_r - 14), "SKELETON")

    def _paint_telemetry(self, p: QPainter, w: int, h: int, body: dict[str, QPointF]) -> None:
        anchors = [
            body["head"],
            body["sternum"],
            body["left_shoulder"],
            body["right_shoulder"],
            body["pelvis"],
            body["left_knee"],
            body["right_knee"],
        ]
        slots = [
            QRectF(w * 0.06, h * 0.10, w * 0.24, 58),
            QRectF(w * 0.70, h * 0.10, w * 0.24, 58),
            QRectF(w * 0.05, h * 0.34, w * 0.24, 58),
            QRectF(w * 0.71, h * 0.34, w * 0.24, 58),
            QRectF(w * 0.06, h * 0.60, w * 0.24, 58),
            QRectF(w * 0.70, h * 0.60, w * 0.24, 58),
            QRectF(w * 0.38, h * 0.83, w * 0.24, 58),
        ]
        lead = QColor(PALETTE.accent_dim)
        lead.setAlpha(150)
        for i, metric in enumerate(self._telemetry[:7]):
            rect = slots[i]
            anchor = anchors[i]
            card_edge = QPointF(rect.left(), rect.center().y())
            if rect.center().x() < w / 2:
                card_edge = QPointF(rect.right(), rect.center().y())
            p.setPen(QPen(lead, 1.0))
            p.drawLine(anchor, card_edge)

            score = float(metric.get("score", 0.5))
            col = self._score_color(score)
            bg = QColor(PALETTE.bg_panel_alt)
            bg.setAlpha(170)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRect(rect)
            p.fillRect(QRectF(rect.left(), rect.top(), 2, rect.height()), QColor(col))
            p.setPen(QPen(QColor(PALETTE.border), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(anchor, 3.2, 3.2)

            f = p.font()
            f.setPointSize(TYPE.nano)
            f.setFamily(TYPE.mono.split(",")[0])
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(PALETTE.text_faint))
            p.drawText(
                int(rect.left() + 10),
                int(rect.top() + 16),
                str(metric["label"]).upper(),
            )
            f.setPointSize(TYPE.h2)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(PALETTE.text))
            p.drawText(
                int(rect.left() + 10),
                int(rect.top() + 39),
                str(metric["value"]),
            )
            f.setPointSize(TYPE.nano)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(
                int(rect.right() - 46),
                int(rect.top() + 17),
                f"{score * 100:02.0f}%",
            )

    def _score_color(self, score: float) -> str:
        if score >= 0.72:
            return PALETTE.positive
        if score >= 0.45:
            return PALETTE.accent
        if score >= 0.28:
            return PALETTE.orange
        return PALETTE.coral


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
