"""Reusable route-map widgets for ORION Fitness.

No external tiles are used in this first version: GPS stays local, and the
widget renders a polished dark schematic map with auto-fit, pan/zoom,
start/finish markers, distance markers, direction hints and overlays.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.core.logging import get_logger
from app.domains.fitness import route_service as routes
from app.ui.themes.theme import PALETTE, TYPE

log = get_logger(__name__)


class RouteMap(QWidget):
    def __init__(
        self,
        *,
        route_geometry: list[dict] | None = None,
        attempt_geometry: list[dict] | None = None,
        comparison_geometry: list[dict] | None = None,
        segments: list[Any] | None = None,
        show_distance_markers: bool = True,
        show_start_finish: bool = True,
        show_direction: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._route = routes.normalise_route_points(route_geometry)
        self._attempt = routes.normalise_route_points(attempt_geometry)
        self._comparison = routes.normalise_route_points(comparison_geometry)
        self._segments = segments or []
        self._show_distance = show_distance_markers
        self._show_start_finish = show_start_finish
        self._show_direction = show_direction
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._drag_origin: QPointF | None = None
        self.setMinimumHeight(280)
        self.setMouseTracking(True)

    def set_data(
        self,
        *,
        route_geometry: list[dict] | None = None,
        attempt_geometry: list[dict] | None = None,
        comparison_geometry: list[dict] | None = None,
        segments: list[Any] | None = None,
    ) -> None:
        self._route = routes.normalise_route_points(route_geometry)
        self._attempt = routes.normalise_route_points(attempt_geometry)
        self._comparison = routes.normalise_route_points(comparison_geometry)
        if segments is not None:
            self._segments = segments
        self.update()

    def wheelEvent(self, event):  # noqa: N802
        factor = 1.12 if event.angleDelta().y() > 0 else 0.88
        self._zoom = max(0.7, min(5.0, self._zoom * factor))
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_origin is None:
            return
        delta = event.position() - self._drag_origin
        self._pan += delta
        self._drag_origin = event.position()
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = None
            self.setCursor(Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        # A raised exception inside paintEvent is fatal to the whole app, so the
        # render is fully guarded: any failure degrades to a quiet placeholder
        # instead of crashing ORION, and the painter is always ended.
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            self._paint(p)
        except Exception:
            log.exception("RouteMap paint failed; showing placeholder")
            try:
                self._paint_render_error(p)
            except Exception:
                pass
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        self._paint_background(p)
        all_points = [*self._route, *self._attempt, *self._comparison]
        if not all_points:
            self._paint_empty_state(p)
            return
        transform = _Transform(all_points, self.width(), self.height(), self._zoom, self._pan)
        if self._comparison:
            self._paint_path(p, transform, self._comparison, QColor(PALETTE.violet), 2.0, alpha=110)
        if self._route:
            self._paint_path(p, transform, self._route, QColor(PALETTE.accent), 3.2, alpha=230)
        if self._attempt:
            self._paint_path(p, transform, self._attempt, QColor(PALETTE.orange), 2.4, alpha=190)
        if self._show_distance:
            self._paint_distance_markers(p, transform, self._route or self._attempt)
        if self._show_direction:
            self._paint_direction_markers(p, transform, self._route or self._attempt)
        if self._segments:
            self._paint_segments(p, transform, self._route or self._attempt)
        if self._show_start_finish:
            self._paint_start_finish(p, transform, self._route or self._attempt)
        self._paint_legend(p)

    def _paint_render_error(self, p: QPainter) -> None:
        p.fillRect(self.rect(), QColor(PALETTE.bg_panel))
        p.setPen(QColor(PALETTE.text_faint))
        font = QFont(TYPE.mono.split(",")[0], TYPE.nano)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, "ROUTE MAP UNAVAILABLE")

    def _paint_background(self, p: QPainter) -> None:
        p.fillRect(self.rect(), QColor(PALETTE.bg_panel_alt))
        grid = QColor(PALETTE.border_soft)
        grid.setAlpha(45)
        p.setPen(QPen(grid, 1))
        step = 36
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(QColor(PALETTE.border), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def _paint_empty_state(self, p: QPainter) -> None:
        p.setPen(QColor(PALETTE.text_dim))
        font = QFont(TYPE.family.split(",")[0], TYPE.body)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, "NO GPS ROUTE DATA AVAILABLE")
        p.setPen(QColor(PALETTE.text_faint))
        small = QFont(TYPE.mono.split(",")[0], TYPE.nano)
        p.setFont(small)
        p.drawText(0, self.height() // 2 + 28, self.width(), 30, Qt.AlignCenter, "ROUTE METRICS STILL WORK WITHOUT A MAP")

    def _paint_path(self, p: QPainter, transform, points: list[dict], color: QColor, width: float, *, alpha: int) -> None:
        if len(points) < 2:
            return
        color.setAlpha(alpha)
        glow = QColor(color)
        glow.setAlpha(45)
        path = QPainterPath()
        first = transform.point(points[0])
        path.moveTo(first)
        for row in points[1:]:
            path.lineTo(transform.point(row))
        p.setPen(QPen(glow, width + 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)

    def _paint_start_finish(self, p: QPainter, transform, points: list[dict]) -> None:
        start, finish = routes.extract_start_finish(points)
        if not start or not finish:
            return
        for label, row, color in (("S", start, QColor(PALETTE.positive)), ("F", finish, QColor(PALETTE.coral))):
            pt = transform.point(row)
            p.setBrush(color)
            p.setPen(QPen(QColor(PALETTE.bg_void), 2))
            p.drawEllipse(pt, 8, 8)
            p.setPen(QColor(PALETTE.bg_void))
            font = QFont(TYPE.mono.split(",")[0], TYPE.nano)
            font.setBold(True)
            p.setFont(font)
            p.drawText(pt.x() - 5, pt.y() + 4, label)

    def _paint_distance_markers(self, p: QPainter, transform, points: list[dict]) -> None:
        markers = routes.calculate_distance_markers(points, 500.0)
        font = QFont(TYPE.mono.split(",")[0], TYPE.nano)
        p.setFont(font)
        for marker in markers[:18]:
            pt = transform.point(marker)
            p.setPen(QPen(QColor(PALETTE.text_dim), 1))
            p.setBrush(QColor(PALETTE.bg_panel))
            p.drawEllipse(pt, 5, 5)
            label = f"{marker['distance_meters'] / 1000:.1f}K"
            p.setPen(QColor(PALETTE.text_faint))
            p.drawText(pt.x() + 7, pt.y() - 5, label)

    def _paint_direction_markers(self, p: QPainter, transform, points: list[dict]) -> None:
        markers = routes.calculate_direction_markers(points, every=max(8, len(points) // 6 if points else 8))
        p.setPen(QPen(QColor(PALETTE.text_dim), 1.4))
        p.setBrush(QColor(PALETTE.accent_dim))
        for marker in markers[:8]:
            pt = transform.point(marker)
            angle = math.radians(marker["bearing"])
            a = QPointF(pt.x() + math.sin(angle) * 8, pt.y() - math.cos(angle) * 8)
            b = QPointF(pt.x() - math.sin(angle + 0.7) * 5, pt.y() + math.cos(angle + 0.7) * 5)
            c = QPointF(pt.x() - math.sin(angle - 0.7) * 5, pt.y() + math.cos(angle - 0.7) * 5)
            path = QPainterPath()
            path.moveTo(a)
            path.lineTo(b)
            path.lineTo(c)
            path.closeSubpath()
            p.drawPath(path)

    def _paint_segments(self, p: QPainter, transform, points: list[dict]) -> None:
        if not points:
            return
        p.setFont(QFont(TYPE.mono.split(",")[0], TYPE.nano))
        for segment in self._segments[:6]:
            start = getattr(segment, "start_distance_meters", None)
            if start is None:
                continue
            nearest = min(points, key=lambda row: abs(float(row.get("distance_from_start_meters") or 0.0) - float(start)))
            pt = transform.point(nearest)
            p.setPen(QPen(QColor(PALETTE.violet), 1))
            p.drawLine(pt.x(), pt.y() - 12, pt.x(), pt.y() + 12)
            p.drawText(pt.x() + 4, pt.y() - 9, getattr(segment, "name", "SEG")[:12].upper())

    def _paint_legend(self, p: QPainter) -> None:
        p.setFont(QFont(TYPE.mono.split(",")[0], TYPE.nano))
        p.setPen(QColor(PALETTE.text_faint))
        p.drawText(12, self.height() - 12, "WHEEL ZOOM · DRAG PAN · DOUBLE-CLICK RESET")


class _Transform:
    def __init__(self, points: list[dict], width: int, height: int, zoom: float, pan: QPointF):
        bounds = routes.calculate_bounds(points) or {"min_lat": 0, "max_lat": 1, "min_lng": 0, "max_lng": 1}
        self.min_lat = bounds["min_lat"]
        self.max_lat = bounds["max_lat"]
        self.min_lng = bounds["min_lng"]
        self.max_lng = bounds["max_lng"]
        self.width = max(1, width)
        self.height = max(1, height)
        self.zoom = zoom
        self.pan = pan
        self.pad = 28
        self.lat_span = max(self.max_lat - self.min_lat, 0.00001)
        self.lng_span = max(self.max_lng - self.min_lng, 0.00001)

    def point(self, row: dict) -> QPointF:
        x_norm = (float(row["lng"]) - self.min_lng) / self.lng_span
        y_norm = 1.0 - ((float(row["lat"]) - self.min_lat) / self.lat_span)
        usable_w = max(1.0, self.width - self.pad * 2)
        usable_h = max(1.0, self.height - self.pad * 2)
        x = self.pad + x_norm * usable_w
        y = self.pad + y_norm * usable_h
        cx = self.width / 2
        cy = self.height / 2
        return QPointF(cx + (x - cx) * self.zoom + self.pan.x(), cy + (y - cy) * self.zoom + self.pan.y())

