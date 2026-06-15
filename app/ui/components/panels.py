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
from datetime import UTC, datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.config import asset_path
from app.domains.health.health_schema import BioSystemBar, HealthDashboardSnapshot, HealthMetricCard
from app.services import Metric
from app.ui.components.hud import HudPanel, MetricCell, StatusPill
from app.ui.themes.theme import PALETTE, TYPE


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class TypingLabel(QLabel):
    """A label that reveals its text character-by-character with a block cursor.

    Gives module headings the feel of a futuristic console booting up. The
    cursor blinks while typing and for a moment after, then the text settles.
    """

    def __init__(self, text: str, parent=None, *, style: str = "", interval_ms: int = 38):
        super().__init__(parent)
        self._full = text
        self._n = 0
        self._cursor_on = True
        self._settle_ticks = 0
        if style:
            self.setStyleSheet(style)
        self.setText(" ")  # reserve height before typing starts

        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._tick)
        self._type_timer.start(interval_ms)
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start(420)

    def _render(self):
        cursor = "▌" if self._cursor_on else " "
        self.setText(self._full[: self._n] + cursor)

    def _tick(self):
        if self._n < len(self._full):
            self._n += 1
            self._render()
        else:
            # Typed out; blink the cursor a few times then remove it.
            self._settle_ticks += 1
            if self._settle_ticks > 6:
                self._type_timer.stop()
                self._blink_timer.stop()
                self.setText(self._full)

    def _blink(self):
        self._cursor_on = not self._cursor_on
        if self._n <= len(self._full):
            self._render()


# --------------------------------------------------------------------------- #
# Mission header
# --------------------------------------------------------------------------- #
class SystemHeader(QWidget):
    """A full-width mission header bar for module pages."""

    def __init__(
        self,
        title: str,
        code: str,
        parent=None,
        *,
        subtitle: str | None = None,
        sync_label: str = "SYNC OK",
        database_label: str = "DB LOCAL",
    ):
        super().__init__(parent)
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 8)
        lay.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(1)
        t = TypingLabel(
            title.upper(),
            style=(f"color:{PALETTE.text}; font-size:{TYPE.h1}px; font-weight:700;"
                   " letter-spacing:2px;"),
        )
        sub = QLabel(subtitle.upper() if subtitle else f"MODULE {code}  ·  ORION OBSERVATORY")
        sub.setObjectName("Mono")
        left.addWidget(t)
        left.addWidget(sub)
        lay.addLayout(left)
        lay.addStretch(1)

        self._clock = QLabel("")
        self._clock.setObjectName("Mono")
        lay.addWidget(self._clock)
        lay.addWidget(_VSep())
        lay.addWidget(StatusPill(sync_label, PALETTE.positive))
        lay.addWidget(StatusPill(database_label, PALETTE.accent))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()

    def _refresh(self):
        self._clock.setText(datetime.now(UTC).strftime("%Y-%m-%d  %H:%M:%S  UTC"))

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
# Biometric scan panel (medical/aerospace HUD)
# --------------------------------------------------------------------------- #
class BiometricScanPanel(HudPanel):
    """Image-backed full-height biometric telemetry scan."""

    def __init__(self, snapshot: HealthDashboardSnapshot, parent=None):
        super().__init__("BIOMETRIC SCAN", "HLT-SCN", parent, status=snapshot.scan_status)
        self._scan = _BiometricScanCanvas(snapshot)
        self.body.addWidget(self._scan)


class BiometricPanel(BiometricScanPanel):
    """Backward-compatible alias for older Health page imports."""


