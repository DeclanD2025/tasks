"""Star-field background with a subtly highlighted Orion constellation.

`ConstellationBackground` is a reusable painted widget:
  * a calm field of randomly placed faint stars
  * the Orion constellation rendered on top, slightly brighter, with thin
    connecting lines tracing the figure
  * a very gentle twinkle animation (low CPU; stars only modulate opacity)

It is used full-bleed behind the login screen and, dimmed, behind the app
shell. The look aims for cinematic and calm — not cartoonish.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import Property, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.ui.themes.theme import PALETTE

# Orion in normalised (x, y) coordinates, 0..1, y down. Hand-tuned to read as
# the classic figure: shoulders (Betelgeuse, Bellatrix), belt (Alnitak,
# Alnilam, Mintaka), feet (Saiph, Rigel), plus the bow/club.
ORION_STARS: dict[str, tuple[float, float, float]] = {
    # name: (x, y, magnitude 0..1 where 1 = brightest)
    "Betelgeuse": (0.36, 0.18, 1.0),
    "Bellatrix": (0.60, 0.20, 0.7),
    "Alnitak": (0.44, 0.47, 0.8),    # belt left
    "Alnilam": (0.50, 0.49, 0.85),   # belt centre
    "Mintaka": (0.56, 0.51, 0.75),   # belt right
    "Saiph": (0.42, 0.80, 0.7),
    "Rigel": (0.62, 0.82, 1.0),
    "Meissa": (0.48, 0.06, 0.45),    # head
    "Bow1": (0.74, 0.30, 0.35),
    "Bow2": (0.78, 0.50, 0.35),
}

# Lines tracing the figure (pairs of star names).
ORION_LINES: list[tuple[str, str]] = [
    ("Meissa", "Betelgeuse"),
    ("Meissa", "Bellatrix"),
    ("Betelgeuse", "Alnitak"),
    ("Bellatrix", "Mintaka"),
    ("Alnitak", "Alnilam"),
    ("Alnilam", "Mintaka"),
    ("Alnitak", "Saiph"),
    ("Mintaka", "Rigel"),
    ("Bellatrix", "Bow1"),
    ("Bow1", "Bow2"),
]


class _Star:
    __slots__ = ("x", "y", "radius", "base", "phase", "speed")

    def __init__(self, x: float, y: float, radius: float, base: float):
        self.x = x
        self.y = y
        self.radius = radius
        self.base = base
        self.phase = random.uniform(0, math.tau)
        self.speed = random.uniform(0.6, 1.8)


class ConstellationBackground(QWidget):
    def __init__(self, parent=None, *, density: int = 220, dim: float = 1.0,
                 orion_anchor: tuple[float, float] = (0.56, 0.5)):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._density = density
        self._dim = dim  # 1.0 = login brightness; <1 dims it behind the shell
        # Fractional (x, y) centre for the constellation, lets callers move
        # Orion clear of overlaid UI (e.g. left of the login card).
        self._anchor = orion_anchor
        self._field: list[_Star] = []
        self._t = 0.0
        self._warp = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(125)  # calm twinkle without burning the main thread

    def _tick(self) -> None:
        self._t += 0.05 * (1.0 + self._warp * 4.5)
        self.update()

    def _get_warp_factor(self) -> float:
        return self._warp

    def _set_warp_factor(self, value: float) -> None:
        self._warp = max(0.0, min(1.0, float(value)))
        self.update()

    warp_factor = Property(float, _get_warp_factor, _set_warp_factor)

    def resizeEvent(self, event):  # noqa: N802 (Qt naming)
        self._regenerate()
        super().resizeEvent(event)

    def _regenerate(self) -> None:
        rng = random.Random(7)  # fixed seed: stable field between repaints
        w, h = max(self.width(), 1), max(self.height(), 1)
        self._field = []
        for _ in range(self._density):
            x = rng.uniform(0, w)
            y = rng.uniform(0, h)
            r = rng.uniform(0.4, 1.4)
            base = rng.uniform(0.10, 0.55)
            self._field.append(_Star(x, y, r, base))

    # --- painting --------------------------------------------------------- #
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        # Deep radial vignette for depth.
        grad = QRadialGradient(w * 0.5, h * 0.42, max(w, h) * 0.75)
        grad.setColorAt(0.0, QColor("#0a1020"))
        grad.setColorAt(1.0, QColor(PALETTE.bg_void))
        p.fillRect(self.rect(), grad)

        if not self._field:
            self._regenerate()

        # Background field.
        star_col = QColor(PALETTE.star)
        cx, cy = w * 0.52, h * 0.46
        for s in self._field:
            tw = 0.5 + 0.5 * math.sin(self._t * s.speed + s.phase)
            alpha = int(255 * s.base * tw * self._dim)
            star_col.setAlpha(max(0, min(255, alpha)))
            p.setBrush(star_col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(s.x, s.y), s.radius, s.radius)
            if self._warp > 0.02:
                dx, dy = s.x - cx, s.y - cy
                length = math.hypot(dx, dy) or 1.0
                ux, uy = dx / length, dy / length
                streak = 10 + 42 * self._warp * (0.35 + s.base)
                sc = QColor(PALETTE.accent)
                sc.setAlpha(int(95 * self._warp * self._dim * (0.35 + s.base)))
                p.setPen(QPen(sc, max(0.8, 1.4 * self._warp)))
                p.drawLine(
                    QPointF(s.x - ux * streak * 0.25, s.y - uy * streak * 0.25),
                    QPointF(s.x + ux * streak, s.y + uy * streak),
                )

        self._paint_orion(p, w, h)
        p.end()

    def _orion_box(self, w: int, h: int):
        # Place Orion slightly right-of-centre, occupying a tall central region.
        box_w = min(w, h) * 0.46
        box_h = box_w * 1.5
        ox = w * self._anchor[0] - box_w * 0.5
        oy = h * self._anchor[1] - box_h * 0.5
        return ox, oy, box_w, box_h

    def _star_point(self, name: str, w: int, h: int) -> QPointF:
        ox, oy, bw, bh = self._orion_box(w, h)
        x, y, _ = ORION_STARS[name]
        return QPointF(ox + x * bw, oy + y * bh)

    def _paint_orion(self, p: QPainter, w: int, h: int) -> None:
        # Connecting lines — thin, faint accent blue.
        line_col = QColor(PALETTE.accent)
        line_col.setAlpha(int(70 * self._dim))
        pen = p.pen()
        pen.setColor(line_col)
        pen.setWidthF(1.0)
        p.setPen(pen)
        for a, b in ORION_LINES:
            p.drawLine(self._star_point(a, w, h), self._star_point(b, w, h))

        # Stars — brighter than the field, with a soft glow halo.
        for name, (_, _, mag) in ORION_STARS.items():
            pt = self._star_point(name, w, h)
            tw = 0.7 + 0.3 * math.sin(self._t * 1.2 + hash(name) % 7)
            core_r = (1.6 + mag * 2.8)
            glow_r = core_r * 4.5

            glow = QRadialGradient(pt, glow_r)
            gc = QColor(PALETTE.star)
            gc.setAlpha(int(70 * mag * self._dim * tw))
            glow.setColorAt(0.0, gc)
            transparent = QColor(PALETTE.star)
            transparent.setAlpha(0)
            glow.setColorAt(1.0, transparent)
            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(pt, glow_r, glow_r)

            core = QColor("#ffffff")
            core.setAlpha(int(255 * self._dim * tw))
            p.setBrush(core)
            p.drawEllipse(pt, core_r, core_r)
