"""Drag-and-drop training calendar widgets.

  SessionTile    — a draggable palette tile (carries a session type)
  SessionChip    — a placed session on a day; draggable (to move) + click to delete
  DayCell        — a calendar day that accepts drops (new sessions or moves)
  MonthCalendar  — the month grid of DayCells with weekday headers + month nav

MIME formats:
  application/x-orion-session-type  -> a new session from the palette
  application/x-orion-session-id    -> an existing session being moved

The calendar persists every change immediately via fitness_service and re-emits
``changed`` so the page can refresh inferred metrics if needed.
"""

from __future__ import annotations

import calendar as _cal
from datetime import date

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.domains.fitness import fitness_service as fs
from app.ui.themes.theme import PALETTE, TYPE

MIME_TYPE = "application/x-orion-session-type"
MIME_ID = "application/x-orion-session-id"


class SessionTile(QFrame):
    """A draggable palette tile representing a session type."""

    def __init__(self, session_type: str, color: str, parent=None):
        super().__init__(parent)
        self._type = session_type
        self._color = color
        self.setFixedHeight(34)
        self.setCursor(Qt.OpenHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)
        swatch = QLabel("●")
        swatch.setStyleSheet(f"color:{color}; font-size:10px;")
        name = QLabel(session_type)
        name.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.small}px; font-weight:600;")
        lay.addWidget(swatch)
        lay.addWidget(name)
        lay.addStretch(1)
        grip = QLabel("⠿")
        grip.setStyleSheet(f"color:{PALETTE.text_faint}; font-size:12px;")
        lay.addWidget(grip)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(PALETTE.bg_panel_alt))
        p.setPen(QPen(QColor(PALETTE.border), 1.0))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.fillRect(0, 0, 3, self.height(), QColor(self._color))
        p.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, self._type.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.CopyAction)


class SessionChip(QFrame):
    """A placed session on a day cell — draggable to move, click to remove."""

    removed = Signal()
    moved = Signal()

    def __init__(self, item: fs.SessionItem, parent=None):
        super().__init__(parent)
        self._item = item
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedHeight(18)
        self.setToolTip(f"{item.session_type} — click to remove, drag to move")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 0, 4, 0)
        lay.setSpacing(4)
        name = QLabel(item.session_type)
        name.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.nano}px; font-weight:700;")
        lay.addWidget(name)
        lay.addStretch(1)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor(self._item.color)
        bg.setAlpha(48)
        p.fillRect(self.rect(), bg)
        p.fillRect(0, 0, 3, self.height(), QColor(self._item.color))
        p.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.RightButton:
            fs.delete_session(self._item.id)
            self.removed.emit()
            return
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position()

    def mouseMoveEvent(self, event):  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_ID, str(self._item.id).encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event):  # noqa: N802
        # A plain left click (no drag) removes the chip.
        if event.button() == Qt.LeftButton:
            fs.delete_session(self._item.id)
            self.removed.emit()


