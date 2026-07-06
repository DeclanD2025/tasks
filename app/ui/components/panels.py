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
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
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

    def __init__(self, text: str, parent=None, *, style: str = "",
                 interval_ms: int = 72, boot_delay_ms: int = 260):
        super().__init__(parent)
        self._full = text
        self._interval = interval_ms
        self._n = 0
        self._cursor_on = True
        self._settle_ticks = 0
        self._booting = True
        if style:
            self.setStyleSheet(style)
        self.setText(" ")  # reserve height before typing starts

        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._tick)
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start(360)
        # Brief boot delay (blinking cursor only) before characters stream in —
        # makes the heading feel like a module powering up, not a typewriter.
        QTimer.singleShot(boot_delay_ms, self._begin)

    def _begin(self):
        self._booting = False
        self._type_timer.start(self._interval)

    def _render(self):
        cursor = "\u258c" if self._cursor_on else " "
        shown = "" if self._booting else self._full[: self._n]
        self.setText(shown + cursor)

    def _tick(self):
        if self._n < len(self._full):
            self._n += 1
            self._render()
            # Micro-stall after a space, as if streaming the next token in.
            nxt = self._interval * 3 if self._full[self._n - 1] == " " else self._interval
            self._type_timer.start(nxt)
        else:
            # Typed out; let the cursor blink a while, then settle.
            self._settle_ticks += 1
            if self._settle_ticks > 7:
                self._type_timer.stop()
                self._blink_timer.stop()
                self.setText(self._full)

    def _blink(self):
        self._cursor_on = not self._cursor_on
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
    """Image-backed full-height biometric telemetry scan.

    ``illness`` (0.0 .. 1.0) shifts the panel's cyan accent toward red — the
    sickness-protocol wash. 0.0 is the normal blue health page; 1.0 is a fully
    red, unwell page.
    """

    def __init__(self, snapshot: HealthDashboardSnapshot, parent=None, *, illness: float = 0.0):
        accent = _blend_hex(PALETTE.accent, _ILLNESS_RED, illness)
        super().__init__(
            "BIOMETRIC SCAN", "HLT-SCN", parent,
            status=snapshot.scan_status,
            accent=accent if illness > 0 else None,
        )
        self._scan = _BiometricScanCanvas(snapshot, illness=illness)
        self.body.addWidget(self._scan)


class BiometricPanel(BiometricScanPanel):
    """Backward-compatible alias for older Health page imports."""


# Target hue for the illness wash. The page interpolates PALETTE.accent -> this.
_ILLNESS_RED = "#ff3b46"


def _blend_hex(base: str, target: str, t: float) -> str:
    """Linear-blend two hex colours; t in [0,1] (0=base, 1=target)."""
    t = max(0.0, min(1.0, t))
    b, g = QColor(base), QColor(target)
    r = round(b.red() + (g.red() - b.red()) * t)
    gr = round(b.green() + (g.green() - b.green()) * t)
    bl = round(b.blue() + (g.blue() - b.blue()) * t)
    return f"#{r:02x}{gr:02x}{bl:02x}"


