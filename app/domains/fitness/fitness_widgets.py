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
from datetime import date, timedelta

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
        # Resolve built-in OR custom card definitions so custom tiles read right.
        self._def = fs.resolve_def(session_type, color)
        self.setFixedHeight(68)
        self.setCursor(Qt.OpenHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 7, 10, 7)
        lay.setSpacing(10)
        swatch = QLabel("●")
        swatch.setStyleSheet(f"color:{color}; font-size:11px;")
        lay.addWidget(swatch)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(self._def.title if self._def else session_type.title())
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.small}px; font-weight:700;")
        detail = QLabel(self._detail_text())
        detail.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;")
        detail.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(detail)
        lay.addLayout(text, 1)
        lay.addStretch(1)
        grip = QLabel("⠿")
        grip.setStyleSheet(f"color:{PALETTE.text_faint}; font-size:12px;")
        lay.addWidget(grip)

    def _detail_text(self) -> str:
        if not self._def:
            return "MOD · 45 min · R3"
        minutes = "rest" if self._def.duration_min <= 0 else f"{self._def.duration_min} min"
        cat = fs.CATEGORY_LABELS.get(self._def.category, "")
        prefix = f"{cat} · " if cat else ""
        return f"{prefix}{self._def.intensity} · {minutes} · R{self._def.recovery_cost}"

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor(PALETTE.bg_panel_alt)
        bg.setAlpha(205)
        p.fillRect(self.rect(), bg)
        p.setPen(QPen(QColor(PALETTE.border_soft), 1.0))
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
    """A placed session on a day cell — draggable to move, right-click to remove."""

    removed = Signal()
    moved = Signal()

    def __init__(self, item: fs.SessionItem, parent=None):
        super().__init__(parent)
        self._item = item
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedHeight(24)
        self.setToolTip(f"{item.title} — drag to move, right-click to remove")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 5, 0)
        lay.setSpacing(5)
        mark = QLabel("✓" if item.completed else "•")
        mark.setStyleSheet(
            f"color:{PALETTE.positive if item.completed else item.color};"
            f" font-size:{TYPE.nano}px; font-weight:700;"
        )
        name = QLabel(item.title)
        name.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.nano}px; font-weight:700;")
        meta = QLabel(item.definition.intensity)
        meta.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;")
        lay.addWidget(mark)
        lay.addWidget(name)
        lay.addStretch(1)
        lay.addWidget(meta)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor(self._item.color)
        bg.setAlpha(60 if self._item.completed else 48)
        p.fillRect(self.rect(), bg)
        p.fillRect(0, 0, 3, self.height(), QColor(self._item.color))
        if self._item.completed:
            p.setPen(QPen(QColor(PALETTE.positive), 1.0))
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)
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
        if event.button() == Qt.LeftButton:
            event.ignore()


