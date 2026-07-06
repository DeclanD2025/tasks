"""MeterBar — a labelled 0–100 HUD bar used by Career and Diploma pages.

A thin painted bar with a label, a value readout, and a fill whose colour
reflects a band. Purely presentational; the value is supplied by the caller.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.themes.theme import PALETTE, TYPE


class MeterBar(QWidget):
    """A horizontal 0–100 meter with a label and value text."""

    def __init__(
        self,
        label: str,
        value: float,
        *,
        suffix: str = "",
        color: str | None = None,
        readout: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._label = label
        self._value = max(0.0, min(100.0, float(value)))
        self._suffix = suffix
        self._color = color or PALETTE.accent
        self._readout = readout
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: float, *, color: str | None = None) -> None:
        self._value = max(0.0, min(100.0, float(value)))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802
        w, h = self.width(), self.height()
        if w <= 2 or h <= 2:
            return  # nothing sensible to paint yet

        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)

            # Label (top-left) and readout (top-right). drawText with integer
            # alignment flags requires an INTEGER QRect (the QRectF overload
            # takes a QTextOption, not flags) — mixing them segfaults in PySide6.
            base = QFont(self.font())
            base.setPixelSize(TYPE.small)
            base.setLetterSpacing(QFont.PercentageSpacing, 104)
            p.setFont(base)
            p.setPen(QPen(QColor(PALETTE.text_dim)))
            label_w = max(1, int(w * 0.7))
            p.drawText(QRect(0, 0, label_w, 15),
                       int(Qt.AlignLeft | Qt.AlignVCenter), self._label)

            readout = self._readout if self._readout is not None else (
                f"{self._value:.0f}{self._suffix}"
            )
            bold = QFont(self.font())
            bold.setPixelSize(TYPE.small)
            bold.setBold(True)
            p.setFont(bold)
            p.setPen(QPen(QColor(PALETTE.text)))
            half = max(1, int(w * 0.5))
            p.drawText(QRect(half, 0, w - half, 15),
                       int(Qt.AlignRight | Qt.AlignVCenter), readout)

            # Track + fill.
            track = QRectF(1, h - 11, w - 2, 7)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(PALETTE.grid))
            p.drawRoundedRect(track, 3, 3)
            fill_w = (w - 2) * (self._value / 100.0)
            if fill_w > 1:
                fill = QRectF(1, h - 11, fill_w, 7)
                col = QColor(self._color)
                p.setBrush(col)
                p.drawRoundedRect(fill, 3, 3)
                p.setPen(QPen(col.lighter(150), 1.5))
                p.drawLine(int(fill.right()), int(fill.top()),
                           int(fill.right()), int(fill.bottom()))
        finally:
            p.end()