class _BiometricScanCanvas(QWidget):
    _LEADER_KEYS = {"sleep", "hrv", "vo2", "training_load"}

    def __init__(self, snapshot: HealthDashboardSnapshot, parent=None, *, illness: float = 0.0):
        super().__init__(parent)
        self._snapshot = snapshot
        self._illness = max(0.0, min(1.0, illness))
        # Resolve the accent pair once: every PALETTE.accent / accent_dim used in
        # painting is remapped through _color, so shifting these two shifts the
        # whole scan from cyan toward red.
        self._accent = _blend_hex(PALETTE.accent, _ILLNESS_RED, self._illness)
        self._accent_dim = _blend_hex(PALETTE.accent_dim, _ILLNESS_RED, self._illness)
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
        self._paint_scan_field(p, w, h, layout["stage"], layout["figure"], layout["pedestal"])
        anchors = self._body_anchors(layout["figure"])
        self._paint_metric_leaders(p, layout["metric_slots"], anchors)
        self._paint_model(p, layout["figure"])
        self._paint_pedestal(p, layout["pedestal"], layout["scan_status"])
        self._paint_metric_cards(p, layout["metric_slots"])
        self._paint_leader_terminators(p, layout["metric_slots"], anchors)
        self._paint_scan_status(p, layout["scan_status"])
        self._paint_system_rail(p, layout["rail"])
        p.end()

    # The body content within the PNG (non-transparent bbox), as fractions of
    # the image. Used to place the figure and ground the pedestal under the feet
    # without ever altering the asset.
    _BODY_TOP_FRAC = 0.020
    _BODY_BOTTOM_FRAC = 0.980
    _BODY_CX_FRAC = 0.512

    def _layout(self, w: int, h: int) -> dict[str, object]:
        margin = 18.0
        rail_w = max(190.0, min(232.0, w * 0.155))
        gap = max(20.0, min(30.0, w * 0.018))
        card_w = max(212.0, min(272.0, w * 0.188))

        rail = QRectF(w - rail_w - margin, margin, rail_w, h - margin * 2)

        # Four cards per side, evenly distributed over the working height.
        top_y = margin + 6.0
        bottom_pad = 118.0  # clearance for the grounded pedestal + status chip
        card_h = max(92.0, min(118.0, (h - top_y - bottom_pad - 3 * 18.0) / 4.0))
        step = card_h + 18.0

        left_x = margin
        right_x = rail.left() - gap - card_w

        # Central scan chamber sits between the two card columns.
        stage_left = left_x + card_w + gap
        stage_right = right_x - gap
        stage = QRectF(stage_left, margin, max(260.0, stage_right - stage_left), h - margin * 2)

        # Figure: as tall as the chamber allows, centred, feet grounded above the
        # pedestal. We scale by the BODY bbox so the visible body fills the space.
        cx = stage.center().x()
        body_frac_h = self._BODY_BOTTOM_FRAC - self._BODY_TOP_FRAC
        avail_h = stage.height() - bottom_pad - 16.0
        figure_h = min(avail_h / body_frac_h, stage.width() * 2.1)
        figure_w = figure_h * self._image_aspect()
        figure = QRectF(0, 0, figure_w, figure_h)
        figure.moveCenter(QPointF(cx, 0))
        figure.moveTop(stage.top() + 8.0)

        # Pedestal centred under the true feet position.
        feet_y = figure.top() + figure.height() * self._BODY_BOTTOM_FRAC
        body_cx = figure.left() + figure.width() * self._BODY_CX_FRAC
        pedestal = QRectF(0, 0, figure_w * 1.5, 70.0)
        pedestal.moveCenter(QPointF(body_cx, feet_y + 26.0))

        left_cards = [c for c in self._snapshot.metric_cards if c.side == "left"]
        right_cards = [c for c in self._snapshot.metric_cards if c.side == "right"]
        slots: list[tuple[HealthMetricCard, QRectF]] = []
        for idx, card in enumerate(left_cards[:4]):
            slots.append((card, QRectF(left_x, top_y + idx * step, card_w, card_h)))
        for idx, card in enumerate(right_cards[:4]):
            slots.append((card, QRectF(right_x, top_y + idx * step, card_w, card_h)))

        status = QRectF(0, 0, min(398.0, stage.width() - 16.0), 38.0)
        status.moveCenter(QPointF(body_cx, pedestal.bottom() + 26.0))

        return {
            "rail": rail,
            "stage": stage,
            "figure": figure,
            "pedestal": pedestal,
            "metric_slots": slots,
            "scan_status": status,
        }

    def _image_aspect(self) -> float:
        if self._pixmap.isNull():
            return 0.478
        return self._pixmap.width() / max(1, self._pixmap.height())

    def _paint_scan_field(
        self, p: QPainter, w: int, h: int, stage: QRectF, figure: QRectF, pedestal: QRectF
    ) -> None:
        # Faint global grid — quieter than before so it never competes with text.
        step = 52
        x = (stage.center().x() % step)
        while x < w:
            p.setPen(QPen(self._color(PALETTE.grid, 34), 1.0))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = 0.0
        while y < h:
            p.setPen(QPen(self._color(PALETTE.grid, 26), 1.0))
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += step

        # --- Scan chamber: concentric guide rings centred on the torso. ------
        body_cx = figure.left() + figure.width() * self._BODY_CX_FRAC
        torso_y = figure.top() + figure.height() * 0.40
        chamber = QPointF(body_cx, torso_y)
        max_r = min(stage.width() * 0.46, figure.height() * 0.40)

        # Soft radial glow behind the figure to lift it off the grid.
        glow = QRadialGradient(chamber, max_r * 1.5)
        glow.setColorAt(0.0, self._color(PALETTE.accent, 26))
        glow.setColorAt(0.45, self._color(PALETTE.accent_dim, 12))
        glow.setColorAt(1.0, self._color(PALETTE.accent, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(chamber, max_r * 1.5, max_r * 1.7)

        for i, frac in enumerate((0.52, 0.78, 1.0)):
            r = max_r * frac
            p.setPen(QPen(self._color(PALETTE.accent_dim, 52 - i * 10), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(chamber, r, r)
        # Radial guides (subtle), every 30°.
        for k in range(12):
            ang = math.radians(k * 30)
            p.setPen(QPen(self._color(PALETTE.accent_dim, 22), 1.0))
            p.drawLine(
                chamber,
                QPointF(chamber.x() + math.cos(ang) * max_r,
                        chamber.y() + math.sin(ang) * max_r),
            )
        # One slow rotating sweep arc — restrained, not a spinning radar.
        sweep = (self._t * 0.30) % math.tau
        p.setPen(QPen(self._color(PALETTE.accent, 90), 1.4))
        span = 0.5
        rect_r = QRectF(chamber.x() - max_r, chamber.y() - max_r, max_r * 2, max_r * 2)
        p.drawArc(rect_r, int(math.degrees(-sweep) * 16), int(math.degrees(span) * 16))

        # --- Vertical scan line sweeping the figure (kept, but softer). ------
        scan_y = figure.top() + (0.5 + 0.5 * math.sin(self._t * 0.7)) * (
            figure.height() * self._BODY_BOTTOM_FRAC
        )
        band = QLinearGradient(0, scan_y - 9, 0, scan_y + 9)
        band.setColorAt(0.0, self._color(PALETTE.accent, 0))
        band.setColorAt(0.5, self._color(PALETTE.accent, 16))
        band.setColorAt(1.0, self._color(PALETTE.accent, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(band)
        p.drawRect(QRectF(figure.left() - 6, scan_y - 9, figure.width() + 12, 18))
        p.setPen(QPen(self._color(PALETTE.accent, 60), 1.0))
        p.drawLine(QPointF(figure.left() + 4, scan_y), QPointF(figure.right() - 4, scan_y))

    def _paint_model(self, p: QPainter, figure: QRectF) -> None:
        if self._pixmap.isNull():
            self._set_font(p, TYPE.small, mono=True, bold=True)
            p.setPen(self._color(PALETTE.coral, 200))
            p.drawText(figure, Qt.AlignCenter, "WIRE MODEL MISSING")
            return

        # The image is drawn unchanged. A faint scaled copy beneath adds a soft
        # halo so the model lifts off the chamber — the asset itself is intact.
        pulse = 1.0 + math.sin(self._t * 1.7) * 0.010
        glow = QRectF(figure)
        glow.setWidth(figure.width() * (1.04 * pulse))
        glow.setHeight(figure.height() * (1.028 * pulse))
        glow.moveCenter(figure.center())
        p.setOpacity(0.16)
        p.drawPixmap(glow.toRect(), self._pixmap)
        p.setOpacity(0.96)
        p.drawPixmap(figure.toRect(), self._pixmap)
        p.setOpacity(1.0)

    def _paint_pedestal(self, p: QPainter, pedestal: QRectF, status: QRectF) -> None:
        """A grounded holographic scan base under the feet, fused with status."""
        cx = pedestal.center().x()
        base_y = pedestal.center().y()
        pulse = 1.0 + math.sin(self._t * 1.3) * 0.03

        # Soft projected-light fill first (under the rings).
        fill = QRadialGradient(QPointF(cx, base_y), pedestal.width() * 0.55)
        fill.setColorAt(0.0, self._color(PALETTE.accent, 60))
        fill.setColorAt(0.6, self._color(PALETTE.accent_dim, 24))
        fill.setColorAt(1.0, self._color(PALETTE.accent, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QPointF(cx, base_y), pedestal.width() * 0.55, pedestal.width() * 0.14)

        # Light shafts rising from the ring toward the feet (behind rings).
        for sx in (-0.46, -0.22, 0.22, 0.46):
            x = cx + pedestal.width() * sx
            p.setPen(QPen(self._color(PALETTE.accent, 50), 1.0))
            p.drawLine(QPointF(x, base_y), QPointF(cx + (x - cx) * 0.35, base_y - 34))

        # Stacked elliptical rings — clearly a pedestal the figure stands on.
        for i, (rw, alpha) in enumerate(((1.0, 200), (0.72, 130), (0.46, 80))):
            rx = pedestal.width() * 0.5 * rw * (pulse if i == 0 else 1.0)
            ry = rx * 0.18
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self._color(PALETTE.accent, alpha), 1.6 if i == 0 else 1.1))
            p.drawEllipse(QPointF(cx, base_y), rx, ry)
        # Bright tick marks around the outer ring for a scanned-base feel.
        outer = pedestal.width() * 0.5
        for k in range(24):
            ang = math.radians(k * 15)
            ex, ey = math.cos(ang) * outer, math.sin(ang) * outer * 0.18
            p.setPen(QPen(self._color(PALETTE.accent, 90), 1.0))
            p.drawPoint(QPointF(cx + ex, base_y + ey))

        # A restrained tether makes the base and status module read as one scan system.
        p.setPen(QPen(self._color(PALETTE.accent_dim, 52), 1.0))
        p.drawLine(QPointF(cx, base_y + outer * 0.18 + 4), QPointF(cx, status.top() + 2))

    def _paint_metric_leaders(
        self,
        p: QPainter,
        slots: list[tuple[HealthMetricCard, QRectF]],
        anchors: dict[str, QPointF],
    ) -> None:
        # Leader paths sit behind the image. This keeps callouts intentional
        # without drawing hard cyan routes over the body mesh.
        for card, rect in slots:
            if not card.sparkline and card.value == "—":
                continue  # NO DATA cards don't claim a body region
            anchor = self._anchor_for(card, anchors)
            if anchor is None:
                continue
            self._draw_leader(p, card, rect, anchor)

    def _paint_metric_cards(
        self,
        p: QPainter,
        slots: list[tuple[HealthMetricCard, QRectF]],
    ) -> None:
        for card, rect in slots:
            self._draw_metric_card(p, card, rect)

    def _paint_leader_terminators(
        self,
        p: QPainter,
        slots: list[tuple[HealthMetricCard, QRectF]],
        anchors: dict[str, QPointF],
    ) -> None:
        for card, rect in slots:
            if not card.sparkline and card.value == "—":
                continue
            anchor = self._anchor_for(card, anchors)
            if anchor is None:
                continue
            self._draw_leader_terminator(p, card, rect, anchor)

    def _anchor_for(
        self, card: HealthMetricCard, anchors: dict[str, QPointF]
    ) -> QPointF | None:
        keyed = {
            "hrv": "heart_left",
            "rhr": "heart_right",
            "vo2": "lungs_right",
            "distance": "right_thigh",
            "readiness": "feet",
        }.get(card.key)
        return anchors.get(keyed or card.target_region)

    def _draw_leader(
        self, p: QPainter, card: HealthMetricCard, rect: QRectF, anchor: QPointF
    ) -> None:
        """A clean right-angled leader from the card to a body landmark."""
        left = card.side == "left"
        edge_x = rect.right() if left else rect.left()
        start = QPointF(edge_x, rect.center().y())
        # Horizontal run out of the card, then a routed bend to the anchor.
        mid_x = anchor.x() + (-46 if left else 46)
        path = QPainterPath(start)
        path.lineTo(QPointF(mid_x, start.y()))
        path.lineTo(QPointF(mid_x, anchor.y()))
        path.lineTo(anchor)
        p.setPen(QPen(self._color(PALETTE.accent, 78), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _draw_leader_terminator(
        self, p: QPainter, card: HealthMetricCard, rect: QRectF, anchor: QPointF
    ) -> None:
        left = card.side == "left"
        edge_x = rect.right() if left else rect.left()
        start = QPointF(edge_x, rect.center().y())
        # Terminators: square at the card, ringed dot on the body.
        p.setPen(Qt.NoPen)
        p.setBrush(self._color(PALETTE.accent, 135))
        p.drawRect(QRectF(start.x() - 1.5, start.y() - 1.5, 3.0, 3.0))
        p.setPen(QPen(self._color(PALETTE.accent, 180), 1.1))
        p.setBrush(self._color(PALETTE.bg_void, 200))
        p.drawEllipse(anchor, 3.0, 3.0)
        p.setBrush(self._color(PALETTE.accent, 220))
        p.setPen(Qt.NoPen)
        p.drawEllipse(anchor, 1.25, 1.25)

    def _draw_metric_card(self, p: QPainter, card: HealthMetricCard, rect: QRectF) -> None:
        no_data = (card.value == "—") and not card.sparkline
        accent = PALETTE.orange if card.warning else PALETTE.accent
        # NO DATA cards read quieter: dim accent, lower fill, no corner brackets.
        if no_data:
            self._draw_card_surface(
                rect,
                p,
                side=card.side,
                accent=PALETTE.border,
                fill_alpha=92,
                brackets=False,
            )
        else:
            self._draw_card_surface(
                rect,
                p,
                side=card.side,
                accent=accent,
                fill_alpha=168,
                brackets=True,
            )

        pad = 15.0
        # Row 1: label (left) · module code (right).
        self._set_font(p, TYPE.micro, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text_dim if no_data else PALETTE.text, 210))
        self._tracked_text(p, QRectF(rect.left() + pad, rect.top() + 13,
                                     rect.width() - pad * 2, 14), card.label.upper(), 2.0)
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.accent_dim, 110 if no_data else 200))
        p.drawText(QRectF(rect.right() - 84, rect.top() + 13, 70, 13),
                   Qt.AlignRight, card.code.upper())

        # Row 2: large value + unit.
        self._set_font(p, 23, mono=False, bold=True)
        p.setPen(self._color(PALETTE.text_faint if no_data else PALETTE.text,
                             170 if no_data else 248))
        value_y = rect.top() + 36
        p.drawText(QRectF(rect.left() + pad, value_y, rect.width() * 0.6, 30),
                   Qt.AlignLeft | Qt.AlignVCenter, card.value)
        if card.unit and not no_data:
            ux = rect.left() + pad + p.fontMetrics().horizontalAdvance(card.value) + 7
            self._set_font(p, TYPE.small, mono=False, bold=False)
            p.setPen(self._color(PALETTE.text_dim, 220))
            p.drawText(QRectF(ux, value_y + 6, rect.width() * 0.35, 20),
                       Qt.AlignLeft | Qt.AlignVCenter, card.unit)

        # Row 2 (right): status tag chip.
        self._draw_status_tag(p, card, rect, accent if not no_data else PALETTE.text_faint,
                              no_data)

        # Row 3: subtitle detail (the metric's meaning), muted.
        self._set_font(p, TYPE.nano, mono=True, bold=False)
        p.setPen(self._color(PALETTE.text_faint, 150 if no_data else 195))
        sub = self._primary_detail(card) if not no_data else card.secondary_label.upper()
        self._tracked_text(p, QRectF(rect.left() + pad, rect.top() + 67,
                                     rect.width() - pad * 2, 12), sub, 1.4)

        # Row 4: subtle sparkline (only with real data).
        if not no_data:
            self._draw_sparkline(
                p, card.sparkline,
                QRectF(rect.left() + pad, rect.bottom() - 22, rect.width() - pad * 2, 14),
                accent, filled=True,
            )

    def _draw_status_tag(
        self, p: QPainter, card: HealthMetricCard, rect: QRectF, accent: str, no_data: bool
    ) -> None:
        text = card.secondary_value.upper()
        if not text:
            return
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        tw = p.fontMetrics().horizontalAdvance(text)
        chip = QRectF(rect.right() - 15 - tw - 16, rect.top() + 38, tw + 16, 16)
        col = PALETTE.text_faint if no_data else accent
        p.setPen(QPen(self._color(col, 90), 1.0))
        p.setBrush(self._color(col, 26))
        p.drawRoundedRect(chip, 2.0, 2.0)
        p.setPen(self._color(col, 235 if not no_data else 170))
        p.drawText(chip, Qt.AlignCenter, text)

    def _draw_card_surface(
        self,
        rect: QRectF,
        p: QPainter,
        *,
        side: str,
        accent: str,
        fill_alpha: int,
        brackets: bool,
    ) -> None:
        # Vertical gradient fill — premium depth instead of a flat block.
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, self._color(PALETTE.bg_panel_alt, fill_alpha))
        grad.setColorAt(1.0, self._color(PALETTE.bg_panel, min(255, fill_alpha + 20)))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 5.0, 5.0)
        # Hairline border + a thin accent edge on the inner side.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._color(PALETTE.border, 200), 1.0))
        p.drawRoundedRect(rect, 5.0, 5.0)
        p.setPen(QPen(self._color(accent, 135 if brackets else 70), 1.5))
        edge_x = rect.right() - 1 if side == "left" else rect.left() + 1
        p.drawLine(QPointF(edge_x, rect.top() + 9),
                   QPointF(edge_x, rect.bottom() - 9))
        if brackets:
            self._corner_brackets(p, rect, accent, 9.0, 150)

    def _corner_brackets(
        self, p: QPainter, rect: QRectF, accent: str, b: float, alpha: int
    ) -> None:
        p.setPen(QPen(self._color(accent, alpha), 1.2))
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        for a, bpt, c in (
            (QPointF(x1, y1 + b), QPointF(x1, y1), QPointF(x1 + b, y1)),
            (QPointF(x2 - b, y1), QPointF(x2, y1), QPointF(x2, y1 + b)),
            (QPointF(x1, y2 - b), QPointF(x1, y2), QPointF(x1 + b, y2)),
            (QPointF(x2 - b, y2), QPointF(x2, y2), QPointF(x2, y2 - b)),
        ):
            p.drawLine(a, bpt)
            p.drawLine(bpt, c)

    def _tracked_text(self, p: QPainter, rect: QRectF, text: str, spacing: float) -> None:
        f = p.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        p.setFont(f)
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.0)
        p.setFont(f)

    def _primary_detail(self, card: HealthMetricCard) -> str:
        details = {
            "sleep": "LAST NIGHT",
            "hrv": "7-DAY SDNN",
            "recovery": "DERIVED · HRV",
            "weight": "LATEST READING",
            "rhr": "RESTING BPM",
            "vo2": "ML / KG / MIN",
            "distance": "WALK + RUN",
            "training_load": "7-DAY LOAD",
            "readiness": "OVERALL",
        }
        return details.get(card.key, "CURRENT")

    def _paint_scan_status(self, p: QPainter, rect: QRectF) -> None:
        """A single status chip fused with the pedestal: scan state + battery."""
        # Pill background.
        p.setPen(QPen(self._color(PALETTE.accent, 70), 1.0))
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, self._color(PALETTE.bg_panel_alt, 230))
        grad.setColorAt(1.0, self._color(PALETTE.bg_panel, 235))
        p.setBrush(grad)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        # Pulsing live dot.
        dot = QPointF(rect.left() + 18, rect.center().y())
        a = 170 + int(70 * (0.5 + 0.5 * math.sin(self._t * 2.2)))
        p.setPen(Qt.NoPen)
        p.setBrush(self._color(PALETTE.positive, a))
        p.drawEllipse(dot, 3.4, 3.4)

        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text, 230))
        self._tracked_text(
            p,
            QRectF(rect.left() + 32, rect.top(), rect.width() - 174, rect.height()),
            "BIOMETRIC SCAN ACTIVE",
            0.9,
        )
        # Battery readout on the right.
        batt = self._snapshot.body_battery_value
        label = f"BATTERY {batt}" if batt and batt != "—" else "BATTERY —"
        p.setPen(self._color(PALETTE.accent, 215))
        p.drawText(QRectF(rect.right() - 140, rect.top(), 124, rect.height()),
                   Qt.AlignRight | Qt.AlignVCenter, label)

    def _paint_system_rail(self, p: QPainter, rail: QRectF) -> None:
        # One cohesive panel with internal sections separated by hairlines —
        # not a stack of disconnected boxes.
        grad = QLinearGradient(rail.topLeft(), rail.bottomLeft())
        grad.setColorAt(0.0, self._color(PALETTE.bg_panel_alt, 180))
        grad.setColorAt(1.0, self._color(PALETTE.bg_panel, 200))
        p.setPen(QPen(self._color(PALETTE.border, 200), 1.0))
        p.setBrush(grad)
        p.drawRoundedRect(rail, 6.0, 6.0)
        self._corner_brackets(p, rail, PALETTE.accent, 12.0, 120)

        bars = self._snapshot.bio_systems
        bio_h = 56 + len(bars) * 22 + 14
        gap = 1.0
        rest = (rail.height() - bio_h - gap * 3)
        sections = [
            (bio_h, "bio"),
            (rest * 0.34, "anomaly"),
            (rest * 0.33, "sync"),
            (rest * 0.33, "source"),
        ]
        y = rail.top()
        for i, (height, kind) in enumerate(sections):
            sect = QRectF(rail.left(), y, rail.width(), height)
            if i:
                p.setPen(QPen(self._color(PALETTE.border, 140), 1.0))
                p.drawLine(QPointF(rail.left() + 14, y), QPointF(rail.right() - 14, y))
            if kind == "bio":
                self._paint_bio_bars(p, sect, bars)
            elif kind == "anomaly":
                self._paint_anomaly_panel(p, sect)
            elif kind == "sync":
                self._paint_last_sync(p, sect)
            else:
                self._paint_data_source(p, sect)
            y += height + gap

    def _paint_bio_bars(self, p: QPainter, rect: QRectF, bars: tuple[BioSystemBar, ...]) -> None:
        self._rail_title(p, rect, "CAPTURED SIGNALS")
        top = rect.top() + 44
        row_h = 22.0
        for i, bar in enumerate(bars):
            y = top + i * row_h
            present = bar.value >= 50
            self._set_font(p, TYPE.nano, mono=True)
            p.setPen(self._color(PALETTE.text_dim if present else PALETTE.text_faint, 210))
            p.drawText(QRectF(rect.left() + 16, y - 1, rect.width() * 0.42, 14),
                       Qt.AlignVCenter, bar.label.upper())
            track = QRectF(rect.left() + rect.width() * 0.50, y + 3, rect.width() * 0.30, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(self._color(PALETTE.border, 170))
            p.drawRoundedRect(track, 2, 2)
            if present:
                fill = QRectF(track.left(), track.top(),
                              track.width() * _clamp(bar.value / 100), track.height())
                p.setBrush(self._color(PALETTE.accent, 190))
                p.drawRoundedRect(fill, 2, 2)
            # ON / — marker instead of a misleading % for binary presence.
            p.setPen(self._color(PALETTE.accent if present else PALETTE.text_faint, 200))
            p.drawText(QRectF(track.right() + 9, y - 2, 34, 14), Qt.AlignVCenter,
                       "ON" if present else "—")

    def _paint_anomaly_panel(self, p: QPainter, rect: QRectF) -> None:
        self._rail_title(p, rect, "ANOMALIES")
        self._set_font(p, TYPE.display, mono=False, bold=True)
        p.setPen(self._color(PALETTE.positive if self._snapshot.anomaly_count == 0
                             else PALETTE.coral, 235))
        p.drawText(QRectF(rect.left() + 16, rect.top() + 34, 80, 34),
                   Qt.AlignVCenter, str(self._snapshot.anomaly_count))
        self._set_font(p, TYPE.nano, mono=True)
        p.setPen(self._color(PALETTE.text_faint, 200))
        p.drawText(QRectF(rect.left() + 16, rect.bottom() - 24, rect.width() - 30, 14),
                   "NO ACTIVE ANOMALIES" if self._snapshot.anomaly_count == 0
                   else "REVIEW REQUIRED")

    def _paint_last_sync(self, p: QPainter, rect: QRectF) -> None:
        self._rail_title(p, rect, "LAST SYNC")
        self._set_font(p, TYPE.body, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text, 225))
        p.drawText(QRectF(rect.left() + 16, rect.top() + 34, rect.width() - 30, 18),
                   Qt.AlignVCenter, self._snapshot.last_sync_time)
        self._set_font(p, TYPE.nano, mono=True)
        p.setPen(self._color(PALETTE.text_faint, 200))
        p.drawText(QRectF(rect.left() + 16, rect.bottom() - 24, rect.width() - 30, 14),
                   self._snapshot.last_sync_date)

    def _paint_data_source(self, p: QPainter, rect: QRectF) -> None:
        self._rail_title(p, rect, "DATA SOURCE")
        online = self._snapshot.data_sources_online
        self._set_font(p, TYPE.h1, mono=False, bold=True)
        p.setPen(self._color(PALETTE.text, 232))
        p.drawText(QRectF(rect.left() + 16, rect.top() + 32, rect.width() - 30, 22),
                   Qt.AlignVCenter,
                   f"{online} / {self._snapshot.data_sources_total}")
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        col = PALETTE.positive if online else PALETTE.text_faint
        p.setPen(self._color(col, 220))
        p.drawText(QRectF(rect.left() + 16, rect.bottom() - 24, rect.width() - 30, 14),
                   ("ONLINE  ●" if online else "NO SOURCE  ○"))

    def _rail_title(self, p: QPainter, rect: QRectF, title: str) -> None:
        self._set_font(p, TYPE.nano, mono=True, bold=True)
        p.setPen(self._color(PALETTE.text_dim, 220))
        self._tracked_text(p, QRectF(rect.left() + 16, rect.top() + 16, rect.width() - 30, 14),
                           title, 1.6)

    def _body_anchors(self, figure: QRectF) -> dict[str, QPointF]:
        """Anatomical anchor points, derived from the model's real content bbox.

        Vertical positions are fractions of the body span (top→feet) measured
        from the PNG; horizontal offsets land on the actual body, not empty
        space. This keeps every callout terminating on a sensible region.
        """
        body_top = figure.top() + figure.height() * self._BODY_TOP_FRAC
        body_h = figure.height() * (self._BODY_BOTTOM_FRAC - self._BODY_TOP_FRAC)
        cx = figure.left() + figure.width() * self._BODY_CX_FRAC
        w = figure.width()

        def at(yfrac: float, xoff: float = 0.0) -> QPointF:
            return QPointF(cx + w * xoff, body_top + body_h * yfrac)

        return {
            "head": at(0.07),                 # Sleep
            "heart": at(0.30, -0.075),        # fallback heart landmark
            "heart_left": at(0.30, -0.095),   # HRV — anatomical left chest
            "heart_right": at(0.31, 0.040),   # RHR — central/right chest route
            "lungs": at(0.27, 0.105),         # fallback lungs
            "lungs_right": at(0.265, 0.118),  # VO2 — right upper chest
            "core": at(0.44),                 # Recovery — solar plexus
            "pelvis": at(0.52, -0.02),        # Weight — waist/hips
            "legs": at(0.72, 0.07),           # fallback leg landmark
            "right_thigh": at(0.72, 0.082),   # Distance — right thigh
            "base": at(0.95),                 # fallback feet / ground
            "feet": at(0.965, 0.006),         # Readiness — between feet/base
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
        # Remap the palette accent pair to the (possibly illness-shifted)
        # instance accents, so the whole scan recolours from one place.
        if self._illness > 0:
            if value == PALETTE.accent:
                value = self._accent
            elif value == PALETTE.accent_dim:
                value = self._accent_dim
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