class DayCell(QFrame):
    """A calendar day that accepts dropped sessions."""

    changed = Signal()
    selected = Signal(object)
    # Emitted when this cell's own contents changed in place (drop / move-in /
    # remove). The planner listens to refresh only the affected cells, so the
    # calendar grid never reshapes or jumps.
    touched = Signal(object)

    # How many session chips a cell shows before collapsing to a "+N" marker.
    # Caps the cell's content so its shape stays static regardless of load.
    MAX_VISIBLE_CHIPS = 3

    def __init__(
        self,
        user_id: int,
        day: date | None,
        in_month: bool,
        parent=None,
        *,
        selected: bool = False,
    ):
        super().__init__(parent)
        self._user_id = user_id
        self._day = day
        self._in_month = in_month
        self._selected = selected
        self._sessions: list[fs.SessionItem] = []
        self.setAcceptDrops(day is not None)
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(6, 5, 6, 6)
        self._lay.setSpacing(3)

        if day is not None:
            label = day.strftime("%a %d").upper()
            today = day == date.today()
            num = QLabel(label)
            num.setStyleSheet(
                f"color:{PALETTE.accent if today else PALETTE.text_dim};"
                f" font-size:{TYPE.nano}px; font-weight:{'700' if today else '400'};"
            )
            self._lay.addWidget(num)
        self._lay.addStretch(1)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def refresh(self) -> None:
        """Re-read this single day from the service and repaint in place.

        Used after a drop / move so only the touched cells update — the grid
        keeps its fixed shape and the page never has to rebuild.
        """
        if self._day is None:
            return
        items = fs.sessions_for_day(self._user_id, self._day)
        self.set_sessions(items)

    def set_sessions(self, items: list[fs.SessionItem]) -> None:
        self._sessions = items
        # Clear existing dynamic content (keep the day label at index 0).
        while self._lay.count() > 1:
            it = self._lay.takeAt(1)
            if it.widget():
                it.widget().deleteLater()
        # Cap visible chips so a busy day never grows the cell out of shape.
        visible = items[: self.MAX_VISIBLE_CHIPS]
        for item in visible:
            chip = SessionChip(item)
            chip.removed.connect(self._on_chip_removed)
            self._lay.addWidget(chip)
        overflow = len(items) - len(visible)
        if overflow > 0:
            more = QLabel(f"+{overflow} more")
            more.setAlignment(Qt.AlignCenter)
            more.setStyleSheet(
                f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;"
                " background:transparent;"
            )
            self._lay.addWidget(more)
        if not items and self._day is not None:
            empty = QLabel(self._empty_text())
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color:{PALETTE.text_faint}; font-size:{TYPE.nano}px;"
                " background:transparent;"
            )
            self._lay.addWidget(empty, 1)
        self._lay.addStretch(1)
        self.update()

    def _on_chip_removed(self) -> None:
        self.refresh()
        self.touched.emit(self._day)
        self.changed.emit()

    def _empty_text(self) -> str:
        if self._day == date.today():
            return "No session planned"
        if self._day and self._day.weekday() >= 5:
            return "Rest"
        return "Drop session"

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
            self.refresh()
            self.selected.emit(self._day)
            self.touched.emit(self._day)
            self.changed.emit()
        elif md.hasFormat(MIME_ID):
            sid = int(bytes(md.data(MIME_ID)).decode("utf-8"))
            session = fs.get_session(sid)
            source_day = session.day if session else None
            fs.move_session(sid, self._day)
            event.acceptProposedAction()
            self.refresh()
            # Refresh the day it left so its chip disappears without a rebuild.
            if source_day is not None and source_day != self._day:
                self.touched.emit(source_day)
            self.selected.emit(self._day)
            self.touched.emit(self._day)
            self.changed.emit()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._day is not None:
            self.selected.emit(self._day)
        super().mousePressEvent(event)

    _hover = False

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        base = PALETTE.bg_panel if self._in_month else PALETTE.bg_deep
        bg = QColor(base)
        bg.setAlpha(225 if self._selected else 190)
        p.fillRect(self.rect(), bg)
        if self._sessions and all(item.completed for item in self._sessions):
            border = PALETTE.positive
        elif self._selected or self._hover:
            border = PALETTE.accent
        else:
            border = PALETTE.border_soft
        p.setPen(QPen(QColor(border), 1.2 if self._selected else 1.0))
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
                    cell.touched.connect(self._on_cell_touched)
                    cell.changed.connect(self.changed.emit)
                    self._cells[d] = cell
                self._grid.addWidget(cell, r, c)
            self._grid.setRowStretch(r, 0)  # rows stay at the cells' fixed height

        # Equal-width columns; no vertical stretch so the grid stays compact.
        for c in range(7):
            self._grid.setColumnStretch(c, 1)

    def _on_cell_touched(self, day: date):
        """Refresh only the touched day in place; the grid never reshapes."""
        cell = self._cells.get(day)
        if cell is not None:
            cell.refresh()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(760, 520)


