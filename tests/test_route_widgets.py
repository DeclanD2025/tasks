"""Regression tests for the RouteMap widget paint path.

A bad attribute reference inside ``paintEvent`` (e.g. ``PALETTE.bg`` instead of
``PALETTE.bg_void``) raises during paint, which is fatal to the whole Qt app.
These tests render the widget headlessly across the marker paths so such a crash
is caught in CI rather than in the user's running app.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.domains.fitness.route_widgets import RouteMap  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _render(widget) -> None:
    widget.resize(360, 240)
    img = QImage(360, 240, QImage.Format_ARGB32)
    painter = QPainter(img)
    widget.render(painter, QPoint(0, 0))
    painter.end()


_ROUTE = [
    {"lat": 51.500, "lon": -0.100},
    {"lat": 51.505, "lon": -0.095},
    {"lat": 51.510, "lon": -0.085},
    {"lat": 51.508, "lon": -0.080},
]


def test_route_map_paints_with_geometry(qapp):
    # Exercises path, start/finish, distance + direction markers — the full
    # marker stack that previously crashed on PALETTE.bg.
    m = RouteMap(
        route_geometry=_ROUTE,
        show_distance_markers=True,
        show_start_finish=True,
    )
    _render(m)  # must not raise


def test_route_map_paints_empty_state(qapp):
    m = RouteMap(route_geometry=[])
    _render(m)  # empty-state branch must not raise


def test_route_map_paint_is_crash_safe(qapp, monkeypatch):
    """Even if an inner paint helper raises, paintEvent must not propagate it
    (that would kill the app) — it degrades to the placeholder."""
    m = RouteMap(route_geometry=_ROUTE)

    def boom(self, p):
        raise RuntimeError("simulated paint failure")

    monkeypatch.setattr(RouteMap, "_paint", boom)
    _render(m)  # guard swallows it; no exception escapes