class _BiometricScanCanvas(QWidget):
    _LEADER_KEYS = {"sleep", "hrv", "vo2", "training_load"}

    def __init__(self, snapshot: HealthDashboardSnapshot, parent=None):
        super().__init__(parent)
        self._snapshot = snapshot
        self._t = 0.0
        self._pixmap = QPixmap(str(asset_path("ui", "assets", "biometric", "wireframe_human.png")))
        self.setMinimumHeight(710)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(70)

    def _tick(self) -> None:
        self._t += 0.045
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), self._color(PALETTE.bg_void, 95))

        layout = self._layout(w, h)
        self._paint_scan_field(p, w, h, layout["stage"], layout["figure"])
        anchors = self._body_anchors(layout["figure"])
        self._paint_model(p, layout["figure"])
        self._paint_metric_cards(p, layout["metric_slots"], anchors)
        self._paint_scan_status(p, layout["scan_status"])
        self._paint_system_rail(p, layout["rail"])
        p.end()

    def _layout(self, w: int, h: int) -> dict[str, object]:
        rail_w = max(172.0, min(220.0, w * 0.15))
        gap = max(14.0, min(22.0, w * 0.014))
        left_x = 18.0
        card_w = max(204.0, min(268.0, w * 0.19))
        card_h = max(84.0, min(110.0, (h * 0.70 - 36.0) / 4.0))
        top_y = 34.0
        step = card_h + max(13.0, min(19.0, h * 0.022))
        rail = QRectF(w - rail_w - 8.0, 16.0, rail_w, h - 30.0)
        right_x = rail.left() - gap - card_w
        stage_left = left_x + card_w + gap
        stage_right = right_x - gap
        stage = QRectF(stage_left, 16.0, max(240.0, stage_right - stage_left), h - 32.0)
        cx = stage.center().x()
        figure_h = min(h * 0.93, stage.width() * 2.08)
        figure_w = figure_h * self._image_aspect()
        figure = QRectF(cx - figure_w / 2.0, h * 0.0, figure_w, figure_h)
        if figure.bottom() > h * 0.95:
            figure.moveBottom(h * 0.95)

        left_cards = [c for c in self._snapshot.metric_cards if c.side == "left"]
        right_cards = [c for c in self._snapshot.metric_cards if c.side == "right"]
        slots: list[tuple[HealthMetricCard, QRectF]] = []
        for idx, card in enumerate(left_cards[:4]):
            slots.append((card, QRectF(left_x, top_y + idx * step, card_w, card_h)))
        for idx, card in enumerate(right_cards[:4]):
            slots.append((card, QRectF(right_x, top_y + idx * step, card_w, card_h)))

        return {
            "rail": rail,
            "stage": stage,
            "figure": figure,
            "metric_slots": slots,
            "scan_status": QRectF(stage.center().x() - 180.0, h - 64.0, 360.0, 46.0),
        }

    def _image_aspect(self) -> float:
        if self._pixmap.isNull():
            return 0.42
        return self._pixmap.width() / max(1, self._pixmap.height())

    def _paint_scan_field(self, p: QPainter, w: int, h: int, stage: QRectF, figure: QRectF) -> None:
        grid = self._color(PALETTE.grid, 84)
        p.setPen(QPen(grid, 1.0))
        x = 0.0
        while x < w:
            alpha = 95 if abs(x - stage.center().x()) < 2 else 52
            p.setPen(QPen(self._color(PALETTE.grid, alpha), 1.0))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            x += 48
        y = 0.0
        while y < h:
            p.setPen(QPen(self._color(PALETTE.grid, 54), 1.0))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += 48

        cx = figure.center().x()
        cy = figure.center().y() + figure.height() * 0.02
        for i, factor in enumerate((0.44, 0.63)):
            radius = figure.height() * factor
            alpha = 36 + i * 18
            p.setPen(QPen(self._color(PALETTE.accent_dim, alpha), 1.0))
            p.drawEllipse(QPointF(cx, cy), radius * 0.46, radius * 0.46)

        sweep = (self._t * 0.12) % (math.tau)
        ring_r = figure.height() * 0.30
        p.setPen(QPen(self._color(PALETTE.accent, 120), 1.2))
        p.drawLine(
            QPointF(cx, cy),
            QPointF(cx + math.cos(sweep) * ring_r, cy + math.sin(sweep) * ring_r),
        )

        base = QPointF(cx, figure.bottom() + 8)
        for i, r in enumerate((figure.width() * 0.62, figure.width() * 0.96)):
            alpha = 80 - i * 24
            p.setPen(QPen(self._color(PALETTE.accent, alpha), 1.0))
            p.drawEllipse(base, r, r * 0.15)
        pulse = 1.0 + math.sin(self._t * 1.4) * 0.035
        p.setPen(QPen(self._color(PALETTE.accent, 120), 1.2))
        p.drawEllipse(base, figure.width() * 0.68 * pulse, figure.width() * 0.19 * pulse)

        scan_y = figure.top() + (0.5 + 0.5 * math.sin(self._t * 0.82)) * figure.height()
        p.fillRect(
            QRectF(stage.left() + 10, scan_y - 7, stage.width() - 20, 14),
            self._color(PALETTE.accent, 12),
        )
        p.setPen(QPen(self._color(PALETTE.accent, 58), 1.0))
        p.drawLine(QPointF(stage.left() + 18, scan_y), QPointF(stage.right() - 18, scan_y))

    def _paint_model(self, p: QPainter, figure: QRectF) -> None:
        if self._pixmap.isNull():
            self._set_font(p, TYPE.small, mono=True, bold=True)
            p.setPen(self._color(PALETTE.coral, 200))
            p.drawText(figure, Qt.AlignCenter, "WIRE MODEL MISSING")
            return

        pulse = 1.0 + math.sin(self._t * 1.7) * 0.012
        glow = QRectF(figure)
        glow.setWidth(figure.width() * (1.05 * pulse))
        glow.setHeight(figure.height() * (1.035 * pulse))
        glow.moveCenter(figure.center())
        p.setOpacity(0.22)
        p.drawPixmap(glow.toRect(), self._pixmap)
        p.setOpacity(0.93)
        p.drawPixmap(figure.toRect(), self._pixmap)
        p.setOpacity(1.0)

        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text_faint, 180))
        p.drawText(
            QRectF(figure.center().x() - 122, figure.top() - 18, 244, 14),
            Qt.AlignCenter,
            "WIRE MODEL / SKELETAL TELEMETRY",
        )

    def _paint_metric_cards(
        self,
        p: QPainter,
        slots: list[tuple[HealthMetricCard, QRectF]],
        anchors: dict[str, QPointF],
    ) -> None:
        for card, rect in slots:
            anchor = anchors.get(card.target_region, anchors["core"])
            if card.key in self._LEADER_KEYS:
                edge_x = rect.right() if card.side == "left" else rect.left()
                start = QPointF(edge_x, rect.center().y())
                elbow = QPointF(start.x() + (24 if card.side == "left" else -24), start.y())
                pre_anchor = QPointF(anchor.x() + (-54 if card.side == "left" else 54), anchor.y())
                p.setPen(QPen(self._color(PALETTE.accent, 128), 1.0))
                p.drawLine(start, elbow)
                p.drawLine(elbow, pre_anchor)
                p.drawLine(pre_anchor, anchor)
                p.setBrush(self._color(PALETTE.accent, 190))
                p.setPen(Qt.NoPen)
                p.drawEllipse(anchor, 3.0, 3.0)
                p.drawRect(QRectF(start.x() - 2.0, start.y() - 2.0, 4.0, 4.0))
            self._draw_metric_card(p, card, rect)

    def _draw_metric_card(self, p: QPainter, card: HealthMetricCard, rect: QRectF) -> None:
        accent = PALETTE.orange if card.warning else PALETTE.accent
        self._draw_panel_rect(p, rect, accent=accent, fill_alpha=154)
        self._set_font(p, TYPE.small, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text, 226))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 12, rect.width() - 28, 16), card.label.upper()
        )
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.accent_dim, 205))
        p.drawText(
            QRectF(rect.right() - 82, rect.top() + 12, 68, 14),
            Qt.AlignRight,
            card.code.upper(),
        )

        self._set_font(p, 20, mono=False, bold=True)
        p.setPen(self._color(PALETTE.text, 244))
        value_rect = QRectF(rect.left() + 14, rect.top() + 38, rect.width() * 0.46, 28)
        tight_unit = card.unit if card.unit in {"h", "%"} else ""
        p.drawText(value_rect, Qt.AlignLeft | Qt.AlignVCenter, f"{card.value}{tight_unit}")
        if card.unit and not tight_unit and len(card.unit) <= 4:
            unit_x = value_rect.left() + p.fontMetrics().horizontalAdvance(card.value) + 6
            self._set_font(p, TYPE.small, mono=False, bold=True)
            p.setPen(self._color(PALETTE.text, 225))
            p.drawText(
                QRectF(unit_x, rect.top() + 43, rect.width() * 0.30, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                card.unit,
            )

        sep_x = rect.left() + rect.width() * 0.55
        p.fillRect(QRectF(sep_x, rect.top() + 38, 1.0, 31), self._color(PALETTE.border, 190))
        secondary_size = 18 if len(card.secondary_value) <= 4 else TYPE.h2
        self._set_font(p, secondary_size, mono=True, bold=True)
        p.setPen(self._color(accent, 235))
        p.drawText(
            QRectF(sep_x + 14, rect.top() + 37, rect.right() - sep_x - 28, 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            card.secondary_value.upper(),
        )
        self._set_font(p, TYPE.nano, mono=True)
        p.setPen(self._color(PALETTE.text_dim, 205))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 66, rect.width() * 0.44, 14),
            self._primary_detail(card),
        )
        p.drawText(
            QRectF(sep_x + 14, rect.top() + 66, rect.right() - sep_x - 28, 14),
            card.secondary_label.upper(),
        )
        self._draw_sparkline(
            p,
            card.sparkline,
            QRectF(rect.left() + 14, rect.bottom() - 24, rect.width() - 28, 16),
            accent,
        )

    def _primary_detail(self, card: HealthMetricCard) -> str:
        details = {
            "sleep": "DURATION",
            "hrv": "7D AVERAGE",
            "recovery": "RECOVERY SCORE",
            "weight": "CURRENT",
            "rhr": "RESTING HEART RATE",
            "vo2": "ML/KG/MIN",
            "training_load": "7D LOAD",
            "readiness": "OVERALL READINESS",
        }
        return details.get(card.key, "CURRENT")

    def _paint_scan_status(self, p: QPainter, rect: QRectF) -> None:
        self._draw_panel_rect(p, rect, accent=PALETTE.border, fill_alpha=150)
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.accent, 230))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 10, rect.width() - 28, 14),
            "BIOMETRIC SCAN ACTIVE",
        )
        p.setPen(self._color(PALETTE.text_faint, 210))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 25, rect.width() - 28, 14),
            f"BODY BATTERY {self._snapshot.body_battery_value} / {self._snapshot.body_battery_status.upper()}",
        )
        bar = QRectF(rect.left() + 14, rect.bottom() - 9, rect.width() - 28, 3)
        p.fillRect(bar, self._color(PALETTE.border, 180))
        p.fillRect(
            QRectF(bar.left(), bar.top(), bar.width() * 0.72, bar.height()),
            self._color(PALETTE.accent, 180),
        )
        p.setBrush(
            self._color(PALETTE.accent, 185 + int(50 * (0.5 + 0.5 * math.sin(self._t * 2.2))))
        )
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(rect.right() - 50, rect.top() + 16), 3.0, 3.0)
        p.setPen(self._color(PALETTE.text_dim, 210))
        p.drawText(QRectF(rect.right() - 43, rect.top() + 9, 36, 14), "LIVE")

    def _paint_system_rail(self, p: QPainter, rail: QRectF) -> None:
        gap = 10.0
        available = rail.height() - gap * 3.0
        heights = [
            available * 0.43,
            available * 0.19,
            available * 0.19,
            available * 0.19,
        ]
        y = rail.top()
        rects: list[QRectF] = []
        for height in heights:
            rects.append(QRectF(rail.left(), y, rail.width(), height))
            y += height + gap
        self._paint_bio_bars(p, rects[0], self._snapshot.bio_systems)
        self._paint_anomaly_panel(p, rects[1])
        self._paint_last_sync(p, rects[2])
        self._paint_data_source(p, rects[3])

    def _paint_bio_bars(self, p: QPainter, rect: QRectF, bars: tuple[BioSystemBar, ...]) -> None:
        self._draw_panel_rect(p, rect, accent=PALETTE.border, fill_alpha=160)
        self._rail_title(p, rect, "BIO METRICS")
        top = rect.top() + 43
        row_h = max(20.0, (rect.height() - 56) / max(1, len(bars)))
        for i, bar in enumerate(bars):
            y = top + i * row_h
            self._set_font(p, TYPE.nano, mono=True)
            p.setPen(self._color(PALETTE.text_dim, 205))
            p.drawText(QRectF(rect.left() + 14, y, rect.width() * 0.42, 14), bar.label.upper())
            track = QRectF(rect.left() + rect.width() * 0.54, y + 3, rect.width() * 0.30, 5)
            p.fillRect(track, self._color(PALETTE.border, 185))
            p.fillRect(
                QRectF(
                    track.left(),
                    track.top(),
                    track.width() * _clamp(bar.value / 100),
                    track.height(),
                ),
                self._color(PALETTE.accent, 172),
            )
            p.setPen(self._color(PALETTE.text_faint, 205))
            p.drawText(QRectF(track.right() + 7, y - 1, 30, 12), f"{bar.value}%")

    def _paint_anomaly_panel(self, p: QPainter, rect: QRectF) -> None:
        self._draw_panel_rect(p, rect, accent=PALETTE.border, fill_alpha=160)
        self._rail_title(p, rect, "ANOMALIES")
        self._set_font(p, TYPE.h2, mono=True, bold=True)
        p.setPen(self._color(PALETTE.accent, 235))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 38, 60, 20), str(self._snapshot.anomaly_count)
        )
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 63, rect.width() - 28, 14), "NO ACTIVE ANOMALIES"
        )

    def _paint_last_sync(self, p: QPainter, rect: QRectF) -> None:
        self._draw_panel_rect(p, rect, accent=PALETTE.border, fill_alpha=160)
        self._rail_title(p, rect, "LAST SYNC")
        self._set_font(p, TYPE.small, mono=True)
        p.setPen(self._color(PALETTE.text_dim, 215))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 39, rect.width() - 28, 16),
            self._snapshot.last_sync_time,
        )
        self._set_font(p, TYPE.nano, mono=True)
        p.setPen(self._color(PALETTE.text_faint, 205))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 61, rect.width() - 28, 14),
            self._snapshot.last_sync_date,
        )

    def _paint_data_source(self, p: QPainter, rect: QRectF) -> None:
        self._draw_panel_rect(p, rect, accent=PALETTE.border, fill_alpha=160)
        self._rail_title(p, rect, "DATA SOURCE")
        self._set_font(p, TYPE.h2, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text, 230))
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 39, rect.width() - 28, 18),
            f"{self._snapshot.data_sources_online} / {self._snapshot.data_sources_total}",
        )
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.positive, 220))
        p.drawText(QRectF(rect.left() + 14, rect.top() + 66, rect.width() - 28, 14), "ONLINE  ●")

    def _rail_title(self, p: QPainter, rect: QRectF, title: str) -> None:
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text, 220))
        p.drawText(QRectF(rect.left() + 14, rect.top() + 14, rect.width() - 28, 14), title)

    def _body_anchors(self, figure: QRectF) -> dict[str, QPointF]:
        cx = figure.center().x()
        return {
            "head": QPointF(cx, figure.top() + figure.height() * 0.13),
            "heart": QPointF(cx - figure.width() * 0.08, figure.top() + figure.height() * 0.33),
            "lungs": QPointF(cx + figure.width() * 0.12, figure.top() + figure.height() * 0.35),
            "core": QPointF(cx, figure.top() + figure.height() * 0.48),
            "pelvis": QPointF(cx, figure.top() + figure.height() * 0.57),
            "legs": QPointF(cx + figure.width() * 0.10, figure.top() + figure.height() * 0.78),
            "base": QPointF(cx, figure.bottom() + 14),
        }

    def _draw_panel_rect(
        self, p: QPainter, rect: QRectF, *, accent: str, fill_alpha: int = 175
    ) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(self._color(PALETTE.bg_panel, fill_alpha))
        p.drawRect(rect)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._color(PALETTE.border, 210), 1.0))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.setPen(QPen(self._color(accent, 225), 1.3))
        b = 11.0
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        for a, bpt, c in (
            (QPointF(x1, y1 + b), QPointF(x1, y1), QPointF(x1 + b, y1)),
            (QPointF(x2 - b, y1), QPointF(x2, y1), QPointF(x2, y1 + b)),
            (QPointF(x1, y2 - b), QPointF(x1, y2), QPointF(x1 + b, y2)),
            (QPointF(x2 - b, y2), QPointF(x2, y2), QPointF(x2, y2 - b)),
        ):
            p.drawLine(a, bpt)
            p.drawLine(bpt, c)

    def _draw_sparkline(
        self,
        p: QPainter,
        values: tuple[float, ...],
        rect: QRectF,
        color: str,
        *,
        filled: bool = False,
    ) -> None:
        if len(values) < 2:
            return
        lo, hi = min(values), max(values)
        rng = (hi - lo) or 1.0
        points = [
            QPointF(
                rect.left() + i * rect.width() / (len(values) - 1),
                rect.bottom() - ((v - lo) / rng) * rect.height(),
            )
            for i, v in enumerate(values)
        ]
        if filled:
            for point in points[::3]:
                p.setPen(QPen(self._color(color, 90), 1.0))
                p.drawLine(QPointF(point.x(), rect.bottom()), point)
        pen = QPen(self._color(color, 220), 1.2)
        p.setPen(pen)
        for a, b in zip(points, points[1:], strict=False):
            p.drawLine(a, b)

    def _set_font(self, p: QPainter, size: int, *, mono: bool = False, bold: bool = False) -> None:
        f = p.font()
        f.setPointSize(size)
        f.setBold(bold)
        f.setFamily((TYPE.mono if mono else TYPE.family).split(",")[0])
        p.setFont(f)

    def _color(self, value: str, alpha: int = 255) -> QColor:
        color = QColor(value)
        color.setAlpha(max(0, min(255, alpha)))
        return color


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