class TrainingBlockPlanner(QWidget):
    """A compact, actionable three-week planner centred on the current block."""

    changed = Signal()
    day_selected = Signal(object)

    def __init__(self, user_id: int, selected_day: date | None = None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._selected_day = selected_day or date.today()
        self._window_start = self._monday(date.today()) - timedelta(days=7)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(424)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self._title = QLabel("")
        self._title.setStyleSheet(
            f"color:{PALETTE.text}; font-size:{TYPE.h2}px; font-weight:700;"
        )
        self._range = QLabel("")
        self._range.setObjectName("Mono")
        prev = QPushButton("‹")
        today = QPushButton("Today")
        nxt = QPushButton("›")
        for button in (prev, today, nxt):
            button.setObjectName("GhostButton")
            button.setFixedHeight(28)
        prev.setFixedWidth(34)
        nxt.setFixedWidth(34)
        today.setFixedWidth(78)
        prev.clicked.connect(lambda: self._shift(-21))
        today.clicked.connect(self._go_today)
        nxt.clicked.connect(lambda: self._shift(21))
        head.addWidget(self._title)
        head.addWidget(self._range)
        head.addStretch(1)
        head.addWidget(prev)
        head.addWidget(today)
        head.addWidget(nxt)
        self._root.addLayout(head)

        self._grid_host = QWidget()
        self._grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._grid_host.setFixedHeight(374)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(5)
        self._grid.setVerticalSpacing(5)
        self._root.addWidget(self._grid_host, 0, Qt.AlignTop)

        self._cells: dict[date, DayCell] = {}
        self.rebuild()

    @staticmethod
    def _monday(day: date) -> date:
        return day - timedelta(days=day.weekday())

    def _shift(self, days: int) -> None:
        self._window_start += timedelta(days=days)
        self.rebuild()

    def _go_today(self) -> None:
        self._selected_day = date.today()
        self._window_start = self._monday(date.today()) - timedelta(days=7)
        self.rebuild()
        self.day_selected.emit(self._selected_day)

    def set_selected_day(self, day: date) -> None:
        self._selected_day = day
        for d, cell in self._cells.items():
            cell.set_selected(d == day)

    def rebuild(self) -> None:
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._cells.clear()

        end = self._window_start + timedelta(days=20)
        self._title.setText("3-WEEK BLOCK")
        self._range.setText(f"{self._window_start.strftime('%d %b').upper()} → "
                            f"{end.strftime('%d %b').upper()}")

        for col, name in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
            lbl = QLabel(name)
            lbl.setObjectName("Mono")
            lbl.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(lbl, 0, col)

        sessions = fs.sessions_for_range(self._user_id, self._window_start, end)
        for idx in range(21):
            day = self._window_start + timedelta(days=idx)
            row = idx // 7 + 1
            col = idx % 7
            cell = DayCell(
                self._user_id,
                day,
                in_month=True,
                selected=day == self._selected_day,
            )
            cell.set_sessions(sessions.get(day, []))
            cell.touched.connect(self._on_cell_touched)
            cell.changed.connect(self.changed.emit)
            cell.selected.connect(self._on_selected)
            self._cells[day] = cell
            self._grid.addWidget(cell, row, col)

        for col in range(7):
            self._grid.setColumnStretch(col, 1)
        for row in range(4):
            self._grid.setRowStretch(row, 0)

    def _on_selected(self, day: date) -> None:
        self.set_selected_day(day)
        self.day_selected.emit(day)

    def _on_cell_touched(self, day: date) -> None:
        """Refresh only the affected day in place; never reshape the grid."""
        self.refresh_day(day)

    def refresh_day(self, day: date) -> None:
        """Public hook: refresh a single day cell in place if it's visible."""
        cell = self._cells.get(day)
        if cell is not None:
            cell.refresh()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(820, 420)