class DayCell(QFrame):
    """A calendar day that accepts dropped sessions."""

    changed = Signal()

    def __init__(self, user_id: int, day: date | None, in_month: bool, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._day = day
        self._in_month = in_month
        self.setAcceptDrops(day is not None)
        # Fixed, uniform cell height so a week with one session doesn't stretch
        # the whole row. Holds the day number plus ~3 session chips.
        self.setFixedHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(4, 3, 4, 4)
        self._lay.setSpacing(2)

        if day is not None:
            num = QLabel(str(day.day))
            today = day == date.today()
            num.setStyleSheet(
                f"color:{PALETTE.accent if today else PALETTE.text_dim};"
                f" font-size:{TYPE.nano}px; font-weight:{'700' if today else '400'};"
            )
            self._lay.addWidget(num)
        self._lay.addStretch(1)

    def set_sessions(self, items: list[fs.SessionItem]) -> None:
        # Clear existing chips (keep the day-number label at index 0).
        while self._lay.count() > 1:
            it = self._lay.takeAt(1)
            if it.widget():
                it.widget().deleteLater()
        self._lay.takeAt(self._lay.count() - 1)  # drop the stretch; re-add after
        for item in items:
            chip = SessionChip(item)
            chip.removed.connect(self.changed.emit)
            self._lay.addWidget(chip)
        self._lay.addStretch(1)

    # --- drop handling ---------------------------------------------------- #
    def dragEnterEvent(self, event):  # noqa: N802
        md = event.mimeData()
        if md.hasFormat(MIME_TYPE) or md.hasFormat(MIME_ID):
            event.acceptProposedAction()
            self._hover = True
            self.update()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def dropEvent(self, event):  # noqa: N802
        self._hover = False
        if self._day is None:
            return
        md = event.mimeData()
        if md.hasFormat(MIME_TYPE):
            stype = bytes(md.data(MIME_TYPE)).decode("utf-8")
            fs.add_session(self._user_id, self._day, stype)
            event.acceptProposedAction()
            self.changed.emit()
        elif md.hasFormat(MIME_ID):
            sid = int(bytes(md.data(MIME_ID)).decode("utf-8"))
            fs.move_session(sid, self._day)
            event.acceptProposedAction()
            self.changed.emit()

    _hover = False

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        base = PALETTE.bg_panel if self._in_month else PALETTE.bg_deep
        p.fillRect(self.rect(), QColor(base))
        border = PALETTE.accent if self._hover else PALETTE.border_soft
        p.setPen(QPen(QColor(border), 1.0))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        if self._day == date.today():
            p.setPen(QPen(QColor(PALETTE.accent), 1.0))
            p.drawRect(1, 1, self.width() - 3, self.height() - 3)
        p.end()


class MonthCalendar(QWidget):
    """Month grid of DayCells with weekday headers and month navigation."""

    changed = Signal()

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        today = date.today()
        self._year, self._month = today.year, today.month

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(8)

        # Header: month label + nav.
        head = QHBoxLayout()
        self._title = QLabel("")
        self._title.setObjectName("PanelTitle")
        prev = QPushButton("‹")
        nxt = QPushButton("›")
        for b in (prev, nxt):
            b.setObjectName("GhostButton")
            b.setFixedWidth(34)
        prev.clicked.connect(self._prev_month)
        nxt.clicked.connect(self._next_month)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(prev)
        head.addWidget(nxt)
        self._root.addLayout(head)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        self._root.addWidget(self._grid_host)

        self._cells: dict[date, DayCell] = {}
        self.rebuild()

    def _prev_month(self):
        self._month -= 1
        if self._month < 1:
            self._month, self._year = 12, self._year - 1
        self.rebuild()

    def _next_month(self):
        self._month += 1
        if self._month > 12:
            self._month, self._year = 1, self._year + 1
        self.rebuild()

    def rebuild(self):
        # Clear grid.
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._cells.clear()

        self._title.setText(
            f"{_cal.month_name[self._month].upper()} {self._year}"
        )
        # Weekday headers (Mon-first).
        for c, name in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
            lbl = QLabel(name)
            lbl.setObjectName("Mono")
            lbl.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(lbl, 0, c)

        _cal.setfirstweekday(_cal.MONDAY)
        weeks = _cal.monthcalendar(self._year, self._month)
        sessions = fs.sessions_for_month(self._user_id, self._year, self._month)

        for r, week in enumerate(weeks, start=1):
            for c, dnum in enumerate(week):
                if dnum == 0:
                    cell = DayCell(self._user_id, None, in_month=False)
                else:
                    d = date(self._year, self._month, dnum)
                    cell = DayCell(self._user_id, d, in_month=True)
                    cell.set_sessions(sessions.get(d, []))
                    cell.changed.connect(self._on_changed)
                    self._cells[d] = cell
                self._grid.addWidget(cell, r, c)
            self._grid.setRowStretch(r, 0)  # rows stay at the cells' fixed height

        # Equal-width columns; no vertical stretch so the grid stays compact.
        for c in range(7):
            self._grid.setColumnStretch(c, 1)

    def _on_changed(self):
        self.rebuild()
        self.changed.emit()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(760, 520)
