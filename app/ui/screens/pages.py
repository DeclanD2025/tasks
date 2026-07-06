"""Module pages.

Each navigation key maps to a page widget. The Overview page is built from real
seeded data via `app.services`; the other module pages show a polished
placeholder layout (metric strip + chart + panel) so the modular structure is
visible and each is ready to be filled in later.

Pages are decoupled from the ORM — they only call `app.services`.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import services
from app.domains.career import career_service as career
from app.domains.diploma import diploma_service as diploma
from app.domains.finance.finance_service import (
    CreditFacilityLine,
    FinanceDashboardSnapshot,
    FinanceProviderPlan,
    FinanceRiskSnapshot,
    LiabilityLine,
    StocksAndSharesIsaOverview,
    get_finance_dashboard_snapshot,
    store_provider_credentials,
)
from app.domains.fitness import fitness_service as fitness
from app.domains.fitness import route_service as routes
from app.domains.fitness.fitness_widgets import SessionTile, TrainingBlockPlanner
from app.domains.fitness.route_widgets import RouteMap
from app.domains.health.health_service import get_health_dashboard_snapshot
from app.domains.health.sickness_service import (
    SYMPTOM_CHECKLIST,
    get_sickness_snapshot,
    set_status,
    upsert_symptom_entry,
)
from app.domains.mental_health import mental_health_service as mental
from app.domains import personal_os
from app.domains.productivity.inbox_parser import ParsedTaskSuggestion, parse_inbox_text
from app.db.models import HealthStatus, SymptomSeverity
from app.domains.stoic.stoic_service import get_stoic_snapshot, upsert_today_entry
from app.domains.stoic.stoic_widgets import (
    ControlGauge,
    EudaimoniaGauge,
    LifeWeeksGrid,
    MaximPlate,
)
from app.ui.components.charts import ChartPanel
from app.ui.components.hud import Divider, HudPanel, MetricCell
from app.ui.components.meter import MeterBar
from app.ui.components.panels import (
    BiometricScanPanel,
    FinanceTerminalPanel,
    SystemHeader,
    VitalsStrip,
    ZoneDistribution,
)
from app.ui.components.viz import (
    DomainNode,
    InsightFeed,
    RadarDial,
    SignalLineChart,
)
from app.ui.components.widgets import GlassPanel, InsightCard, MetricCard
from app.services import Metric
from app.ui.navigation import NAV_ITEMS
from app.ui.themes.theme import PALETTE, TYPE


_NAV_BY_KEY = {item.key: item for item in NAV_ITEMS}


class _ScrollPage(QScrollArea):
    """A vertically scrolling page with a content column."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._assembly_effects: dict[QWidget, QGraphicsOpacityEffect] = {}
        self._assembly_anims: list[QParallelAnimationGroup] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.col = QVBoxLayout(container)
        self.col.setContentsMargins(24, 18, 24, 24)
        self.col.setSpacing(16)
        self.col.setAlignment(Qt.AlignTop)
        self.setWidget(container)

    def clear(self) -> None:
        self._assembly_effects.clear()
        self._assembly_anims.clear()
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _assembly_items(self) -> list[QWidget]:
        custom = getattr(self, "_assembly_widgets", None)
        if custom is not None:
            return [w for w in custom if w is not None]
        widgets: list[QWidget] = []
        for i in range(self.col.count()):
            widget = self.col.itemAt(i).widget()
            if widget is not None:
                widgets.append(widget)
        return widgets

    def prepare_assembly(self) -> None:
        for widget in self._assembly_items():
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            self._assembly_effects[widget] = effect

    def play_assembly(self, *, reduced: bool = False, base_delay: int = 0) -> None:
        if not self._assembly_effects:
            self.prepare_assembly()
        offset = QPoint(0, 0) if reduced else QPoint(0, 18)
        duration = 220 if reduced else 470
        step = 55 if reduced else 95
        for idx, widget in enumerate(self._assembly_items()):
            self._animate_item(
                widget,
                delay=base_delay + idx * step,
                offset=offset,
                duration=duration,
            )

    def _animate_item(
        self,
        widget: QWidget,
        *,
        delay: int,
        offset: QPoint,
        duration: int,
    ) -> None:
        effect = self._assembly_effects.get(widget)
        if effect is None:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            self._assembly_effects[widget] = effect
        final_pos = widget.pos()
        widget.move(final_pos + offset)

        def _start() -> None:
            group = QParallelAnimationGroup(self)
            fade = QPropertyAnimation(effect, b"opacity", group)
            fade.setDuration(duration)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(fade)
            if offset != QPoint(0, 0):
                slide = QPropertyAnimation(widget, b"pos", group)
                slide.setDuration(duration)
                slide.setStartValue(final_pos + offset)
                slide.setEndValue(final_pos)
                slide.setEasingCurve(QEasingCurve.Type.OutCubic)
                group.addAnimation(slide)
            group.finished.connect(lambda: self._assembly_anims.remove(group)
                                   if group in self._assembly_anims else None)
            self._assembly_anims.append(group)
            group.start()

        QTimer.singleShot(delay, _start)

    def add_metric_strip(self, metrics: list[Metric]) -> None:
        strip = QWidget()
        grid = QGridLayout(strip)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        cols = 4
        for i, m in enumerate(metrics):
            grid.addWidget(MetricCard(m), i // cols, i % cols)
        self.col.addWidget(strip)

    def add_placeholder_note(self, text: str) -> None:
        note = QLabel(text)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        self.col.addWidget(note)


def _nav_code(key: str) -> str:
    return _NAV_BY_KEY[key].code if key in _NAV_BY_KEY else key[:3].upper()


def _set_env_var(key: str, value: str) -> None:
    """Upsert ``KEY=value`` in the project .env (created if missing).

    Also updates the live process env so the change is visible without restart
    where settings re-read it. Used by Settings toggles that must persist.
    """
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[2] / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _last_value(frame, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _duration_label(minutes: float | None) -> str:
    if minutes is None:
        return "NO SIGNAL"
    total = max(0, int(round(minutes)))
    return f"{total // 60}h {total % 60:02d}"


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_percent(value: str, fallback: float = 62.0) -> float:
    digits = "".join(ch for ch in value if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else fallback
    except ValueError:
        return fallback


def _distance_label(meters: float | int | None) -> str:
    if meters is None:
        return "—"
    value = float(meters)
    if value >= 1000:
        return f"{value / 1000:.2f} km"
    return f"{value:.0f} m"


def _meters_label(meters: float | int | None) -> str:
    return "—" if meters is None else f"{float(meters):.0f} m"


def _signed_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    sign = "+" if seconds > 0 else "-" if seconds < 0 else "±"
    return f"{sign}{routes.format_duration(abs(seconds))}"


def _signed_pace(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    sign = "+" if seconds > 0 else "-" if seconds < 0 else "±"
    return f"{sign}{routes.format_pace(abs(seconds))}"


def _signed_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else "-" if value < 0 else "±"
    return f"{sign}{abs(float(value)):.0f}{suffix}"


def _metric_panel(title: str, code: str, metrics: list[Metric], *, limit: int = 6) -> HudPanel:
    panel = HudPanel(title, code)
    if not metrics:
        panel.body.addWidget(QLabel("NO SIGNALS"))
        return panel
    for i, metric in enumerate(metrics[:limit]):
        panel.body.addWidget(MetricCell(metric, f"{code}-{i + 1:02d}"))
    return panel


def _signal_panel(
    title: str,
    code: str,
    series: list[float],
    *,
    unit: str = "",
    color: str | None = None,
    height: int = 150,
) -> HudPanel:
    panel = HudPanel(title, code)
    panel.body.addWidget(
        SignalLineChart(series, color=color or PALETTE.accent, unit=unit, height=height)
    )
    return panel


def _feed_panel(title: str, code: str, insights: list[dict], *, status: str = "LIVE") -> HudPanel:
    panel = HudPanel(title, code, status=status)
    panel.body.addWidget(InsightFeed(insights))
    return panel


def _factor_row(factor) -> QWidget:
    """A single derivation line: input label · measured readout · real/unwired."""
    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(8)
    dot = QLabel("●")
    dot.setStyleSheet(
        f"color:{PALETTE.accent if factor.is_real else PALETTE.text_faint}; font-size:7px;"
    )
    label = QLabel(factor.label.upper())
    label.setObjectName("Mono")
    readout = QLabel(factor.readout)
    readout.setObjectName("Faint" if not factor.is_real else "Muted")
    readout.setStyleSheet(f"font-size:{TYPE.nano}px;")
    rl.addWidget(dot)
    rl.addWidget(label)
    rl.addStretch(1)
    rl.addWidget(readout)
    return row


# --------------------------------------------------------------------------- #
# Mental health / Calendar / Tasks rows
# --------------------------------------------------------------------------- #
_PRIORITY_COLOR = {
    "low": PALETTE.text_faint,
    "medium": PALETTE.accent,
    "high": PALETTE.critical,
}


class _MentalHealthWorkbench(HudPanel):
    """Local ACT/thinking-trap reflection tool."""

    def __init__(self, parent=None):
        super().__init__("Thought Trap Scanner", "MHL-SCN", parent=parent, status="LOCAL")

        note = QLabel(
            "This is a reflection aid, not diagnosis. It helps name possible thinking "
            "patterns, loosen fusion with thoughts, and choose a values-based next step."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.body.addWidget(note)

        self._input = QTextEdit()
        self._input.setMinimumHeight(130)
        self._input.setPlaceholderText(
            "Write the thought or situation as your mind is presenting it. "
            "Example: This will be a disaster and everyone will think I failed."
        )
        self.body.addWidget(self._input)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        scan = QPushButton("Scan thinking traps")
        scan.setObjectName("PrimaryButton")
        scan.clicked.connect(self._scan)
        reset = QPushButton("Clear")
        reset.setObjectName("GhostButton")
        reset.clicked.connect(self._clear)
        actions.addWidget(scan)
        actions.addWidget(reset)
        actions.addStretch(1)
        self.body.addLayout(actions)

        self._results_host = QWidget()
        self._results = QVBoxLayout(self._results_host)
        self._results.setContentsMargins(0, 0, 0, 0)
        self._results.setSpacing(8)
        self.body.addWidget(self._results_host)
        self._render_result(mental.build_reflection(""))

    def _clear(self) -> None:
        self._input.clear()
        self._render_result(mental.build_reflection(""))

    def _scan(self) -> None:
        self._render_result(mental.build_reflection(self._input.toPlainText()))

    def _render_result(self, result: mental.ReflectionResult) -> None:
        while self._results.count():
            item = self._results.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if result.trap_hits:
            self._results.addWidget(_mini_heading("Possible thinking traps"))
            for hit in result.trap_hits:
                self._results.addWidget(
                    _MentalHealthResultBlock(
                        hit.label,
                        f"{hit.description}\nReframe: {hit.reframe_prompt}\nACT move: {hit.act_move}",
                    )
                )
        else:
            self._results.addWidget(
                _MentalHealthResultBlock(
                    "No strong trap pattern detected",
                    "Use this as a clean check-in: name what is happening, make room for the feeling, "
                    "then choose a values-based action.",
                )
            )

        self._results.addWidget(_mini_heading("ACT prompts"))
        for prompt in result.act_prompts:
            self._results.addWidget(_MentalHealthResultBlock(prompt.label, prompt.prompt))

        method = result.regulation
        self._results.addWidget(_mini_heading("Regulation protocol"))
        steps = "\n".join(f"{idx}. {step}" for idx, step in enumerate(method.steps, start=1))
        self._results.addWidget(
            _MentalHealthResultBlock(
                method.label,
                f"When: {method.when_to_use}\n{steps}\nWhy: {method.mechanism}",
            )
        )

        self._results.addWidget(
            _MentalHealthResultBlock("Next action", result.next_action_prompt)
        )
        safety = QLabel(result.safety_note)
        safety.setObjectName("Faint")
        safety.setWordWrap(True)
        self._results.addWidget(safety)


class _MentalHealthResultBlock(QFrame):
    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("MentalHealthResultBlock")
        self.setStyleSheet(
            f"""
            QFrame#MentalHealthResultBlock {{
                background-color: {PALETTE.bg_panel_alt};
                border: 1px solid {PALETTE.border_soft};
                border-radius: 4px;
            }}
            """
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 9)
        lay.setSpacing(5)
        heading = QLabel(title.upper())
        heading.setObjectName("PanelTitle")
        heading.setWordWrap(True)
        text = QLabel(body)
        text.setObjectName("Muted")
        text.setWordWrap(True)
        lay.addWidget(heading)
        lay.addWidget(text)


def _mini_heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("ModuleCode")
    return label


class _CalendarEventRow(QWidget):
    """A single calendar event: time · title · calendar."""

    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(12)

        starts = ev["starts_at"]
        ends = ev.get("ends_at")
        if ev.get("all_day"):
            when = "All day"
        elif ends is not None:
            when = f"{starts.strftime('%H:%M')}–{ends.strftime('%H:%M')}"
        else:
            when = starts.strftime("%H:%M")
        time_label = QLabel(when)
        time_label.setObjectName("Mono")
        time_label.setFixedWidth(104)
        lay.addWidget(time_label, 0, Qt.AlignVCenter)

        title = QLabel(ev["title"])
        title.setStyleSheet(
            f"color:{PALETTE.text}; font-size:{TYPE.body}px; font-weight:500;"
        )
        lay.addWidget(title, 0, Qt.AlignVCenter)
        lay.addStretch(1)

        cal = ev.get("calendar_name")
        if cal:
            chip = QLabel(cal)
            chip.setObjectName("Pill")
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
            lay.addWidget(chip, 0, Qt.AlignVCenter)


class _TaskRow(QWidget):
    """A task with a completion checkbox, priority dot, title and area.

    Toggling the checkbox marks the task locally and queues it for push back to
    Supabase on the next sync; ``on_change`` re-renders the page.
    """

    def __init__(self, task: dict, on_change, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._task = task
        self._on_change = on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(10)

        self._check = QCheckBox()
        self._check.setChecked(task["status"] == "done")
        self._check.toggled.connect(self._toggle)
        lay.addWidget(self._check)

        dot = QLabel("●")
        dot.setStyleSheet(
            f"color:{_PRIORITY_COLOR.get(task['priority'], PALETTE.accent)};"
            " font-size:8px;"
        )
        lay.addWidget(dot)

        title = QLabel(task["title"])
        if task["status"] == "done":
            title.setStyleSheet(
                f"color:{PALETTE.text_faint}; font-size:{TYPE.body}px;"
                " text-decoration: line-through;"
            )
        else:
            title.setStyleSheet(
                f"color:{PALETTE.text}; font-size:{TYPE.body}px; font-weight:500;"
            )
        title.setWordWrap(True)
        lay.addWidget(title, 1)

        due = task.get("due_date")
        if due is not None:
            due_label = QLabel(due.strftime("%d %b"))
            due_label.setObjectName("Mono")
            lay.addWidget(due_label)

        if task.get("dirty"):
            pending = QLabel("⟳")
            pending.setStyleSheet(f"color:{PALETTE.text_faint}; font-size:11px;")
            pending.setToolTip("Edited locally — will sync on next run")
            lay.addWidget(pending)

    def _toggle(self, checked: bool) -> None:
        services.set_task_done(self._task["id"], checked)
        if callable(self._on_change):
            self._on_change()


class _TaskComposer(QWidget):
    """A clean quick-add row: a text field + Add button that creates a task.

    Created locally and pushed to Supabase on the next sync (the new row is
    marked dirty by ``services.add_task``).
    """

    def __init__(self, user_id, on_change, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._on_change = on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Add a task…")
        self._input.returnPressed.connect(self._add)
        lay.addWidget(self._input, 1)

        add = QPushButton("Add")
        add.setObjectName("PrimaryButton")
        add.clicked.connect(self._add)
        lay.addWidget(add)

    def _add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        services.add_task(self._user_id, title)
        self._input.clear()
        if callable(self._on_change):
            self._on_change()


_INBOX_AREAS = [
    "Steelmen Dispatch",
    "Health & Fitness",
    "Finance",
    "DPLP/University",
    "Legal Career",
    "Coding Projects",
    "Creative Writing",
    "Misc Review",
]


class _CommandInboxSuggestionCard(QFrame):
    """Editable review card for one locally parsed task suggestion."""

    def __init__(self, suggestion: ParsedTaskSuggestion, on_remove, parent=None):
        super().__init__(parent)
        self._suggestion = suggestion
        self._on_remove = on_remove
        self.setObjectName("CommandInboxSuggestion")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setStyleSheet(
            f"""
            QFrame#CommandInboxSuggestion {{
                background-color: {PALETTE.bg_panel_alt};
                border: 1px solid {PALETTE.border_soft};
                border-radius: 4px;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.selected = QCheckBox()
        self.selected.setChecked(True)
        top.addWidget(self.selected, 0, Qt.AlignTop)

        self.title = QLineEdit(suggestion.title)
        self.title.setPlaceholderText("Task title")
        top.addWidget(self.title, 1)

        remove = QToolButton()
        remove.setText("Remove")
        remove.setToolTip("Remove this suggestion")
        remove.clicked.connect(self._remove)
        top.addWidget(remove)
        root.addLayout(top)

        grid = QGridLayout()
        grid.setContentsMargins(24, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)

        self.area = QComboBox()
        self.area.setEditable(True)
        areas = list(_INBOX_AREAS)
        if suggestion.area not in areas:
            areas.append(suggestion.area)
        self.area.addItems(areas)
        self.area.setCurrentText(suggestion.area)

        self.priority = QComboBox()
        self.priority.addItems(["low", "medium", "high"])
        self.priority.setCurrentText(suggestion.priority)

        self.due_date = QLineEdit(suggestion.due_date.isoformat() if suggestion.due_date else "")
        self.due_date.setPlaceholderText("YYYY-MM-DD")

        self.project = QLineEdit(suggestion.project)
        self.project.setPlaceholderText("Project")

        self.today = QCheckBox("Today")
        self.today.setChecked(suggestion.today)
        self.today.toggled.connect(self._sync_today_date)

        self.this_week = QCheckBox("This week")
        self.this_week.setChecked(suggestion.this_week)

        self._add_field(grid, 0, "Area", self.area)
        self._add_field(grid, 1, "Priority", self.priority)
        self._add_field(grid, 2, "Due", self.due_date)
        self._add_field(grid, 3, "Project", self.project)
        grid.addWidget(self.today, 4, 1)
        grid.addWidget(self.this_week, 4, 3)
        root.addLayout(grid)

        self.notes = QTextEdit(suggestion.notes)
        self.notes.setPlaceholderText("Notes")
        self.notes.setFixedHeight(74)
        root.addWidget(self.notes)

        reason = QLabel(f"{int(suggestion.confidence * 100)}% · {suggestion.reason}")
        reason.setObjectName("Faint")
        reason.setWordWrap(True)
        root.addWidget(reason)

    def _add_field(self, grid: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        caption = QLabel(label.upper())
        caption.setObjectName("Mono")
        caption.setStyleSheet(f"font-size:{TYPE.nano}px; color:{PALETTE.text_faint};")
        grid.addWidget(caption, row, 0)
        grid.addWidget(widget, row, 1, 1, 3)

    def _sync_today_date(self, checked: bool) -> None:
        if checked:
            self.due_date.setText(date.today().isoformat())

    def _remove(self) -> None:
        if callable(self._on_remove):
            self._on_remove(self)

    def payload(self) -> dict:
        due_text = self.due_date.text().strip()
        due = None
        if due_text:
            try:
                due = date.fromisoformat(due_text)
            except ValueError as exc:
                raise ValueError(f"Use YYYY-MM-DD for '{self.title.text().strip()}'.") from exc
        return {
            "selected": self.selected.isChecked(),
            "title": self.title.text().strip(),
            "area": self.area.currentText().strip(),
            "category": self._suggestion.category,
            "priority": self.priority.currentText().strip() or "medium",
            "due_date": due,
            "notes": self.notes.toPlainText().strip(),
            "project": self.project.text().strip(),
            "today": self.today.isChecked(),
            "this_week": self.this_week.isChecked(),
        }


class _CommandInbox(HudPanel):
    """Local brain-dump parser with review-before-save task creation."""

    def __init__(self, user_id: int, on_created, *, success_message: str = "", parent=None):
        super().__init__("Command Inbox", "TSK-INB", parent=parent, status="LOCAL RULES")
        self._user_id = user_id
        self._on_created = on_created
        self._cards: list[_CommandInboxSuggestionCard] = []

        self._input = QTextEdit()
        self._input.setMinimumHeight(126)
        self._input.setPlaceholderText(
            "Example: need to send Marc the HB brief tomorrow; also finish the "
            "BAE interview prep today, and maybe explore WordPress widget ideas this week"
        )
        self.body.addWidget(self._input)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        parse = QPushButton("Parse into tasks")
        parse.setObjectName("PrimaryButton")
        parse.clicked.connect(self._parse)
        self._create = QPushButton("Create selected tasks")
        self._create.setObjectName("GhostButton")
        self._create.setEnabled(False)
        self._create.clicked.connect(self._create_selected)
        actions.addWidget(parse)
        actions.addWidget(self._create)
        actions.addStretch(1)
        self.body.addLayout(actions)

        self._status = QLabel(success_message)
        self._status.setObjectName("Muted" if success_message else "Faint")
        self._status.setWordWrap(True)
        self.body.addWidget(self._status)

        self._suggestions_host = QWidget()
        self._suggestions = QVBoxLayout(self._suggestions_host)
        self._suggestions.setContentsMargins(0, 0, 0, 0)
        self._suggestions.setSpacing(8)
        self.body.addWidget(self._suggestions_host)
        self._show_empty_state()

    def _show_empty_state(self) -> None:
        self._clear_suggestions()
        empty = QLabel(
            "Paste a messy brain dump above, parse it locally, then review each "
            "suggestion before anything is saved."
        )
        empty.setObjectName("Faint")
        empty.setWordWrap(True)
        self._suggestions.addWidget(empty)
        self._create.setEnabled(False)

    def _clear_suggestions(self) -> None:
        self._cards.clear()
        while self._suggestions.count():
            item = self._suggestions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _parse(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            self._status.setText("Add a brain dump first.")
            self._status.setObjectName("Faint")
            self._show_empty_state()
            return

        suggestions = parse_inbox_text(text)
        self._clear_suggestions()
        if not suggestions:
            self._status.setText("No task-like suggestions found. Try one task per clause or line.")
            self._status.setObjectName("Faint")
            self._show_empty_state()
            return

        self._status.setText(
            f"Parsed {len(suggestions)} suggestion{'s' if len(suggestions) != 1 else ''}. "
            "Review before saving."
        )
        self._status.setObjectName("Muted")
        for suggestion in suggestions:
            card = _CommandInboxSuggestionCard(suggestion, self._remove_card)
            self._cards.append(card)
            self._suggestions.addWidget(card)
        self._create.setEnabled(True)

    def _remove_card(self, card: _CommandInboxSuggestionCard) -> None:
        if card in self._cards:
            self._cards.remove(card)
        self._suggestions.removeWidget(card)
        card.deleteLater()
        self._create.setEnabled(bool(self._cards))
        if not self._cards:
            self._show_empty_state()

    def _create_selected(self) -> None:
        payloads = []
        try:
            for card in self._cards:
                payload = card.payload()
                if payload["selected"]:
                    payloads.append(payload)
        except ValueError as exc:
            self._status.setText(str(exc))
            self._status.setObjectName("Faint")
            return

        if not payloads:
            self._status.setText("Select at least one suggestion to create.")
            self._status.setObjectName("Faint")
            return

        created = 0
        for payload in payloads:
            if not payload["title"]:
                continue
            due = date.today() if payload["today"] else payload["due_date"]
            services.add_task(
                self._user_id,
                payload["title"],
                area=payload["area"] or None,
                category=payload["category"],
                priority=payload["priority"],
                due_date=due,
                notes=self._compose_notes(payload),
            )
            created += 1

        if created == 0:
            self._status.setText("No titled suggestions were selected.")
            self._status.setObjectName("Faint")
            return

        self._input.clear()
        self._clear_suggestions()
        if callable(self._on_created):
            self._on_created(created)
        else:
            self._status.setText(f"Created {created} task{'s' if created != 1 else ''}.")
            self._show_empty_state()

    def _compose_notes(self, payload: dict) -> str | None:
        notes = payload["notes"].strip()
        metadata = []
        if payload["project"]:
            metadata.append(f"Project: {payload['project']}")
        if payload["today"]:
            metadata.append("Today: yes")
        if payload["this_week"]:
            metadata.append("This Week: yes")
        if metadata:
            notes = (notes + "\n\n" if notes else "") + "Command Inbox metadata:\n"
            notes += "\n".join(metadata)
        return notes or None


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
class OverviewPage(_ScrollPage):
    open_module = Signal(str)

    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.refresh()

    def refresh(self) -> None:
        self.clear()

        if self._user_id is None:
            self.add_placeholder_note("No data yet. Run the seeder: python -m app.db.seed")
            return

        today = personal_os.get_today_snapshot(self._user_id)
        self._assembly_widgets: list[QWidget] = []

        hero = self._command_centre_card(today)
        self.col.addWidget(hero)
        self._assembly_widgets.append(hero)

        grid = QWidget()
        layout = QGridLayout(grid)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(16)
        layout.setColumnStretch(0, 5)
        layout.setColumnStretch(1, 4)
        layout.addWidget(self._today_metrics_panel(today), 0, 0)
        layout.addWidget(self._todays_plan_panel(today), 0, 1)
        layout.addWidget(self._operating_insights_panel(today), 1, 0)
        layout.addWidget(self._quick_actions_panel(), 1, 1)
        self.col.addWidget(grid)
        self._assembly_widgets.append(grid)

    def _command_centre_card(self, today: personal_os.TodaySnapshot) -> HudPanel:
        accent = (
            PALETTE.positive if today.score and today.score >= 78
            else PALETTE.orange if today.score and today.score < 58
            else PALETTE.accent
        )
        panel = HudPanel("Daily Command Centre", "TDY-CMD", status=today.status, accent=accent)
        top = QWidget()
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(5)
        date_label = QLabel(datetime.now().strftime("%A %d %B").upper())
        date_label.setObjectName("Mono")
        score = QLabel(today.score_label)
        score.setStyleSheet(f"color:{accent}; font-size:42px; font-weight:800;")
        if today.estimated:
            score.setToolTip("Estimated from available local data; missing inputs are shown in Data.")
        status = QLabel(
            ("ESTIMATED READINESS" if today.estimated else "READINESS")
            + f"  ·  {today.freshness_label.upper()}"
        )
        status.setObjectName("Faint")
        status.setWordWrap(True)
        left.addWidget(date_label)
        left.addWidget(score)
        left.addWidget(status)
        row.addLayout(left, 0)

        middle = QVBoxLayout()
        middle.setSpacing(8)
        for label, text in [
            ("Training", today.training_recommendation),
            ("Mind", today.mental_nudge),
            ("Money", today.finance_nudge),
        ]:
            middle.addWidget(self._command_line(label, text))
        row.addLayout(middle, 1)

        action = QWidget()
        action.setObjectName("SuggestedAction")
        action.setStyleSheet(
            f"#SuggestedAction {{ background:{PALETTE.bg_panel_alt};"
            f" border:1px solid {PALETTE.border_soft}; border-radius:3px; }}"
        )
        action_lay = QVBoxLayout(action)
        action_lay.setContentsMargins(12, 10, 12, 11)
        action_lay.setSpacing(6)
        action_head = QLabel("SUGGESTED ACTION  ·  NEXT")
        action_head.setObjectName("ModuleCode")
        action_lay.addWidget(action_head)
        headline = QLabel(today.suggested_action)
        headline.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.h2}px; font-weight:750;")
        headline.setWordWrap(True)
        action_lay.addWidget(headline)
        action_note = QLabel("Generated from recovery, run plan, mind check-in and cashflow signals.")
        action_note.setObjectName("Faint")
        action_note.setWordWrap(True)
        action_lay.addWidget(action_note)
        row.addWidget(action, 1)
        panel.body.addWidget(top)
        return panel

    def _command_line(self, label: str, text: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        key = QLabel(label.upper())
        key.setObjectName("ModuleCode")
        key.setFixedWidth(74)
        body = QLabel(text)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        lay.addWidget(key)
        lay.addWidget(body, 1)
        return row

    def _today_metrics_panel(self, today: personal_os.TodaySnapshot) -> HudPanel:
        available = sum(1 for metric in today.metrics if metric.quality != "missing")
        panel = HudPanel("Daily Metrics", "TDY-MET", status=f"{available}/{len(today.metrics)} LIVE")
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for idx, metric in enumerate(today.metrics[:12]):
            grid.addWidget(self._today_metric_card(metric), idx // 3, idx % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        panel.body.addWidget(host)
        return panel

    def _today_metric_card(self, metric: personal_os.TodayMetric) -> QWidget:
        color = {
            "up": PALETTE.positive,
            "down": PALETTE.orange,
            "flat": PALETTE.accent_dim,
        }.get(metric.trend, PALETTE.accent_dim)
        if metric.quality == "missing":
            color = PALETTE.text_faint
        card = QWidget()
        card.setObjectName("TodayMetricCard")
        card.setStyleSheet(
            f"#TodayMetricCard {{ background:{PALETTE.bg_panel_alt};"
            f" border:1px solid {PALETTE.border_soft}; border-radius:3px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 9)
        lay.setSpacing(3)
        label = QLabel(metric.label.upper())
        label.setObjectName("CardLabel")
        value = QLabel(metric.value)
        value.setStyleSheet(f"color:{color}; font-size:{TYPE.h2}px; font-weight:750;")
        interpretation = QLabel(metric.interpretation.upper())
        interpretation.setObjectName("Faint")
        interpretation.setWordWrap(True)
        quality = QLabel(metric.quality.upper())
        quality.setObjectName("Mono")
        lay.addWidget(label)
        lay.addWidget(value)
        lay.addWidget(interpretation)
        lay.addWidget(quality)
        if len(metric.series) > 1:
            lay.addWidget(SignalLineChart(metric.series, color=color, height=34))
        return card

    def _todays_plan_panel(self, today: personal_os.TodaySnapshot) -> HudPanel:
        high = sum(1 for item in today.plan if item.priority == "high")
        panel = HudPanel("Today's Plan", "TDY-PLN", status=f"{high} PRIORITY" if high else "READY")
        for item in today.plan:
            panel.body.addWidget(self._plan_item(item))
        return panel

    def _plan_item(self, item: personal_os.DailyPlanItem) -> QWidget:
        color = PALETTE.orange if item.priority == "high" else PALETTE.accent
        row = QWidget()
        row.setObjectName("PlanItem")
        row.setStyleSheet(
            f"#PlanItem {{ background:{PALETTE.bg_panel_alt}; border:1px solid {PALETTE.border_soft};"
            " border-radius:3px; }}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        marker = QLabel("●")
        marker.setStyleSheet(f"color:{color}; font-size:8px;")
        lay.addWidget(marker)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(f"{item.area.upper()}  ·  {item.title}")
        title.setObjectName("PanelTitle")
        detail = QLabel(item.detail)
        detail.setObjectName("Faint")
        detail.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(detail)
        lay.addLayout(text, 1)
        if item.route_key:
            btn = QPushButton("Open")
            btn.setObjectName("GhostButton")
            btn.clicked.connect(lambda _=False, key=item.route_key: self.open_module.emit(key))
            lay.addWidget(btn)
        return row

    def _operating_insights_panel(self, today: personal_os.TodaySnapshot) -> HudPanel:
        panel = HudPanel("Insight Engine", "TDY-INS", status=f"{len(today.insights)} SIGNALS")
        if not today.insights:
            empty = QLabel("No high-signal observations yet. More imported data will sharpen this.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel
        for insight in today.insights[:6]:
            panel.body.addWidget(self._operating_insight_row(insight))
        return panel

    def _operating_insight_row(self, insight: personal_os.OperatingInsight) -> QWidget:
        color = {
            "positive": PALETTE.positive,
            "warning": PALETTE.orange,
            "critical": PALETTE.coral,
            "info": PALETTE.accent,
        }.get(insight.severity, PALETTE.accent)
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 3, 0, 8)
        lay.setSpacing(3)
        head = QHBoxLayout()
        sev = QLabel(insight.severity.upper())
        sev.setObjectName("ModuleCode")
        sev.setStyleSheet(f"color:{color};")
        area = QLabel(insight.area.upper())
        area.setObjectName("Mono")
        head.addWidget(sev)
        head.addWidget(area)
        head.addStretch(1)
        conf = QLabel(insight.confidence.upper())
        conf.setObjectName("Faint")
        head.addWidget(conf)
        lay.addLayout(head)
        title = QLabel(insight.title)
        title.setObjectName("PanelTitle")
        title.setWordWrap(True)
        body = QLabel(f"{insight.explanation} Action: {insight.action}")
        body.setObjectName("Muted")
        body.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(body)
        lay.addWidget(Divider())
        return row

    def _quick_actions_panel(self) -> HudPanel:
        panel = HudPanel("Quick Entry", "TDY-QCK", status="LOCAL")
        actions = [
            ("Start Workout", "fitness"),
            ("Plan Next Run", "run_plan"),
            ("Mind Check-in", "mental_health"),
            ("Review Money", "finance"),
            ("Inspect Data", "data"),
        ]
        for label, key in actions:
            btn = QPushButton(label)
            btn.setObjectName("GhostButton")
            btn.clicked.connect(lambda _=False, route=key: self.open_module.emit(route))
            panel.body.addWidget(btn)
        return panel

    # --- Overview pieces -------------------------------------------------- #
    def _today_banner(self, nodes, insights, health_snapshot) -> QWidget:
        """A calm at-a-glance summary row — plain language, your real numbers."""
        captured = sum(1 for item in health_snapshot.bio_systems if item.value > 0)
        total = len(health_snapshot.bio_systems)
        missing = total - captured

        # A task count if tasks have synced; otherwise omit.
        try:
            counts = services.task_counts(self._user_id)
            open_tasks = counts.get("open")
        except Exception:
            open_tasks = None

        alerts = sum(1 for i in insights if i["severity"] == "critical")
        mean_mom = sum(n.momentum for n in nodes) / (len(nodes) or 1)

        section = HudPanel("At a glance")
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        readouts = [
            ("Open tasks", str(open_tasks) if open_tasks is not None else "—",
             PALETTE.text if open_tasks else PALETTE.text_dim),
            ("Health signals", f"{captured}/{total}",
             PALETTE.orange if missing else PALETTE.positive),
            ("Momentum", f"{mean_mom * 100:.0f}%", PALETTE.text),
            ("Things to flag", str(alerts),
             PALETTE.orange if alerts else PALETTE.text_dim),
        ]
        for i, (lbl, val, col) in enumerate(readouts):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            k = QLabel(lbl)
            k.setObjectName("CardLabel")
            v = QLabel(val)
            v.setStyleSheet(
                f"color:{col}; font-size:26px; font-weight:700; letter-spacing:-0.02em;"
            )
            cell.addWidget(k)
            cell.addWidget(v)
            wrap = QWidget()
            wrap.setLayout(cell)
            grid.addWidget(wrap, 0, i)
            grid.setColumnStretch(i, 1)
        section.body.addWidget(row)
        return section

    def _summary_cards_row(self, health_snapshot, health_frame, activity_frame, nodes) -> QWidget:
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        sleep_minutes = _last_value(health_frame, "sleep_minutes")
        hrv = _last_value(health_frame, "hrv_ms")
        deep_work = _last_value(activity_frame, "deep_work_minutes")
        readiness = _parse_percent(health_snapshot.body_battery_value)
        readiness_label = "Ready" if readiness >= 75 else "Low" if readiness < 50 else "Recovering"
        sleep_debt = max(0.0, 480.0 - sleep_minutes) if sleep_minutes is not None else None
        focus_score = _clamp((deep_work or 0.0) / 180.0) * 100.0

        cards = [
            self._summary_card(
                "Recovery",
                "",
                f"{readiness:.0f}%",
                readiness_label,
                [
                    ("HRV", f"{hrv:.0f} ms" if hrv is not None else "—", PALETTE.text_dim),
                    ("Sleep quality", "Stable" if (sleep_minutes or 0) >= 420 else "Short",
                     PALETTE.positive if (sleep_minutes or 0) >= 420 else PALETTE.orange),
                ],
                PALETTE.positive if readiness >= 75 else PALETTE.orange,
                readiness,
            ),
            self._summary_card(
                "Sleep",
                "",
                _duration_label(sleep_minutes),
                "On track" if (sleep_minutes or 0) >= 420 else "Below target",
                [
                    ("Sleep debt", _duration_label(sleep_debt) if sleep_debt is not None else "—",
                     PALETTE.orange if (sleep_debt or 0) else PALETTE.positive),
                    ("Target", "8h 00", PALETTE.text_dim),
                ],
                PALETTE.accent,
                _clamp((sleep_minutes or 0.0) / 480.0) * 100.0,
            ),
            self._summary_card(
                "Focus",
                "",
                f"{focus_score:.0f}",
                "Good window" if focus_score >= 55 else "Scattered",
                [
                    ("Deep work", _duration_label(deep_work),
                     PALETTE.positive if focus_score >= 55 else PALETTE.orange),
                    ("Distractions", "Low" if focus_score >= 55 else "Watch", PALETTE.text_dim),
                ],
                PALETTE.violet,
                focus_score,
            ),
        ]

        cols = 3
        for idx, card in enumerate(cards):
            card.setMinimumHeight(158)
            grid.addWidget(card, idx // cols, idx % cols)
            self._assembly_widgets.append(card)
        for col_idx in range(cols):
            grid.setColumnStretch(col_idx, 1)
        return row

    def _summary_card(
        self,
        title: str,
        code: str,
        value: str,
        state: str,
        rows: list[tuple[str, str, str]],
        color: str,
        score: float,
    ) -> HudPanel:
        panel = HudPanel(title, code, status=state)
        value_label = QLabel(value)
        value_label.setStyleSheet(
            f"color:{color}; font-size:28px; font-weight:700; letter-spacing:-0.02em;"
        )
        panel.body.addWidget(value_label)
        panel.body.addWidget(MeterBar(state, score, color=color, readout=state))
        for label, row_value, row_color in rows:
            panel.body.addWidget(self._status_pair(label, row_value, row_color))
        return panel

    def _lower_dashboard(
        self,
        nodes: list[DomainNode],
        health_frame,
        activity_frame,
        recommendations: list[dict],
    ) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 3)

        actions = self._action_queue_panel()
        daily = self._daily_readout_panel(health_frame, activity_frame)
        alerts = self._alerts_panel(recommendations)

        grid.addWidget(actions, 0, 0)
        grid.addWidget(daily, 0, 1)
        grid.addWidget(alerts, 0, 2)

        self._assembly_widgets.extend([actions, daily, alerts])
        return host

    def _action_queue_panel(self) -> HudPanel:
        """Your real open tasks (synced), most pressing first — not mock filler."""
        try:
            tasks = services.get_tasks(self._user_id, include_done=False)
        except Exception:
            tasks = []

        # Sort: high priority first, then by due date (None last).
        from datetime import date as _date

        order = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (
            order.get(t.get("priority"), 1),
            t.get("due_date") or _date.max,
        ))

        panel = HudPanel("To do today", status=str(len(tasks)) if tasks else None)
        if not tasks:
            empty = QLabel("Nothing open. Sync your tasks app or add a task on the Tasks tab.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
        else:
            for t in tasks[:6]:
                panel.body.addWidget(_TaskRow(t, self.refresh))

        open_tasks = QPushButton("View all tasks")
        open_tasks.setObjectName("GhostButton")
        open_tasks.clicked.connect(lambda _=False: self.open_module.emit("tasks"))
        panel.body.addWidget(open_tasks)
        panel.body.addStretch(1)
        return panel

    def _daily_readout_panel(self, health_frame, activity_frame) -> HudPanel:
        panel = HudPanel("Today's numbers")
        sleep = _last_value(health_frame, "sleep_minutes")
        hrv = _last_value(health_frame, "hrv_ms")
        deep = _last_value(activity_frame, "deep_work_minutes")
        steps = _last_value(activity_frame, "steps")
        active = _last_value(activity_frame, "active_minutes")
        calories = active * 8.5 if active is not None else None
        rows = [
            ("Sleep", _duration_label(sleep), _clamp((sleep or 0) / 480) * 100,
             "Restored" if (sleep or 0) >= 420 else "Short", PALETTE.accent),
            ("HRV", f"{hrv:.0f} ms" if hrv is not None else "—",
             _clamp((hrv or 0) / 80) * 100, "Balanced" if (hrv or 0) >= 55 else "Low", PALETTE.violet),
            ("Deep work", _duration_label(deep), _clamp((deep or 0) / 180) * 100,
             "Clear" if (deep or 0) >= 120 else "Room to grow", PALETTE.positive),
            ("Steps", f"{steps:,.0f}" if steps is not None else "—",
             _clamp((steps or 0) / 10000) * 100, "Moving" if (steps or 0) >= 7000 else "Low", PALETTE.orange),
            ("Active calories", f"{calories:,.0f} kcal" if calories is not None else "—",
             _clamp((calories or 0) / 2200) * 100, "" , PALETTE.accent),
        ]
        for label, readout, score, status, color in rows:
            panel.body.addWidget(self._daily_metric(label, readout, score, status, color))
        panel.body.addStretch(1)
        return panel

    def _daily_metric(self, label: str, readout: str, score: float, status: str, color: str) -> QWidget:
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(MeterBar(label, score, color=color, readout=readout))
        if status:
            state = QLabel(status)
            state.setAlignment(Qt.AlignRight)
            state.setStyleSheet(f"color:{color}; font-size:{TYPE.small}px;")
            lay.addWidget(state)
        return row

    def _alerts_panel(self, recommendations: list[dict]) -> HudPanel:
        panel = HudPanel(
            "Worth a look", status=str(len(recommendations)) if recommendations else None
        )
        if not recommendations:
            empty = QLabel("Nothing needs attention right now.")
            empty.setObjectName("Faint")
            panel.body.addWidget(empty)
        for rec in recommendations[:3]:
            panel.body.addWidget(self._alert_item(rec))
        panel.body.addStretch(1)
        return panel

    def _alert_item(self, rec: dict) -> QWidget:
        color = {
            "positive": PALETTE.positive,
            "warning": PALETTE.orange,
            "critical": PALETTE.coral,
            "info": PALETTE.accent,
        }.get(rec["severity"], PALETTE.accent)
        item = QWidget()
        item.setObjectName("AlertItem")
        item.setStyleSheet(
            f"#AlertItem {{ background-color:{PALETTE.bg_panel_alt};"
            f" border:1px solid {PALETTE.border_soft}; border-radius:3px; }}"
        )
        lay = QVBoxLayout(item)
        lay.setContentsMargins(10, 8, 10, 9)
        lay.setSpacing(5)

        head = QHBoxLayout()
        sev = QLabel(rec["severity"].capitalize())
        sev.setStyleSheet(f"color:{color}; font-size:{TYPE.small}px; font-weight:600;")
        head.addWidget(sev)
        head.addStretch(1)
        lay.addLayout(head)

        title = QLabel(rec["title"])
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.body}px; font-weight:700;")
        title.setWordWrap(True)
        lay.addWidget(title)
        body = QLabel(rec["body"])
        body.setObjectName("Faint")
        body.setWordWrap(True)
        lay.addWidget(body)

        action = QPushButton(rec["action"])
        action.setObjectName("GhostButton")
        action.clicked.connect(lambda _=False, key=rec["module"]: self.open_module.emit(key))
        lay.addWidget(action, 0, Qt.AlignRight)
        return item

    def _recommendations(self, health_frame, activity_frame, insights: list[dict]) -> list[dict]:
        now = datetime.now().strftime("%H:%M")
        sleep = _last_value(health_frame, "sleep_minutes")
        hrv = _last_value(health_frame, "hrv_ms")
        deep = _last_value(activity_frame, "deep_work_minutes")
        debt = max(0.0, 480.0 - sleep) if sleep is not None else 0.0
        hrv_low = hrv is not None and hrv < 55

        recs: list[dict] = []
        recs.append({
            "severity": "warning" if hrv_low else "info",
            "title": "Elevated Stress Trend" if hrv_low else "Recovery Signal Stable",
            "body": "HRV has been trending low; keep today controlled and avoid stacking load."
            if hrv_low else "No critical recovery drift detected in the latest local signal.",
            "action": "View Insights",
            "module": "insights",
            "timestamp": now,
        })
        recs.append({
            "severity": "warning" if debt else "positive",
            "title": "Sleep Debt Building" if debt else "Sleep Target Stable",
            "body": f"You're {_duration_label(debt)} below your sleep target."
            if debt else "Last night's sleep is within the target corridor.",
            "action": "Optimise Sleep",
            "module": "health",
            "timestamp": now,
        })
        recs.append({
            "severity": "positive" if (deep or 0) < 120 else "info",
            "title": "Deep Work Opportunity",
            "body": "Your focus window is clear for the next 90 minutes."
            if (deep or 0) < 120 else "Deep work is already moving; protect the current cadence.",
            "action": "Start Session",
            "module": "productivity",
            "timestamp": now,
        })
        for insight in insights:
            if insight["severity"] == "critical":
                recs.insert(0, {
                    "severity": "critical",
                    "title": insight["title"],
                    "body": insight["body"] or "Critical deterministic insight requires review.",
                    "action": "Inspect",
                    "module": "insights",
                    "timestamp": insight["created_at"].strftime("%H:%M"),
                })
                break
        return recs[:3]

    def _status_pair(self, label: str, value: str, color: str) -> QWidget:
        row = QWidget()
        row.setFixedHeight(22)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        tick = QLabel("▸")
        tick.setStyleSheet(f"color:{color}; font-size:9px;")
        lay.addWidget(tick)
        name = QLabel(label)
        name.setObjectName("Mono")
        lay.addWidget(name)
        lay.addStretch(1)
        val = QLabel(value.upper())
        val.setStyleSheet(f"color:{color}; font-family:{TYPE.mono}; font-size:{TYPE.nano}px;")
        lay.addWidget(val)
        return row

    def _systems_readout(self, core_metrics, health_snapshot) -> HudPanel:
        """Compact operations readout with explicit data availability."""
        captured = sum(1 for item in health_snapshot.bio_systems if item.value > 0)
        total = len(health_snapshot.bio_systems)
        panel = HudPanel("Command Readout", "OVW-SYS", status=f"{captured}/{total} HEALTH")

        section = QLabel("PRIORITY")
        section.setObjectName("CardLabel")
        panel.body.addWidget(section)
        for m in core_metrics[:4]:
            panel.body.addWidget(self._readout_row(m.label, m.value, m.delta, m.trend))

        health_label = QLabel("HEALTH SIGNALS")
        health_label.setObjectName("CardLabel")
        panel.body.addWidget(health_label)
        cards = {card.label: card for card in health_snapshot.metric_cards}
        for label in ("Sleep", "HRV", "RHR", "Weight", "VO2 Max"):
            card = cards.get(label)
            if card is None:
                continue
            value = f"{card.value}{card.unit}" if card.unit else card.value
            state = card.secondary_value
            tone = "up" if state in ("REAL", "ASLEEP", "DERIVED") else "down"
            panel.body.addWidget(self._readout_row(label, value, state, tone))

        open_health = QPushButton("Open Health")
        open_health.setObjectName("GhostButton")
        open_health.clicked.connect(lambda _=False: self.open_module.emit("health"))
        panel.body.addWidget(open_health)
        panel.body.addStretch(1)
        return panel

    def _readout_row(self, label: str, value: str, meta: str = "", trend: str = "flat") -> QWidget:
        row = QWidget()
        row.setFixedHeight(28)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        color = {
            "up": PALETTE.positive,
            "down": PALETTE.orange,
            "flat": PALETTE.accent_dim,
        }.get(trend, PALETTE.accent_dim)
        tick = QLabel("▸")
        tick.setStyleSheet(f"color:{color}; font-size:9px;")
        name = QLabel(label.upper())
        name.setObjectName("Mono")
        val = QLabel(value)
        val.setStyleSheet(
            f"color:{PALETTE.text}; font-family:{TYPE.mono};"
            f" font-size:{TYPE.small}px; font-weight:700;"
        )
        rl.addWidget(tick)
        rl.addWidget(name)
        rl.addStretch(1)
        if meta:
            meta_label = QLabel(meta.upper())
            meta_label.setStyleSheet(
                f"color:{color}; font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            )
            rl.addWidget(meta_label)
        rl.addWidget(val)
        return row

    def _telemetry_strip(self) -> QWidget:
        panel = HudPanel("Telemetry", "OVW-TLM", status="STREAMING")
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        streams = [
            ("NET WORTH", services.net_worth_series(self._user_id).get("value"), PALETTE.accent, "£"),
        ]
        hf = services.health_frame(self._user_id)
        af = services.activity_frame(self._user_id)
        if not hf.empty:
            streams.append(("HRV", hf["hrv_ms"].dropna(), PALETTE.violet, ""))
            streams.append(("RHR", hf["resting_hr"].dropna(), PALETTE.orange, ""))
            streams.append(("WEIGHT", hf["weight_kg"].dropna(), PALETTE.positive, "kg"))
        if not af.empty:
            streams.append(("DEEP WORK", af["deep_work_minutes"].dropna(), PALETTE.positive, ""))
            streams.append(("TRAINING LOAD", af["training_load"].dropna(), PALETTE.orange, ""))
        for idx, (name, series, color, unit) in enumerate(streams):
            grid.addWidget(self._telemetry_cell(name, series, color, unit), idx // 3, idx % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        panel.body.addWidget(grid_host)
        return panel

    def _telemetry_cell(self, name: str, series, color: str, unit: str) -> QWidget:
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(5)
        head = QLabel(name)
        head.setObjectName("Mono")
        top.addWidget(head)
        top.addStretch(1)
        values = [] if series is None else [float(v) for v in list(series) if v is not None]
        if values:
            last = values[-1]
            suffix = unit if unit != "£" else ""
            latest = QLabel(f"£{last:,.0f}" if unit == "£" else f"{last:.1f}{suffix}")
            latest.setStyleSheet(
                f"color:{PALETTE.text}; font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            )
            top.addWidget(latest)
        col.addLayout(top)
        if len(values) >= 2:
            col.addWidget(SignalLineChart(values, color=color, unit=unit, height=88))
        else:
            empty = QLabel("NO DATA")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFixedHeight(88)
            empty.setStyleSheet(
                f"color:{PALETTE.text_faint}; border:1px solid {PALETTE.border_soft};"
                f" font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            )
            col.addWidget(empty)
        return cell

    def _system_balance(self) -> list[float]:
        """Normalised 0..1 scores for the radar (deterministic heuristics)."""
        uid = self._user_id
        try:
            af = services.activity_frame(uid)
            hf = services.health_frame(uid)
            pm = services.project_momentum(uid)
            finance = 0.7
            health = (
                min(1.0, (hf["sleep_minutes"].tail(7).mean() or 0) / 480) if not hf.empty else 0.5
            )
            focus = (
                min(1.0, (af["deep_work_minutes"].tail(7).mean() or 0) / 240)
                if not af.empty
                else 0.5
            )
            creative = 0.55
            projects = min(1.0, (pm["momentum"].mean() or 0) / 100) if not pm.empty else 0.5
            return [finance, health, focus, creative, projects]
        except Exception:
            return [0.6] * 5

    def _domain_nodes(self) -> list[DomainNode]:
        balance = self._system_balance()
        lookup = {
            "finance": balance[0],
            "health": balance[1],
            "productivity": balance[2],
            "creative": balance[3],
            "projects": balance[4],
            "calendar": 0.52,
            "learning": 0.48,
        }
        nodes: list[DomainNode] = []
        for item in NAV_ITEMS:
            if item.key in ("overview", "insights", "settings"):
                continue
            nodes.append(DomainNode(item.key, item.label, lookup.get(item.key, 0.5)))
        return nodes


# --------------------------------------------------------------------------- #
# Generic module page (placeholder layout, ready to flesh out)
# --------------------------------------------------------------------------- #
class ModulePage(_ScrollPage):
    # Emitted (possibly from a worker thread) when background data lands; the
    # queued connection hops the refresh back onto the GUI thread safely.
    _data_ready = Signal()

    def __init__(self, key: str, user_id: int | None, parent=None):
        super().__init__(parent)
        self._key = key
        self._user_id = user_id
        self._task_success_message = ""
        self._data_ready.connect(self.refresh)
        self._build()

    def refresh(self) -> None:
        self.clear()
        self._build()

    def _build(self) -> None:
        builder = getattr(self, f"_build_{self._key}", None)
        if builder and self._user_id is not None:
            try:
                builder()
                return
            except Exception:
                pass
        # Default placeholder for modules not yet wired to data.
        self.add_metric_strip(
            [
                Metric("Primary", "—"),
                Metric("Secondary", "—"),
                Metric("Tertiary", "—"),
            ]
        )
        panel = GlassPanel()
        title = QLabel(f"{self._key.title()} module")
        title.setObjectName("PanelTitle")
        body = QLabel(
            "Placeholder layout. This module is scaffolded and ready: wire its "
            "connector(s) in app/integrations and surface metrics via app/services."
        )
        body.setObjectName("Muted")
        body.setWordWrap(True)
        panel.body.addWidget(title)
        panel.body.addWidget(body)
        self.col.addWidget(panel)

    # ---- data-backed module pages ---------------------------------------- #
    def _build_mental_health(self) -> None:
        """Mental Health module — ACT, thinking traps and regulation tools."""
        mind = personal_os.get_mind_snapshot(self._user_id)
        self.col.addWidget(
            SystemHeader(
                "Mind Console",
                _nav_code("mental_health"),
                subtitle="Daily check-ins, protocols, mindfulness and local reflection tools.",
                sync_label="LOCAL ONLY",
                database_label="NO DIAGNOSIS",
            )
        )

        self.add_metric_strip(
            [
                Metric("Mood 7d", f"{mind.mood_average:.1f}/10" if mind.mood_average else "—"),
                Metric("Stress 7d", f"{mind.stress_average:.1f}/10" if mind.stress_average else "—"),
                Metric("Trend", mind.trend_label.title(), trend="flat"),
                Metric("Mindful Week", f"{mind.mindfulness_week_minutes + mind.imported_mindful_week_minutes} min"),
            ]
        )

        top = QWidget()
        grid = QGridLayout(top)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.addWidget(self._mind_checkin_panel(mind), 0, 0)
        grid.addWidget(self._mind_protocol_panel(mind), 0, 1)
        grid.addWidget(self._mindfulness_panel(mind), 1, 0, 1, 2)
        self.col.addWidget(top)

        self.col.addWidget(_MentalHealthWorkbench())

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.addWidget(self._act_process_panel(), 0, 0)
        grid.addWidget(self._regulation_library_panel(), 0, 1)
        self.col.addWidget(grid_host)

        safety = HudPanel("Use Notes", "MHL-SAFE", status="SELF-REFLECTION")
        copy = QLabel(
            "Use this module to notice patterns and choose actions. It does not assess risk, "
            "diagnose conditions, or replace care from a mental health professional. If you "
            "might hurt yourself or someone else, seek urgent local support now."
        )
        copy.setObjectName("Muted")
        copy.setWordWrap(True)
        safety.body.addWidget(copy)
        self.col.addWidget(safety)

    def _mind_checkin_panel(self, mind: personal_os.MindSnapshot) -> HudPanel:
        from PySide6.QtWidgets import QSpinBox

        panel = HudPanel("Daily Check-in", "MND-CHK", status="LOGGED" if mind.today else "DUE")
        today = mind.today or {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        fields: dict[str, QSpinBox] = {}
        for idx, (key, label, default) in enumerate(
            [
                ("mood", "Mood", 5),
                ("anxiety", "Anxiety", 3),
                ("stress", "Stress", 3),
                ("energy", "Energy", 5),
                ("sleep_quality", "Sleep Quality", 5),
            ]
        ):
            cap = QLabel(label.upper())
            cap.setObjectName("CardLabel")
            spin = QSpinBox()
            spin.setRange(1, 10)
            spin.setValue(int(today.get(key, default)))
            fields[key] = spin
            grid.addWidget(cap, idx // 2 * 2, idx % 2)
            grid.addWidget(spin, idx // 2 * 2 + 1, idx % 2)
        host = QWidget()
        host.setLayout(grid)
        panel.body.addWidget(host)

        triggers = QLineEdit(str(today.get("triggers") or ""))
        triggers.setPlaceholderText("Triggers or context")
        actions = QLineEdit(str(today.get("protective_actions") or ""))
        actions.setPlaceholderText("Protective action for today")
        note = QTextEdit(str(today.get("note") or ""))
        note.setPlaceholderText("Short note or journal prompt")
        note.setFixedHeight(78)
        panel.body.addWidget(triggers)
        panel.body.addWidget(actions)
        panel.body.addWidget(note)

        save = QPushButton("SAVE CHECK-IN")
        save.setObjectName("PrimaryButton")

        def _save() -> None:
            personal_os.upsert_mental_checkin(
                self._user_id,
                mood=fields["mood"].value(),
                anxiety=fields["anxiety"].value(),
                stress=fields["stress"].value(),
                energy=fields["energy"].value(),
                sleep_quality=fields["sleep_quality"].value(),
                triggers=triggers.text(),
                protective_actions=actions.text(),
                note=note.toPlainText(),
            )
            self.refresh()

        save.clicked.connect(_save)
        panel.body.addWidget(save)
        return panel

    def _mind_protocol_panel(self, mind: personal_os.MindSnapshot) -> HudPanel:
        panel = HudPanel("Today Protocol", "MND-PRT", status=mind.protocol_title)
        title = QLabel(mind.protocol_title.upper())
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)
        for action in mind.protocol_actions:
            row = QLabel(f"- {action}")
            row.setObjectName("Muted")
            row.setWordWrap(True)
            panel.body.addWidget(row)
        if mind.crisis_note:
            crisis = QLabel(mind.crisis_note)
            crisis.setStyleSheet(f"color:{PALETTE.coral}; font-size:{TYPE.small}px;")
            crisis.setWordWrap(True)
            panel.body.addWidget(crisis)
        note = QLabel("Planning support only. Not diagnosis, treatment, or financial/medical advice.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        panel.body.addWidget(note)
        return panel

    def _mindfulness_panel(self, mind: personal_os.MindSnapshot) -> HudPanel:
        from PySide6.QtWidgets import QSpinBox

        total = mind.mindfulness_week_minutes + mind.imported_mindful_week_minutes
        panel = HudPanel("Mindfulness", "MND-MIN", status=f"{total} MIN / WK")
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        duration = QSpinBox()
        duration.setRange(1, 180)
        duration.setValue(3)
        duration.setSuffix(" min")
        kind = QComboBox()
        for item in personal_os.MINDFULNESS_TYPES:
            kind.addItem(item.title(), item)
        note = QLineEdit()
        note.setPlaceholderText("Optional note")
        save = QPushButton("LOG SESSION")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(
            lambda _=False: self._log_mindfulness(duration.value(), kind.currentData(), note.text())
        )
        lay.addWidget(duration)
        lay.addWidget(kind)
        lay.addWidget(note, 1)
        lay.addWidget(save)
        panel.body.addWidget(row)

        readout = QLabel(
            f"LOCAL {mind.mindfulness_week_minutes} MIN  ·  IMPORTED APPLE HEALTH "
            f"{mind.imported_mindful_week_minutes} MIN  ·  STREAK {mind.mindfulness_streak}D"
        )
        readout.setObjectName("Mono")
        readout.setWordWrap(True)
        panel.body.addWidget(readout)
        target = QLabel("Target: 3 minutes minimum viable session; weekly consistency over perfection.")
        target.setObjectName("Faint")
        target.setWordWrap(True)
        panel.body.addWidget(target)
        return panel

    def _log_mindfulness(self, duration: int, kind: str, note: str) -> None:
        personal_os.log_mindfulness_session(
            self._user_id,
            duration_minutes=duration,
            kind=kind,
            note=note,
        )
        self.refresh()

    def _act_process_panel(self) -> HudPanel:
        panel = HudPanel("ACT Compass", "MHL-ACT")
        for process in mental.ACT_PROCESSES:
            panel.body.addWidget(_MentalHealthResultBlock(process.label, process.prompt))
        return panel

    def _regulation_library_panel(self) -> HudPanel:
        panel = HudPanel("Neural Regulation", "MHL-REG")
        for method in mental.REGULATION_METHODS:
            panel.body.addWidget(
                _MentalHealthResultBlock(
                    method.label,
                    f"When: {method.when_to_use}\nWhy: {method.mechanism}",
                )
            )
        return panel

    def _build_calendar(self) -> None:
        """Calendar module — upcoming events mirrored from iOS/iCloud (EventKit)."""
        uid = self._user_id
        events = services.calendar_events(uid, days_back=1, days_forward=30)

        if not events:
            empty = QLabel(
                "No calendar events yet. Connect your iCloud calendar in Settings, "
                "grant access, then Sync — your iPhone's schedule appears here."
            )
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self.col.addWidget(empty)
            return

        # Agenda grouped by day: each day is its own light section.
        from collections import OrderedDict

        by_day: "OrderedDict[object, list[dict]]" = OrderedDict()
        for ev in events:
            by_day.setdefault(ev["starts_at"].date(), []).append(ev)

        for day, items in by_day.items():
            section = HudPanel(day.strftime("%A %d %B"), status=str(len(items)))
            for ev in items:
                section.body.addWidget(_CalendarEventRow(ev))
            self.col.addWidget(section)

    def _build_tasks(self) -> None:
        """Tasks module — two-way synced with the companion tasks app (Supabase)."""
        uid = self._user_id
        tasks = services.get_tasks(uid, include_done=True)

        success_message = self._task_success_message
        self._task_success_message = ""
        self.col.addWidget(
            _CommandInbox(uid, self._command_inbox_created, success_message=success_message)
        )

        # Quick-add row at the top (creates locally, pushes on next sync).
        self.col.addWidget(_TaskComposer(uid, self.refresh))

        if not tasks:
            empty = QLabel(
                "No tasks synced yet. Hit Sync to pull tasks from your tasks app — "
                "or add one above. New tasks and completions here sync both ways."
            )
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self.col.addWidget(empty)
            return

        # Group open tasks by area; completed collapse to the bottom.
        from collections import OrderedDict

        groups: "OrderedDict[str, list[dict]]" = OrderedDict()
        for t in tasks:
            if t["status"] == "done":
                continue
            groups.setdefault(t["area"], []).append(t)
        done = [t for t in tasks if t["status"] == "done"]

        for area, items in groups.items():
            section = HudPanel(area, status=str(len(items)))
            for t in items:
                section.body.addWidget(_TaskRow(t, self.refresh))
            self.col.addWidget(section)

        if done:
            section = HudPanel("Completed", status=str(len(done)))
            for t in done[:40]:
                section.body.addWidget(_TaskRow(t, self.refresh))
            self.col.addWidget(section)

    def _command_inbox_created(self, count: int) -> None:
        self._task_success_message = (
            f"Created {count} task{'s' if count != 1 else ''}. "
            "They are saved locally and will sync with the tasks backend on the next sync."
        )
        self.refresh()

    def _build_finance(self) -> None:
        uid = self._user_id
        snapshot = get_finance_dashboard_snapshot(uid)
        cashflow = personal_os.get_finance_operating_snapshot(uid)

        pending = [p for p in snapshot.providers if not p.connected]

        self.col.addWidget(
            SystemHeader(
                "Finance Terminal",
                _nav_code("finance"),
                subtitle="Read-only banking, investment and LISA monitoring.",
                sync_label=snapshot.sync_label,
                database_label=snapshot.database_label,
            )
        )

        self.col.addWidget(self._cashflow_oversight_panel(cashflow))

        # When a connector still needs a key, the setup prompt leads the page so
        # it is acted on. Once everything is live it collapses to the footer line.
        if pending:
            self.col.addWidget(self._connections_section(snapshot, start_expanded=True))

        # --- Data first: the headline numbers you open the page for. ---
        self.col.addWidget(
            VitalsStrip(
                "Capital Strip",
                "FIN-VTL",
                [
                    ("FIN-NW", snapshot.metrics[0]),
                    ("FIN-CSH", snapshot.metrics[1]),
                    ("FIN-INV", snapshot.metrics[2]),
                    ("FIN-LSA", snapshot.metrics[3]),
                    ("FIN-DBT", snapshot.metrics[4]),
                ],
            )
        )

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)

        grid.addWidget(FinanceTerminalPanel(snapshot.allocation), 0, 0)
        trajectory = _signal_panel(
            "Capital Trajectory",
            "FIN-TRJ",
            snapshot.capital_series,
            height=220,
        )
        grid.addWidget(trajectory, 0, 1)
        grid.addWidget(self._account_exposure_panel(snapshot.accounts), 1, 0)
        grid.addWidget(
            self._liabilities_panel(
                snapshot.liabilities,
                snapshot.credit_facilities,
                snapshot.total_debt,
                snapshot.available_credit,
            ),
            1,
            1,
        )
        self.col.addWidget(grid_host)

        # Risk monitor sits on its own row beneath assets vs. liabilities.
        self.col.addWidget(self._risk_panel(snapshot.risk))

        self.col.addWidget(self._finance_intelligence_panel(snapshot.intelligence))

        intelligence_host = QWidget()
        intelligence_grid = QGridLayout(intelligence_host)
        intelligence_grid.setContentsMargins(0, 0, 0, 0)
        intelligence_grid.setHorizontalSpacing(16)
        intelligence_grid.setVerticalSpacing(16)
        intelligence_grid.addWidget(self._recurring_expenses_panel(snapshot.intelligence), 0, 0)
        intelligence_grid.addWidget(self._finance_alerts_panel(snapshot.intelligence), 0, 1)
        intelligence_grid.addWidget(self._funding_flows_panel(snapshot.intelligence), 1, 0)
        intelligence_grid.addWidget(self._finance_projection_panel(snapshot.intelligence), 1, 1)
        self.col.addWidget(intelligence_host)

        lisa_accounts = self._lisa_accounts(snapshot.accounts)
        if lisa_accounts:
            self.col.addWidget(self._lisa_panel(lisa_accounts))

        if snapshot.stocks_isa is not None:
            self.col.addWidget(self._stocks_isa_panel(snapshot.stocks_isa))

        detail_host = QWidget()
        detail_grid = QGridLayout(detail_host)
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(16)
        detail_grid.setVerticalSpacing(16)
        detail_grid.addWidget(self._transaction_panel(snapshot.transactions), 0, 0)
        zones = [
            (
                str(row["label"]),
                float(row["value"]),
                [PALETTE.accent, PALETTE.violet, PALETTE.orange, PALETTE.positive, PALETTE.coral][
                    i % 5
                ],
            )
            for i, row in enumerate(snapshot.spend_zones[:5])
        ] or [("idle", 1.0, PALETTE.border)]
        detail_grid.addWidget(ZoneDistribution("Spend Distribution", "FIN-SPD", zones), 0, 1)
        self.col.addWidget(detail_host)

        # --- Setup last: collapsed when every connector is already live. ---
        if not pending:
            self.col.addWidget(self._connections_section(snapshot, start_expanded=False))

    def _cashflow_oversight_panel(
        self, cashflow: personal_os.FinanceOperatingSnapshot
    ) -> HudPanel:
        status = "PACE HIGH" if cashflow.weekly_pace_delta > 25 else "ON WATCH"
        panel = HudPanel("Monthly Cashflow", "MNY-CFO", status=status)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        items = [
            ("Income", f"£{cashflow.monthly_income:,.0f}", PALETTE.positive),
            ("Fixed Costs", f"£{cashflow.fixed_costs:,.0f}", PALETTE.text),
            ("Subscriptions", f"£{cashflow.subscriptions:,.0f}", PALETTE.orange),
            ("Debt Repayments", f"£{cashflow.debt_repayments:,.0f}", PALETTE.coral),
            ("Savings", f"£{cashflow.savings:,.0f}", PALETTE.violet),
            ("Discretionary", f"£{cashflow.discretionary_spend:,.0f}", PALETTE.accent),
            ("Remaining Buffer", f"£{cashflow.remaining_buffer:,.0f}", PALETTE.positive if cashflow.remaining_buffer >= 0 else PALETTE.coral),
            ("Safe To Spend", f"£{cashflow.safe_to_spend:,.0f}/day", PALETTE.accent),
        ]
        for idx, (label, value, color) in enumerate(items):
            grid.addWidget(self._mini_readout_box(label, value, color), idx // 4, idx % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        panel.body.addWidget(host)

        pace = QLabel(
            f"THIS WEEK £{cashflow.weekly_spend:,.0f}  ·  "
            f"{cashflow.weekly_pace_delta:+,.0f} VS EXPECTED PACE"
        )
        pace.setObjectName("Mono")
        pace.setStyleSheet(
            f"color:{PALETTE.orange if cashflow.weekly_pace_delta > 0 else PALETTE.positive};"
        )
        panel.body.addWidget(pace)
        if cashflow.upcoming_bills:
            panel.body.addWidget(_mini_heading("Upcoming bills"))
            for bill in cashflow.upcoming_bills[:4]:
                row = QLabel(bill)
                row.setObjectName("Faint")
                panel.body.addWidget(row)
        if cashflow.warnings:
            panel.body.addWidget(_mini_heading("Warnings"))
            for warning in cashflow.warnings:
                row = QLabel(warning)
                row.setStyleSheet(f"color:{PALETTE.orange}; font-size:{TYPE.small}px;")
                row.setWordWrap(True)
                panel.body.addWidget(row)
        return panel

    def _mini_readout_box(self, label: str, value: str, color: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        k = QLabel(label.upper())
        k.setObjectName("CardLabel")
        v = QLabel(value)
        v.setStyleSheet(f"color:{color}; font-size:{TYPE.h2}px; font-weight:750;")
        lay.addWidget(k)
        lay.addWidget(v)
        return box

    def _connections_section(
        self, snapshot: FinanceDashboardSnapshot, *, start_expanded: bool
    ) -> QWidget:
        """Collapsible connections block: a one-line status with the full
        credential-entry + provider cards + setup queue tucked behind a toggle."""
        providers = snapshot.providers
        live = sum(1 for p in providers if p.connected)
        total = len(providers)
        all_live = total > 0 and live == total
        tone = PALETTE.positive if all_live else PALETTE.orange

        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # Status line + expander toggle.
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(8)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{tone}; font-size:8px;")
        head_lay.addWidget(dot)

        missing = total - live
        label_text = (
            f"ALL CONNECTORS LIVE  {live}/{total}"
            if all_live
            else f"{missing} CONNECTOR{'S NEED' if missing != 1 else ' NEEDS'} SETUP  {live}/{total}"
        )
        status = QLabel(label_text)
        status.setObjectName("Mono")
        status.setStyleSheet(f"color:{tone};")
        head_lay.addWidget(status)
        head_lay.addStretch(1)

        toggle = QToolButton()
        toggle.setObjectName("GhostButton")
        toggle.setCheckable(True)
        toggle.setChecked(start_expanded)
        toggle.setCursor(Qt.PointingHandCursor)
        head_lay.addWidget(toggle)
        outer.addWidget(head)

        # Collapsible body: the original credential + provider cards + setup queue.
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(14)

        body_lay.addWidget(self._credential_entry_panel(providers))

        provider_host = QWidget()
        provider_grid = QGridLayout(provider_host)
        provider_grid.setContentsMargins(0, 0, 0, 0)
        provider_grid.setHorizontalSpacing(14)
        provider_grid.setVerticalSpacing(14)
        for i, provider in enumerate(providers):
            provider_grid.addWidget(self._provider_plan_panel(provider), i // 3, i % 3)
        body_lay.addWidget(provider_host)

        body_lay.addWidget(
            self._setup_queue_panel(snapshot.setup_tasks, snapshot.security_posture)
        )

        outer.addWidget(body)

        def _apply(checked: bool) -> None:
            body.setVisible(checked)
            toggle.setText("HIDE CONNECTIONS" if checked else "MANAGE CONNECTIONS")

        toggle.toggled.connect(_apply)
        _apply(start_expanded)
        return host

    def _credential_entry_panel(self, providers: list[FinanceProviderPlan]) -> HudPanel:
        from PySide6.QtWidgets import QMessageBox

        provider = next((p for p in providers if p.key == "open_banking"), None)
        status = provider.status_label if provider else "OFFLINE"
        panel = HudPanel("Credential Entry", "FIN-KEY", status=status)

        title = QLabel("STARLING PERSONAL ACCESS TOKEN")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        note = QLabel(
            "Do this in order: open Starling Personal Access, create or copy a token with "
            "read permissions, paste it below, then store it in Keychain."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        panel.body.addWidget(note)

        help_steps = [
            "1. Open Starling Developer Personal Access.",
            "2. Create a Personal Access Token for your own Starling account.",
            "3. Grant account, balance and transaction feed read permissions.",
            "4. Paste the token below and click Store in Keychain.",
        ]
        for step in help_steps:
            step_label = QLabel(step)
            step_label.setObjectName("Faint")
            step_label.setWordWrap(True)
            panel.body.addWidget(step_label)

        portal_button = QPushButton("OPEN STARLING PERSONAL ACCESS")
        portal_button.setObjectName("GhostButton")
        portal_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://developer.starlingbank.com/personal/keys")
            )
        )
        panel.body.addWidget(portal_button)

        inputs: dict[str, QLineEdit] = {}
        fields = provider.credential_fields if provider else ()
        for field, label in fields:
            field_row = QHBoxLayout()
            field_row.setSpacing(9)
            field_label = QLabel(label.upper())
            field_label.setObjectName("ModuleCode")
            field_label.setFixedWidth(90)
            entry = QLineEdit()
            entry.setEchoMode(QLineEdit.Password)
            entry.setPlaceholderText(f"Paste {label} from Starling")
            field_row.addWidget(field_label)
            field_row.addWidget(entry, 1)
            panel.body.addLayout(field_row)
            inputs[field] = entry

        button = QPushButton("STORE IN KEYCHAIN")
        button.setObjectName("PrimaryButton")
        button.setEnabled(provider is not None)
        panel.body.addWidget(button)

        state = QLabel(
                "Current state: "
                + (
                    "STARLING TOKEN STORED IN KEYCHAIN"
                    if provider and provider.status_label in {"KEY STORED", "TOKEN STORED"}
                    else "WAITING FOR STARLING TOKEN"
            )
        )
        state.setObjectName("Mono")
        panel.body.addWidget(state)

        def _store() -> None:
            if provider is None:
                return
            secret_values = {field: entry.text().strip() for field, entry in inputs.items()}
            for entry in inputs.values():
                entry.clear()
            if not all(secret_values.values()):
                QMessageBox.warning(
                    self,
                    "Missing credential",
                    "Paste the Starling Personal Access Token first.",
                )
                return
            try:
                store_provider_credentials(self._user_id, provider.key, secret_values)
            except Exception as exc:
                QMessageBox.warning(self, "Credential not stored", str(exc))
                return
            QMessageBox.information(
                self,
                "Credential stored",
                "Starling token stored in macOS Keychain. Plaintext was not written to SQLite.",
            )
            self.refresh()

        button.clicked.connect(_store)
        for entry in inputs.values():
            entry.returnPressed.connect(_store)
        return panel

    def _provider_plan_panel(self, provider: FinanceProviderPlan) -> HudPanel:
        tone_color = {
            "good": PALETTE.positive,
            "bad": PALETTE.coral,
            "neutral": PALETTE.orange,
        }.get(provider.tone, PALETTE.accent)
        panel = HudPanel(
            provider.title,
            provider.code,
            status=provider.status_label,
            accent=tone_color,
        )

        role = QLabel(provider.role.upper())
        role.setObjectName("PanelTitle")
        role.setWordWrap(True)
        panel.body.addWidget(role)

        for label, value in [
            ("AUTH", provider.auth_method),
            ("SCOPE", provider.data_scope),
            ("SYNC", provider.last_synced_label),
        ]:
            row = QHBoxLayout()
            k = QLabel(label)
            k.setObjectName("ModuleCode")
            v = QLabel(value)
            v.setObjectName("Muted")
            v.setWordWrap(True)
            row.addWidget(k)
            row.addWidget(v, 1)
            panel.body.addLayout(row)

        for idx, item in enumerate(provider.required_items, start=1):
            row = QHBoxLayout()
            row.setSpacing(7)
            code = QLabel(f"{idx:02d}")
            code.setObjectName("ModuleCode")
            text = QLabel(item)
            text.setObjectName("Faint")
            text.setWordWrap(True)
            row.addWidget(code)
            row.addWidget(text, 1)
            panel.body.addLayout(row)

        note = QLabel(provider.security_note)
        note.setObjectName("Mono")
        note.setWordWrap(True)
        panel.body.addWidget(note)

        action = QPushButton("CONNECTED" if provider.connected else provider.action_label)
        action.setObjectName("GhostButton")
        action.setEnabled(bool(provider.credential_label) and not provider.connected)
        action.setToolTip("Stores the key locally in macOS Keychain; SQLite keeps only a reference.")
        if action.isEnabled():
            action.clicked.connect(lambda _=False, p=provider: self._open_finance_key_dialog(p))
        panel.body.addWidget(action)
        return panel

    def _open_finance_key_dialog(self, provider: FinanceProviderPlan) -> None:
        from PySide6.QtWidgets import QMessageBox

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{provider.title} credential")
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel(provider.credential_label.upper())
        title.setObjectName("PanelTitle")
        lay.addWidget(title)

        note = QLabel(
            "Paste the key here on this Mac only. ORION stores it in macOS Keychain "
            "and keeps no plaintext copy in the database."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        inputs: dict[str, QLineEdit] = {}
        for field, label in provider.credential_fields:
            field_label = QLabel(label.upper())
            field_label.setObjectName("ModuleCode")
            lay.addWidget(field_label)
            entry = QLineEdit()
            entry.setEchoMode(QLineEdit.Password)
            entry.setPlaceholderText(label)
            lay.addWidget(entry)
            inputs[field] = entry

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        lay.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            for entry in inputs.values():
                entry.clear()
            return
        secret_values = {field: entry.text().strip() for field, entry in inputs.items()}
        for entry in inputs.values():
            entry.clear()
        if not all(secret_values.values()):
            return
        try:
            store_provider_credentials(self._user_id, provider.key, secret_values)
        except Exception as exc:
            QMessageBox.warning(self, "Credential not stored", str(exc))
            return
        QMessageBox.information(
            self,
            "Credential stored",
            f"{provider.title} credentials stored in macOS Keychain. "
            "The next live connector pass can use them.",
        )
        self.refresh()

    def _setup_queue_panel(self, tasks: list[str], posture: str) -> HudPanel:
        panel = HudPanel("Secure Setup Queue", "FIN-SEC", status=posture)
        intro = QLabel(
            "Starling Personal Access Tokens can now be stored locally in macOS Keychain. "
            "LISA still depends on provider API or export support."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        panel.body.addWidget(intro)
        if not tasks:
            ok = QLabel("ALL FINANCE CONNECTORS ARE READY")
            ok.setObjectName("Mono")
            panel.body.addWidget(ok)
            return panel
        for idx, task in enumerate(tasks, start=1):
            row = QHBoxLayout()
            code = QLabel(f"TASK-{idx:02d}")
            code.setObjectName("ModuleCode")
            text = QLabel(task)
            text.setObjectName("Faint")
            text.setWordWrap(True)
            row.addWidget(code)
            row.addWidget(text, 1)
            panel.body.addLayout(row)
        return panel

    def _account_exposure_panel(self, accounts: list[dict]) -> HudPanel:
        panel = HudPanel("Account Exposure", "FIN-ACC", status=f"{len(accounts)} ACCT")
        if not accounts:
            empty = QLabel("NO ACCOUNT SNAPSHOTS")
            empty.setObjectName("Mono")
            panel.body.addWidget(empty)
            return panel
        for account in accounts[:7]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            source = QLabel(str(account.get("source_key") or "local").upper())
            source.setObjectName("ModuleCode")
            source.setFixedWidth(74)
            lay.addWidget(source)

            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(str(account["name"]).upper())
            name.setObjectName("PanelTitle")
            meta = QLabel(
                f"{account['kind']}  ·  {account['source_status_label']}  ·  "
                f"{account['snapshot_date']}".upper()
            )
            meta.setObjectName("Mono")
            text.addWidget(name)
            text.addWidget(meta)
            extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
            if account.get("source_key") == "open_banking" and extra.get("starling_available_to_spend_minor") is not None:
                outside = float(extra.get("starling_available_to_spend_minor") or 0) / 100.0
                spaces = float(extra.get("starling_spaces_balance_minor") or 0) / 100.0
                split = QLabel(f"OUTSIDE SPACES £{outside:,.2f}  ·  SPACES £{spaces:,.2f}")
                split.setObjectName("Faint")
                split.setWordWrap(True)
                text.addWidget(split)
            lay.addLayout(text, 1)

            value = QLabel(f"£{float(account['value']):,.2f}")
            value.setObjectName("Mono")
            value.setStyleSheet(f"color:{PALETTE.text};")
            lay.addWidget(value)
            panel.body.addWidget(row)
        return panel

    def _liabilities_panel(
        self,
        liabilities: list[LiabilityLine],
        facilities: list[CreditFacilityLine],
        total_debt: float,
        available_credit: float,
    ) -> HudPanel:
        panel = HudPanel(
            "Liabilities & Credit",
            "FIN-LIA",
            status=f"OWE £{total_debt:,.0f}",
            accent=PALETTE.coral if total_debt else PALETTE.border,
        )

        # --- Hard debts: money actually owed (reduces net worth). ---
        debt_head = QLabel("DEBTS OWED")
        debt_head.setObjectName("ModuleCode")
        panel.body.addWidget(debt_head)
        if not liabilities:
            none_owed = QLabel("NO DEBTS RECORDED")
            none_owed.setObjectName("Mono")
            panel.body.addWidget(none_owed)
        for line in liabilities:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            name = QLabel(line.name.upper())
            name.setObjectName("PanelTitle")
            kind = QLabel(line.kind.upper())
            kind.setObjectName("Mono")
            kind.setFixedWidth(56)
            value = QLabel(f"-£{line.balance:,.2f}")
            value.setObjectName("Mono")
            value.setStyleSheet(f"color:{PALETTE.coral};")
            lay.addWidget(kind)
            lay.addWidget(name, 1)
            lay.addWidget(value)
            panel.body.addWidget(row)

        if liabilities:
            total_row = QLabel(f"TOTAL OWED  -£{total_debt:,.2f}")
            total_row.setObjectName("Mono")
            total_row.setStyleSheet(f"color:{PALETTE.coral};")
            panel.body.addWidget(total_row)

        # --- Available credit: headroom, NOT owed — never touches net worth. ---
        if facilities:
            panel.body.addWidget(Divider())
            credit_head = QLabel(
                f"AVAILABLE CREDIT  £{available_credit:,.0f}  ·  SPENDING POWER, NOT OWED"
            )
            credit_head.setObjectName("ModuleCode")
            credit_head.setWordWrap(True)
            panel.body.addWidget(credit_head)
            for fac in facilities:
                row = QWidget()
                lay = QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(8)
                name = QLabel(fac.name.upper())
                name.setObjectName("Faint")
                avail = QLabel(f"£{fac.available:,.0f} free")
                avail.setObjectName("Mono")
                avail.setStyleSheet(f"color:{PALETTE.text_faint};")
                lay.addWidget(name, 1)
                lay.addWidget(avail)
                panel.body.addWidget(row)
        return panel

    def _transaction_panel(self, txns: list[dict]) -> HudPanel:
        panel = HudPanel("Transaction Stream", "FIN-TXN", status=f"{len(txns)} RX")
        if not txns:
            empty = QLabel("NO RECENT MOVEMENTS")
            empty.setObjectName("Mono")
            panel.body.addWidget(empty)
            return panel
        for txn in txns:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            day = QLabel(txn["booked_at"].strftime("%d %b").upper())
            day.setObjectName("ModuleCode")
            day.setFixedWidth(48)
            lay.addWidget(day)

            text = QVBoxLayout()
            text.setSpacing(0)
            desc = QLabel(str(txn["description"]).upper())
            desc.setObjectName("PanelTitle")
            cat = QLabel(f"{txn['category']}  ·  {txn['account']}".upper())
            cat.setObjectName("Mono")
            text.addWidget(desc)
            text.addWidget(cat)
            lay.addLayout(text, 1)

            amount = float(txn["amount"])
            amt = QLabel(f"{amount:+,.2f}")
            amt.setObjectName("Mono")
            amt.setStyleSheet(f"color:{PALETTE.positive if amount >= 0 else PALETTE.coral};")
            lay.addWidget(amt)
            panel.body.addWidget(row)
        return panel

    def _risk_panel(self, risk: FinanceRiskSnapshot) -> HudPanel:
        panel = HudPanel("Risk Monitor", "FIN-RSK", status="WATCH")
        values = [
            _clamp(risk.cash / (risk.total_assets or 1.0)),
            _clamp(1.0 - risk.debt / (risk.total_assets or 1.0)),
            _clamp(risk.runway_months / 6.0),
            _clamp(risk.live_provider_count / (risk.provider_count or 1)),
            _clamp((risk.net_worth_delta_pct + 8.0) / 16.0),
        ]
        panel.body.addWidget(
            RadarDial(
                ["Cash", "Debt", "Runway", "Live", "Trend"],
                values,
                color=PALETTE.orange if min(values) < 0.35 else PALETTE.accent,
            )
        )
        readout = QLabel(
            f"RUNWAY {risk.runway_months:.1f} MO  ·  ASSETS £{risk.total_assets:,.0f}  ·  "
            f"DEBT £{risk.debt:,.0f}"
        )
        readout.setObjectName("Mono")
        panel.body.addWidget(readout)
        return panel

    def _finance_intelligence_panel(self, intel) -> HudPanel:
        period = "NO TRANSACTION HISTORY"
        if intel.period_start and intel.period_end:
            period = f"{intel.period_start:%d %b %Y} - {intel.period_end:%d %b %Y}".upper()
        panel = HudPanel("Finance Intelligence", "FIN-INT", status=period)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for idx, item in enumerate(intel.patterns[:5]):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            label = QLabel(item.label.upper())
            label.setObjectName("ModuleCode")
            value = QLabel(item.value)
            value.setObjectName("PanelTitle")
            tone = {
                "good": PALETTE.positive,
                "warning": PALETTE.orange,
                "critical": PALETTE.coral,
            }.get(item.tone, PALETTE.text)
            value.setStyleSheet(f"color:{tone};")
            detail = QLabel(item.detail.upper())
            detail.setObjectName("Faint")
            detail.setWordWrap(True)
            lay.addWidget(label)
            lay.addWidget(value)
            lay.addWidget(detail)
            grid.addWidget(box, idx // 3, idx % 3)
        panel.body.addWidget(grid_host)
        return panel

    def _recurring_expenses_panel(self, intel) -> HudPanel:
        monthly = sum(line.monthly_estimate for line in intel.recurring)
        panel = HudPanel("Recurring & Subscriptions", "FIN-REC", status=f"£{monthly:,.0f}/MO")
        if not intel.recurring:
            empty = QLabel("NO RECURRING EXPENSES DETECTED")
            empty.setObjectName("Mono")
            panel.body.addWidget(empty)
            return panel
        for line in intel.recurring[:8]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(line.merchant.upper())
            name.setObjectName("PanelTitle")
            due = f"NEXT {line.next_due:%d %b}" if line.next_due else "NEXT UNKNOWN"
            meta = QLabel(f"{line.cadence_label.upper()}  ·  {line.count} HITS  ·  {due}")
            meta.setObjectName("Mono")
            text.addWidget(name)
            text.addWidget(meta)
            lay.addLayout(text, 1)
            value = QLabel(f"£{line.monthly_estimate:,.2f}/mo")
            value.setObjectName("PanelTitle")
            value.setStyleSheet(f"color:{PALETTE.orange if line in intel.subscriptions else PALETTE.text};")
            lay.addWidget(value)
            panel.body.addWidget(row)
        if intel.subscriptions:
            sub_total = sum(line.monthly_estimate for line in intel.subscriptions)
            note = QLabel(f"SUBSCRIPTIONS DETECTED  {len(intel.subscriptions)}  ·  £{sub_total:,.2f}/MO")
            note.setObjectName("Faint")
            panel.body.addWidget(note)
        return panel

    def _finance_alerts_panel(self, intel) -> HudPanel:
        critical = sum(1 for alert in intel.alerts if alert.tone == "critical")
        panel = HudPanel(
            "Red Alerts",
            "FIN-ALT",
            status=f"{len(intel.alerts)} FLAGS",
            accent=PALETTE.coral if critical else PALETTE.orange,
        )
        if not intel.alerts:
            ok = QLabel("NO HIGH-SIGNAL ALERTS FROM TRANSACTION HISTORY")
            ok.setObjectName("Mono")
            panel.body.addWidget(ok)
            return panel
        for alert in intel.alerts[:7]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            marker = QLabel("!" if alert.tone == "critical" else "•")
            marker.setObjectName("ModuleCode")
            marker.setStyleSheet(f"color:{PALETTE.coral if alert.tone == 'critical' else PALETTE.orange};")
            marker.setFixedWidth(18)
            lay.addWidget(marker)
            text = QVBoxLayout()
            text.setSpacing(0)
            title = QLabel(alert.title.upper())
            title.setObjectName("PanelTitle")
            detail = QLabel(alert.detail.upper())
            detail.setObjectName("Faint")
            detail.setWordWrap(True)
            text.addWidget(title)
            text.addWidget(detail)
            lay.addLayout(text, 1)
            value = QLabel(f"£{alert.amount:,.2f}")
            value.setObjectName("Mono")
            value.setStyleSheet(f"color:{PALETTE.coral if alert.tone == 'critical' else PALETTE.orange};")
            lay.addWidget(value)
            panel.body.addWidget(row)
        return panel

    def _funding_flows_panel(self, intel) -> HudPanel:
        total = sum(line.monthly_rate for line in intel.funding_flows)
        panel = HudPanel("Account Funding", "FIN-FLO", status=f"£{total:,.0f}/MO")
        if not intel.funding_flows:
            empty = QLabel("NO ACCOUNT-FUNDING FLOWS DETECTED")
            empty.setObjectName("Mono")
            panel.body.addWidget(empty)
            return panel
        for line in intel.funding_flows[:8]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(line.destination.upper())
            name.setObjectName("PanelTitle")
            last = f"LAST {line.last_seen:%d %b}" if line.last_seen else "LAST UNKNOWN"
            meta = QLabel(f"{line.count} FLOWS  ·  {last}  ·  TOTAL £{line.total:,.2f}")
            meta.setObjectName("Mono")
            text.addWidget(name)
            text.addWidget(meta)
            lay.addLayout(text, 1)
            value = QLabel(f"£{line.monthly_rate:,.2f}/mo")
            value.setObjectName("PanelTitle")
            value.setStyleSheet(f"color:{PALETTE.positive};")
            lay.addWidget(value)
            panel.body.addWidget(row)
        return panel

    def _finance_projection_panel(self, intel) -> HudPanel:
        panel = HudPanel("Projection Console", "FIN-PRJ", status="1Y / 3Y / 5Y")
        if not intel.projections:
            empty = QLabel("NO PROJECTION INPUTS AVAILABLE")
            empty.setObjectName("Mono")
            panel.body.addWidget(empty)
            return panel
        for line in intel.projections:
            block = QWidget()
            lay = QVBoxLayout(block)
            lay.setContentsMargins(0, 0, 0, 8)
            lay.setSpacing(5)
            title = QLabel(f"{line.label.upper()}  ·  £{line.monthly_contribution:,.2f}/MO")
            title.setObjectName("PanelTitle")
            lay.addWidget(title)
            values = QLabel(
                f"1Y £{line.value_1y:,.2f}  ·  3Y £{line.value_3y:,.2f}  ·  5Y £{line.value_5y:,.2f}"
            )
            values.setObjectName("Mono")
            values.setStyleSheet(f"color:{PALETTE.accent};")
            values.setWordWrap(True)
            lay.addWidget(values)
            rate = QLabel(line.rate_label.upper())
            rate.setObjectName("Faint")
            rate.setWordWrap(True)
            lay.addWidget(rate)
            note = QLabel(line.note.upper())
            note.setObjectName("Faint")
            note.setWordWrap(True)
            lay.addWidget(note)
            panel.body.addWidget(block)
        return panel

    def _lisa_accounts(self, accounts: list[dict]) -> list[dict]:
        out = []
        for account in accounts:
            source_key = str(account.get("source_key") or "").lower()
            name = str(account.get("name") or "").lower()
            extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
            if source_key == "moneybox" or "lisa" in name or "lifetime isa" in name or extra.get("is_lisa"):
                out.append(account)
        return out

    def _lisa_panel(self, accounts: list[dict]) -> HudPanel:
        total = sum(max(float(row.get("value") or 0.0), 0.0) for row in accounts)
        panel = HudPanel("Lifetime ISA", "FIN-LSA", status=f"£{total:,.0f}")
        for account in accounts:
            extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(str(account.get("name") or "Lifetime ISA").upper())
            name.setObjectName("PanelTitle")
            source = str(account.get("source_key") or "manual").replace("_", " ").upper()
            meta = QLabel(f"{source}  ·  {account.get('snapshot_date')}".upper())
            meta.setObjectName("Mono")
            text.addWidget(name)
            text.addWidget(meta)

            saved = extra.get("allowance_saved")
            total_allowance = extra.get("allowance_total")
            if saved is not None and total_allowance is not None:
                left = max(float(total_allowance) - float(saved), 0.0)
                allowance = QLabel(
                    f"ALLOWANCE SAVED £{float(saved):,.2f}  ·  LEFT £{left:,.2f}"
                )
                allowance.setObjectName("Faint")
                allowance.setWordWrap(True)
                text.addWidget(allowance)

            lay.addLayout(text, 1)
            value = QLabel(f"£{float(account.get('value') or 0.0):,.2f}")
            value.setObjectName("PanelTitle")
            value.setStyleSheet(f"color:{PALETTE.positive};")
            lay.addWidget(value)
            panel.body.addWidget(row)

        note = QLabel("MANUAL / IMPORTED LISA DATA ONLY; NO MONEYBOX LOGIN IS STORED.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        panel.body.addWidget(note)
        return panel

    def _stocks_isa_panel(self, isa: StocksAndSharesIsaOverview) -> HudPanel:
        status_text = "LIVE QUOTES" if isa.quote_refreshed_at else "STATEMENT LIVE"
        panel = HudPanel("Stocks & Shares ISA", "FIN-ISA", status=status_text)

        headline = QLabel(f"£{isa.value:,.2f}")
        headline.setObjectName("BigValue")
        panel.body.addWidget(headline)

        period = "PERIOD UNKNOWN"
        if isa.period_start and isa.period_end:
            period = f"{isa.period_start:%d %b %Y} - {isa.period_end:%d %b %Y}".upper()
        captured = (
            f"HOLDINGS {isa.holdings_captured_on:%d %b %Y}".upper()
            if isa.holdings_captured_on
            else "HOLDINGS DATE UNKNOWN"
        )
        meta = QLabel(
            f"{isa.account_name.upper()}  ·  SNAPSHOT {isa.snapshot_date:%d %b %Y}  ·  "
            f"{captured}  ·  {period}"
        )
        meta.setObjectName("Mono")
        meta.setWordWrap(True)
        panel.body.addWidget(meta)

        flow_host = QWidget()
        flow_grid = QGridLayout(flow_host)
        flow_grid.setContentsMargins(0, 8, 0, 0)
        flow_grid.setHorizontalSpacing(12)
        flow_grid.setVerticalSpacing(8)
        for idx, (label, value, tone) in enumerate(
            [
                ("Invested", isa.investments_value, PALETTE.accent),
                ("Cash", isa.cash_estimate, PALETTE.text_dim),
                ("Today", isa.day_change, PALETTE.positive if isa.day_change >= 0 else PALETTE.coral),
                ("Deposits", isa.deposits, PALETTE.positive),
                ("Withdrawals", isa.withdrawals, PALETTE.coral),
                ("Interest", isa.interest, PALETTE.violet),
            ]
        ):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            k = QLabel(label.upper())
            k.setObjectName("ModuleCode")
            v = QLabel(f"£{value:,.2f}")
            v.setObjectName("PanelTitle")
            v.setStyleSheet(f"color:{tone};")
            lay.addWidget(k)
            lay.addWidget(v)
            flow_grid.addWidget(box, idx // 3, idx % 3)
        panel.body.addWidget(flow_host)

        if isa.holdings:
            quote_label = ""
            if isa.quote_refreshed_at:
                quote_time = isa.quote_refreshed_at.astimezone()
                quote_label = f" · QUOTES {quote_time:%d %b %H:%M}".upper()
            holdings_title = QLabel(f"{len(isa.holdings)} LIVE HOLDINGS{quote_label}")
            holdings_title.setObjectName("ModuleCode")
            panel.body.addWidget(holdings_title)
            for holding in isa.holdings[:10]:
                row = QWidget()
                lay = QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(8)

                weight = QLabel(f"{float(holding.get('portfolio_weight_pct') or 0):.1f}%")
                weight.setObjectName("ModuleCode")
                weight.setFixedWidth(48)
                lay.addWidget(weight)

                text = QVBoxLayout()
                text.setSpacing(0)
                name = QLabel(str(holding.get("name") or "").upper())
                name.setObjectName("PanelTitle")
                sources = ", ".join(holding.get("sources") or [])
                qty = holding.get("quantity")
                detail = sources.upper()
                if qty is not None:
                    detail = f"{qty:g} UNITS  ·  {detail}"
                if holding.get("quote_symbol"):
                    detail = f"{detail}  ·  {holding.get('quote_symbol')}"
                meta_row = QLabel(detail)
                meta_row.setObjectName("Mono")
                meta_row.setWordWrap(True)
                text.addWidget(name)
                text.addWidget(meta_row)
                lay.addLayout(text, 1)

                value_col = QVBoxLayout()
                value_col.setSpacing(0)
                value = QLabel(f"£{float(holding.get('value') or 0):,.2f}")
                value.setObjectName("PanelTitle")
                ret = float(holding.get("return_value") or 0.0)
                ret_pct = holding.get("return_pct")
                ret_text = f"{ret:+.2f}"
                if ret_pct is not None:
                    ret_text += f" ({float(ret_pct):+.1f}%)"
                ret_label = QLabel(ret_text)
                ret_label.setObjectName("Mono")
                ret_label.setStyleSheet(
                    f"color:{PALETTE.positive if ret >= 0 else PALETTE.coral};"
                )
                value_col.addWidget(value)
                value_col.addWidget(ret_label)
                if holding.get("day_change_value") is not None:
                    day = float(holding.get("day_change_value") or 0.0)
                    day_label = QLabel(f"1D {day:+.2f}")
                    day_label.setObjectName("Mono")
                    day_label.setStyleSheet(
                        f"color:{PALETTE.positive if day >= 0 else PALETTE.coral};"
                    )
                    value_col.addWidget(day_label)
                lay.addLayout(value_col)
                panel.body.addWidget(row)

        status = isa.holdings_status.replace("_", " ").upper()
        source = f"  ·  {isa.quote_source.upper()}" if isa.quote_source else ""
        note = QLabel(f"{isa.movement_count} CASH MOVEMENTS IMPORTED  ·  {status}{source}")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        panel.body.addWidget(note)
        return panel

    def _build_health(self) -> None:
        snapshot = get_health_dashboard_snapshot(self._user_id)
        sickness = get_sickness_snapshot(self._user_id)
        recovery = personal_os.get_recovery_snapshot(self._user_id)

        self.col.addWidget(
            SystemHeader(
                "Recovery Intelligence",
                _nav_code("health"),
                subtitle=snapshot.subtitle,
                sync_label=snapshot.sync_status,
                database_label=snapshot.database_status,
            )
        )

        # Sickness protocol: status control + (when ill) today's symptom prompt.
        self.col.addWidget(self._health_status_panel(sickness))
        if sickness.needs_symptom_entry_today:
            self.col.addWidget(self._symptom_prompt_panel(sickness))

        self.col.addWidget(self._recovery_intelligence_panel(recovery))

        # The scan recolours cyan -> red with illness intensity.
        self.col.addWidget(BiometricScanPanel(snapshot, illness=sickness.illness_intensity))

        # Collapsible symptom log with per-day vitals beside each entry.
        if sickness.log:
            self.col.addWidget(self._symptom_log_section(sickness))

    def _recovery_intelligence_panel(
        self, recovery: personal_os.RecoverySnapshot
    ) -> HudPanel:
        status = (
            recovery.label
            if recovery.score is None
            else f"{recovery.label} {recovery.score:.0f}"
        )
        panel = HudPanel("Readiness Estimate", "RCV-RDY", status=status)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)

        score_col = QVBoxLayout()
        score_col.setSpacing(4)
        color = (
            PALETTE.positive if recovery.score and recovery.score >= 78
            else PALETTE.orange if recovery.score and recovery.score < 58
            else PALETTE.accent
        )
        score = QLabel(f"{recovery.score:.0f}" if recovery.score is not None else "—")
        score.setStyleSheet(f"color:{color}; font-size:42px; font-weight:800;")
        score_col.addWidget(score)
        label = QLabel(("ESTIMATED" if recovery.estimated else "DERIVED") + f" · {recovery.data_quality.upper()}")
        label.setObjectName("Mono")
        score_col.addWidget(label)
        rec = QLabel(recovery.recommendation)
        rec.setObjectName("Muted")
        rec.setWordWrap(True)
        score_col.addWidget(rec)
        lay.addLayout(score_col, 1)

        factors = QVBoxLayout()
        factors.setSpacing(5)
        factors.addWidget(_mini_heading("Contributing metrics"))
        for factor in recovery.factors:
            factors.addWidget(self._recovery_factor_row(factor))
        lay.addLayout(factors, 1)

        changes = QVBoxLayout()
        changes.setSpacing(5)
        changes.addWidget(_mini_heading("What changed"))
        for change in recovery.changes[:5]:
            item = QLabel(change)
            item.setObjectName("Faint")
            item.setWordWrap(True)
            changes.addWidget(item)
        lay.addLayout(changes, 1)
        panel.body.addWidget(row)
        return panel

    def _recovery_factor_row(self, factor: personal_os.ScoreFactor) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        color = PALETTE.accent if factor.present else PALETTE.text_faint
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:7px;")
        name = QLabel(factor.label.upper())
        name.setObjectName("Mono")
        value = QLabel(factor.value)
        value.setObjectName("Muted" if factor.present else "Faint")
        impact = QLabel(factor.impact.upper())
        impact.setObjectName("Faint")
        lay.addWidget(dot)
        lay.addWidget(name)
        lay.addStretch(1)
        lay.addWidget(impact)
        lay.addWidget(value)
        return row

    # ---- sickness protocol ------------------------------------------------- #
    _STATUS_META = {
        HealthStatus.active: ("ACTIVE", "Systems normal.", "positive"),
        HealthStatus.injured: (
            "INJURED",
            "Systems normal — overall health is not impacted.",
            "neutral",
        ),
        HealthStatus.illness: ("ILLNESS", "Unwell — logging symptoms daily.", "bad"),
    }

    def _health_status_panel(self, sickness) -> HudPanel:
        from PySide6.QtWidgets import QComboBox

        label, blurb, tone = self._STATUS_META[sickness.status]
        tone_color = {
            "positive": PALETTE.positive,
            "neutral": PALETTE.accent,
            "bad": PALETTE.coral,
        }[tone]
        status_text = label + (f"  ·  DAY {sickness.days_ill}" if sickness.is_ill else "")
        panel = HudPanel(
            "Status Protocol", "HLT-STA", status=status_text, accent=tone_color
        )

        blurb_label = QLabel(blurb.upper())
        blurb_label.setObjectName("Muted")
        blurb_label.setWordWrap(True)
        panel.body.addWidget(blurb_label)

        row = QHBoxLayout()
        row.setSpacing(9)
        picker_label = QLabel("SET STATUS")
        picker_label.setObjectName("ModuleCode")
        row.addWidget(picker_label)

        picker = QComboBox()
        order = [HealthStatus.active, HealthStatus.injured, HealthStatus.illness]
        for st in order:
            picker.addItem(self._STATUS_META[st][0].title(), st.value)
        picker.setCurrentIndex(order.index(sickness.status))
        row.addWidget(picker, 1)
        panel.body.addLayout(row)

        # Optional note (injury detail / context).
        note = QLineEdit()
        note.setPlaceholderText("Optional note (e.g. injury detail)")
        if sickness.status_note:
            note.setText(sickness.status_note)
        panel.body.addWidget(note)

        apply_btn = QPushButton("APPLY STATUS")
        apply_btn.setObjectName("PrimaryButton")

        def _apply() -> None:
            chosen = HealthStatus(picker.currentData())
            set_status(self._user_id, chosen, note=note.text().strip() or None)
            self.refresh()

        apply_btn.clicked.connect(_apply)
        panel.body.addWidget(apply_btn)
        return panel

    def _symptom_prompt_panel(self, sickness) -> HudPanel:
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        panel = HudPanel(
            "Daily Symptom Check", "HLT-SYM", status="ENTRY DUE", accent=PALETTE.coral
        )
        intro = QLabel("HOW ARE YOU FEELING TODAY? LOG IT FOR THE SYMPTOM RECORD.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        panel.body.addWidget(intro)

        # Severity radio row.
        sev_row = QHBoxLayout()
        sev_row.setSpacing(9)
        sev_label = QLabel("SEVERITY")
        sev_label.setObjectName("ModuleCode")
        sev_row.addWidget(sev_label)
        sev_group = QButtonGroup(panel)
        sev_buttons: dict[SymptomSeverity, QRadioButton] = {}
        for sev in (SymptomSeverity.mild, SymptomSeverity.moderate, SymptomSeverity.severe):
            rb = QRadioButton(sev.value.title())
            sev_group.addButton(rb)
            sev_buttons[sev] = rb
            sev_row.addWidget(rb)
        sev_buttons[SymptomSeverity.mild].setChecked(True)
        sev_row.addStretch(1)
        panel.body.addLayout(sev_row)

        # Symptom checklist grid.
        checks: dict[str, QCheckBox] = {}
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for i, (key, lbl) in enumerate(SYMPTOM_CHECKLIST):
            cb = QCheckBox(lbl)
            checks[key] = cb
            grid.addWidget(cb, i // 2, i % 2)
        panel.body.addWidget(grid_host)

        note = QTextEdit()
        note.setPlaceholderText("Notes (optional) — anything else worth recording today")
        note.setFixedHeight(54)
        panel.body.addWidget(note)

        save = QPushButton("LOG TODAY'S SYMPTOMS")
        save.setObjectName("PrimaryButton")

        def _save() -> None:
            sev = next(s for s, rb in sev_buttons.items() if rb.isChecked())
            chosen = [k for k, cb in checks.items() if cb.isChecked()]
            upsert_symptom_entry(
                self._user_id,
                severity=sev,
                symptoms=chosen,
                note=note.toPlainText().strip() or None,
            )
            self.refresh()

        save.clicked.connect(_save)
        panel.body.addWidget(save)
        return panel

    def _symptom_log_section(self, sickness) -> QWidget:
        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(8)
        title = QLabel(f"SYMPTOM LOG  ·  {len(sickness.log)} ENTRIES")
        title.setObjectName("ModuleCode")
        head_lay.addWidget(title)
        head_lay.addStretch(1)
        toggle = QToolButton()
        toggle.setObjectName("GhostButton")
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setCursor(Qt.PointingHandCursor)
        head_lay.addWidget(toggle)
        outer.addWidget(head)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)
        body_lay.addWidget(self._symptom_log_panel(sickness))
        outer.addWidget(body)

        def _apply(checked: bool) -> None:
            body.setVisible(checked)
            toggle.setText("HIDE LOG" if checked else "SHOW LOG")

        toggle.toggled.connect(_apply)
        _apply(False)
        return host

    def _symptom_log_panel(self, sickness) -> HudPanel:
        panel = HudPanel("Symptom Record", "HLT-LOG", status=f"{len(sickness.log)} DAYS")
        sev_color = {
            SymptomSeverity.mild: PALETTE.orange,
            SymptomSeverity.moderate: PALETTE.coral,
            SymptomSeverity.severe: PALETTE.coral,
        }
        for entry in sickness.log:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)

            # Left: the symptom entry.
            left = QVBoxLayout()
            left.setSpacing(0)
            day = QLabel(entry.day.strftime("%d %b").upper())
            day.setObjectName("PanelTitle")
            sev = QLabel(entry.severity.value.upper())
            sev.setObjectName("Mono")
            sev.setStyleSheet(f"color:{sev_color.get(entry.severity, PALETTE.coral)};")
            head_line = QHBoxLayout()
            head_line.setSpacing(8)
            head_line.addWidget(day)
            head_line.addWidget(sev)
            head_line.addStretch(1)
            left.addLayout(head_line)
            symptoms = QLabel(
                ", ".join(entry.symptom_labels).upper() if entry.symptom_labels else "NO SYMPTOMS TICKED"
            )
            symptoms.setObjectName("Faint")
            symptoms.setWordWrap(True)
            left.addWidget(symptoms)
            if entry.note:
                note = QLabel(entry.note)
                note.setObjectName("Muted")
                note.setWordWrap(True)
                left.addWidget(note)
            lay.addLayout(left, 3)

            # Right: that day's vitals.
            vitals = QVBoxLayout()
            vitals.setSpacing(0)
            for vlabel, vval in (
                ("SLEEP", f"{entry.sleep_hours:.1f}H" if entry.sleep_hours is not None else "—"),
                ("RHR", f"{entry.resting_hr}" if entry.resting_hr is not None else "—"),
                ("HRV", f"{entry.hrv_ms:.0f}MS" if entry.hrv_ms is not None else "—"),
            ):
                vrow = QHBoxLayout()
                vrow.setSpacing(6)
                k = QLabel(vlabel)
                k.setObjectName("ModuleCode")
                v = QLabel(vval)
                v.setObjectName("Mono")
                vrow.addWidget(k)
                vrow.addStretch(1)
                vrow.addWidget(v)
                vitals.addLayout(vrow)
            lay.addLayout(vitals, 2)

            panel.body.addWidget(row)
            panel.body.addWidget(Divider())
        return panel

    def _build_productivity(self) -> None:
        uid = self._user_id
        af = services.activity_frame(uid)
        self.add_metric_strip(
            [
                Metric(
                    "Deep Work (7d)",
                    f"{af['deep_work_minutes'].tail(7).sum() / 60:.1f}h" if not af.empty else "—",
                ),
                Metric(
                    "Active min (7d avg)",
                    f"{af['active_minutes'].tail(7).mean():.0f}" if not af.empty else "—",
                ),
                Metric(
                    "Steps (7d avg)", f"{af['steps'].tail(7).mean():,.0f}" if not af.empty else "—"
                ),
            ]
        )
        dw = ChartPanel("Deep Work — minutes/day", note="30 day")
        if not af.empty:
            dw.bars(af["deep_work_minutes"].tolist(), color=PALETTE.accent)
        self.col.addWidget(dw)

    def _build_run_plan(self) -> None:
        recovery = personal_os.get_recovery_snapshot(self._user_id)
        plan = personal_os.get_run_plan_snapshot(self._user_id, recovery)
        self.col.addWidget(
            SystemHeader(
                "Run Plan",
                _nav_code("run_plan"),
                subtitle="Conservative 5k progression using imported run history and recovery status.",
                sync_label=plan.adherence_label,
                database_label="HAE WORKOUTS",
            )
        )
        self.col.addWidget(
            VitalsStrip(
                "Run Vitals",
                "RUN-VTL",
                [
                    ("RUN-WK", Metric("Week Distance", f"{plan.week_distance_km:.1f}/{plan.weekly_target_km:.1f} km")),
                    ("RUN-FRQ", Metric("Recent Runs", str(plan.recent_frequency))),
                    ("RUN-AVG", Metric("Avg Distance", f"{plan.average_distance_km:.1f} km")),
                    ("RUN-PCE", Metric("Avg Pace", plan.average_pace_label)),
                    ("RUN-RCV", Metric("Recovery", recovery.label)),
                ],
            )
        )

        top = QWidget()
        grid = QGridLayout(top)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self._next_run_panel(plan), 0, 0)
        grid.addWidget(self._run_guardrail_panel(plan), 0, 1)
        grid.addWidget(self._weekly_run_plan_panel(plan), 1, 0, 1, 2)
        self.col.addWidget(top)

    def _next_run_panel(self, plan: personal_os.RunPlanSnapshot) -> HudPanel:
        run = plan.next_run
        panel = HudPanel("Next Run Recommendation", "RUN-NXT", status=run.session_type)
        title = QLabel(run.title)
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:30px; font-weight:800;")
        title.setWordWrap(True)
        panel.body.addWidget(title)
        detail = QLabel(run.detail)
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        panel.body.addWidget(detail)
        panel.body.addWidget(
            MeterBar(
                f"WEEKLY PROGRESS · {plan.adherence_label.upper()}",
                (plan.week_distance_km / max(plan.weekly_target_km, 1.0)) * 100,
                suffix="%",
                color=PALETTE.orange if plan.week_distance_km > plan.weekly_target_km else PALETTE.accent,
                readout=f"{plan.week_distance_km:.1f}/{plan.weekly_target_km:.1f} km",
            )
        )
        return panel

    def _run_guardrail_panel(self, plan: personal_os.RunPlanSnapshot) -> HudPanel:
        panel = HudPanel("Plan Engine", "RUN-ENG", status=f"WEEK {plan.current_week}")
        rows = [
            ("Goal", plan.goal),
            ("Inputs", "recent runs, average distance, pace, recovery"),
            ("Guardrail", plan.guardrail),
            ("Adherence", plan.adherence_label),
        ]
        for label, value in rows:
            panel.body.addWidget(self._kv_line(label, value))
        return panel

    def _weekly_run_plan_panel(self, plan: personal_os.RunPlanSnapshot) -> HudPanel:
        panel = HudPanel("Weekly Plan", "RUN-WKY", status=f"{len(plan.weekly_plan)} SESSIONS")
        for item in plan.weekly_plan:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            day = QLabel(item.day_label.upper())
            day.setObjectName("ModuleCode")
            day.setFixedWidth(78)
            text = QVBoxLayout()
            text.setSpacing(1)
            title = QLabel(item.title)
            title.setObjectName("PanelTitle")
            detail = QLabel(item.detail)
            detail.setObjectName("Faint")
            detail.setWordWrap(True)
            text.addWidget(title)
            text.addWidget(detail)
            lay.addWidget(day)
            lay.addLayout(text, 1)
            intensity = QLabel(item.intensity.upper())
            intensity.setObjectName("Pill")
            lay.addWidget(intensity)
            panel.body.addWidget(row)
            panel.body.addWidget(Divider())
        return panel

    def _kv_line(self, label: str, value: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        key = QLabel(label.upper())
        key.setObjectName("ModuleCode")
        key.setFixedWidth(84)
        val = QLabel(value)
        val.setObjectName("Muted")
        val.setWordWrap(True)
        lay.addWidget(key)
        lay.addWidget(val, 1)
        return row

    def _build_data(self) -> None:
        inv = personal_os.get_data_inventory(self._user_id)
        last = inv.last_import.strftime("%d %b %Y %H:%M").upper() if inv.last_import else "NEVER"
        self.col.addWidget(
            SystemHeader(
                "Data Coverage",
                _nav_code("data"),
                subtitle="Health Auto Export inventory, source freshness and unused signals.",
                sync_label=f"FILES {inv.imported_files}",
                database_label=f"LAST {last}",
            )
        )

        self.col.addWidget(
            VitalsStrip(
                "Data Vitals",
                "DAT-VTL",
                [
                    ("DAT-SRC", Metric("Sources", str(len(inv.sources)))),
                    ("DAT-MET", Metric("Metrics", f"{sum(1 for m in inv.metrics if m.count)}/{len(inv.metrics)}")),
                    ("DAT-FIL", Metric("HAE Files", str(inv.imported_files))),
                    ("DAT-WKO", Metric("Workouts", str(inv.workout_count))),
                    ("DAT-NEW", Metric("Suggestions", str(len(inv.suggestions)))),
                ],
            )
        )

        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.addWidget(self._data_metrics_panel(inv), 0, 0, 2, 1)
        grid.addWidget(self._data_sources_panel(inv), 0, 1)
        grid.addWidget(self._data_suggestions_panel(inv), 1, 1)
        self.col.addWidget(row)

    def _data_metrics_panel(self, inv: personal_os.DataInventorySnapshot) -> HudPanel:
        panel = HudPanel("Metric Inventory", "DAT-MET", status=f"{len(inv.metrics)} METRICS")
        for metric in inv.metrics:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color:{PALETTE.positive if metric.count else PALETTE.text_faint}; font-size:7px;"
            )
            name = QLabel(metric.metric.upper())
            name.setObjectName("PanelTitle")
            latest = metric.latest.isoformat() if metric.latest else "—"
            detail = QLabel(f"{metric.count} records  ·  latest {latest}  ·  {metric.use}")
            detail.setObjectName("Faint")
            detail.setWordWrap(True)
            lay.addWidget(dot)
            lay.addWidget(name, 0)
            lay.addWidget(detail, 1)
            panel.body.addWidget(row)
        return panel

    def _data_sources_panel(self, inv: personal_os.DataInventorySnapshot) -> HudPanel:
        panel = HudPanel("Sources", "DAT-SRC", status=str(len(inv.sources)))
        if not inv.sources:
            panel.body.addWidget(QLabel("No sources registered."))
            return panel
        for source in inv.sources:
            text = QLabel(source)
            text.setObjectName("Muted")
            text.setWordWrap(True)
            panel.body.addWidget(text)
        if inv.parsing_notes:
            panel.body.addWidget(Divider())
            for note in inv.parsing_notes:
                text = QLabel(note)
                text.setObjectName("Faint")
                text.setWordWrap(True)
                panel.body.addWidget(text)
        return panel

    def _data_suggestions_panel(self, inv: personal_os.DataInventorySnapshot) -> HudPanel:
        panel = HudPanel("Next Exports", "DAT-NXT", status=f"{len(inv.suggestions)} IDEAS")
        if not inv.suggestions:
            ok = QLabel("Coverage looks good for the current MVP.")
            ok.setObjectName("Muted")
            panel.body.addWidget(ok)
            return panel
        for suggestion in inv.suggestions:
            item = QLabel(f"- {suggestion}")
            item.setObjectName("Muted")
            item.setWordWrap(True)
            panel.body.addWidget(item)
        return panel

    def _build_projects(self) -> None:
        uid = self._user_id
        portfolio = services.project_portfolio(uid)
        active = [p for p in portfolio if p["status"] == "active"]
        avg = sum(p["momentum"] for p in portfolio) / len(portfolio) if portfolio else 0.0
        total_tasks = sum(p["tasks"] for p in portfolio)
        total_words = sum(p["words"] for p in portfolio)
        stale = sum(1 for p in portfolio if p["stale_days"] is not None and p["stale_days"] >= 7)

        self.col.addWidget(
            SystemHeader(
                "Project Control",
                _nav_code("projects"),
                subtitle="Portfolio momentum, throughput, and next attention.",
                sync_label=f"{len(active)} ACTIVE",
                database_label="PROJECT LOCAL",
            )
        )
        self.col.addWidget(
            VitalsStrip(
                "Project Vitals",
                "PRJ-VTL",
                [
                    ("PRJ-ACT", Metric("Active Projects", str(len(active)), trend="flat")),
                    ("PRJ-MOM", Metric("Avg Momentum", f"{avg:.0f}/100", trend="flat")),
                    ("PRJ-TASK", Metric("Tasks Done", str(total_tasks), trend="up")),
                    ("PRJ-WRD", Metric("Words Written", f"{total_words:,}", trend="up")),
                    ("PRJ-STL", Metric("Stale Signals", str(stale), trend="down",
                                        tone="bad" if stale else "neutral")),
                ],
            )
        )

        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        panel = HudPanel("Project Portfolio", "PRJ-LST", status=f"{len(portfolio)} TRACKED")
        if not portfolio:
            empty = QLabel("No projects tracked yet. Add one below to start a local portfolio.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
        for item in portfolio:
            panel.body.addWidget(self._project_row(item))
        add = QLineEdit()
        add.setPlaceholderText("+ Add a project, press Enter")
        add.returnPressed.connect(lambda: self._add_project(add.text()))
        panel.body.addWidget(add)
        grid.addWidget(panel, 0, 0)

        focus = HudPanel("Attention Queue", "PRJ-FOC", status="NEXT BEST")
        ranked = sorted(
            portfolio,
            key=lambda p: (
                0 if p["status"] == "active" else 1,
                -(p["stale_days"] or 0),
                p["momentum"],
            ),
        )
        if not ranked:
            note = QLabel("Create projects here, then sync Notion or add project metrics later.")
            note.setObjectName("Faint")
            note.setWordWrap(True)
            focus.body.addWidget(note)
        for idx, p in enumerate(ranked[:5], start=1):
            stale_label = "no signal" if p["stale_days"] is None else f"{p['stale_days']}d since signal"
            tone = PALETTE.orange if (p["stale_days"] or 0) >= 7 else PALETTE.accent
            meter = MeterBar(
                f"{idx:02d} · {p['name']} · {stale_label}",
                p["momentum"],
                suffix="",
                color=tone,
                readout=f"{p['momentum']:.0f}",
            )
            focus.body.addWidget(meter)
        grid.addWidget(focus, 0, 1)

        trend = HudPanel("Portfolio Signal", "PRJ-SIG", status="30D")
        pm = services.project_momentum(uid)
        if not pm.empty:
            import pandas as pd

            pm = pm.copy()
            pm["day"] = pd.to_datetime(pm["day"])
            daily = pm.groupby("day")["momentum"].mean().sort_index()
            trend.body.addWidget(SignalLineChart(daily.tolist(), color=PALETTE.accent, height=180))
        else:
            trend.body.addWidget(SignalLineChart([0, 0], color=PALETTE.accent, height=180))
        grid.addWidget(trend, 1, 0, 1, 2)
        self.col.addWidget(row)

    def _project_row(self, item: dict) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        series = item["series"] if len(item["series"]) > 1 else None
        tone = "bad" if (item["stale_days"] or 0) >= 7 else None
        metric = Metric(
            item["name"],
            f"{item['momentum']:.0f}",
            f"{item['delta']:+.0f}",
            item["trend"],
            series,
            tone=tone,
        )
        rl.addWidget(MetricCell(metric, f"PRJ-{item['id']:02d}"), 1)
        detail = QLabel(f"{item['tasks']} tasks · {item['words']:,} words · {item['commits']} commits")
        detail.setObjectName("Mono")
        rl.addWidget(detail, 0)
        status = QComboBox()
        status.addItems(["active", "paused", "done", "archive"])
        status.setCurrentText(item["status"] if item["status"] in ["active", "paused", "done", "archive"] else "active")
        status.setMaximumWidth(92)
        status.currentTextChanged.connect(lambda text, pid=item["id"]: self._update_project(pid, text))
        rl.addWidget(status, 0)
        return row

    def _add_project(self, name: str) -> None:
        if name.strip():
            services.add_project(self._user_id, name)
            self.refresh()

    def _update_project(self, project_id: int, status: str) -> None:
        services.update_project(project_id, status=status)
        self.refresh()

    def _build_learning(self) -> None:
        uid = self._user_id
        af = services.activity_frame(uid)
        skills = career.list_skills(uid)
        snap = diploma.get_snapshot(uid)
        deep_series = (af["deep_work_minutes"] / 60).dropna().tolist() if not af.empty else []
        week_deep = af["deep_work_minutes"].dropna().tail(7).sum() / 60 if not af.empty else 0.0
        avg_skill = sum(s.proficiency for s in skills) / len(skills) if skills else 0.0
        prepared = snap.prepared_pct if snap.prepared_pct is not None else 100.0

        self.col.addWidget(
            SystemHeader(
                "Learning Ops",
                _nav_code("learning"),
                subtitle="Study load, skill acquisition, and assessment readiness.",
                sync_label=f"{week_deep:.1f}H FOCUS",
                database_label="LEARNING LOCAL",
            )
        )
        self.col.addWidget(
            VitalsStrip(
                "Learning Vitals",
                "LRN-VTL",
                [
                    ("LRN-DPW", Metric("Deep Work 7d", f"{week_deep:.1f}h", trend="up",
                                        series=deep_series[-14:] or None)),
                    ("LRN-SKL", Metric("Skill Avg", f"{avg_skill:.0f}/100", trend="flat")),
                    ("LRN-DIP", Metric("Diploma Progress", f"{snap.progress_pct:.0f}%", trend="up")),
                    ("LRN-ASN", Metric("Open Assessments", str(snap.open_assessment_count),
                                        trend="down", tone="bad" if snap.open_assessment_count else "neutral")),
                    ("LRN-RDY", Metric("Preparedness", f"{prepared:.0f}%", trend="up",
                                        tone="bad" if prepared < 50 else "good")),
                ],
            )
        )

        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        load = HudPanel("Study Signal", "LRN-SIG", status="30D")
        load.body.addWidget(
            SignalLineChart(deep_series or [0, 0], color=PALETTE.violet, unit="h", height=170)
        )
        note = QLabel("Focus time is pulled from ActivityWatch deep-work minutes. Diploma status and career skills fill the operating picture.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        load.body.addWidget(note)
        grid.addWidget(load, 0, 0)

        skill_panel = HudPanel("Skill Roadmap", "LRN-SKL", status=f"{len(skills)} SKILLS")
        if not skills:
            empty = QLabel("No skills tracked yet. Add a skill here; it also feeds Career.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            skill_panel.body.addWidget(empty)
        for sk in skills:
            color = PALETTE.positive if sk.momentum == "up" else PALETTE.orange if sk.momentum == "down" else PALETTE.accent
            skill_panel.body.addWidget(
                MeterBar(f"{sk.name} · {sk.momentum.upper()}", sk.proficiency, suffix="%", color=color)
            )
        add_skill = QLineEdit()
        add_skill.setPlaceholderText("+ Add a skill, press Enter")
        add_skill.returnPressed.connect(lambda: self._add_learning_skill(add_skill.text()))
        skill_panel.body.addWidget(add_skill)
        grid.addWidget(skill_panel, 0, 1)

        pipeline = HudPanel("Assessment Pipeline", "LRN-ASM",
                            status=f"{snap.open_assessment_count} OPEN")
        open_assessments = [a for a in snap.assessments if (
            a.status not in ("submitted", "graded") if a.kind == "assignment" else a.status != "ready"
        )]
        if not open_assessments:
            ok = QLabel("No open assessments. Keep the next module moving before urgency builds.")
            ok.setObjectName("Faint")
            ok.setWordWrap(True)
            pipeline.body.addWidget(ok)
        for a in open_assessments[:6]:
            readiness = a.readiness if a.kind == "exam" else {
                "not_started": 0,
                "in_progress": 50,
                "submitted": 100,
                "graded": 100,
            }.get(a.status, 0)
            due = a.due_date.isoformat() if a.due_date else "no date"
            pipeline.body.addWidget(
                MeterBar(f"{a.title} · {a.kind.upper()} · {due}", readiness,
                         suffix="%", color=PALETTE.orange if readiness < 50 else PALETTE.positive)
            )
        grid.addWidget(pipeline, 1, 0)

        modules = HudPanel("Modules", "LRN-MOD", status=f"{len(snap.modules)} UNITS")
        if not snap.modules:
            modules.body.addWidget(QLabel("No modules tracked. Use the Diploma page to add modules and assessments."))
        for m in snap.modules[:7]:
            value = 100 if m.status == "done" else (m.grade or 35)
            readout = f"{m.credits}cr · {m.status.upper()}" + (f" · {m.grade:.0f}%" if m.grade is not None else "")
            modules.body.addWidget(
                MeterBar(m.name, value, suffix="", readout=readout,
                         color=PALETTE.positive if m.status == "done" else PALETTE.accent)
            )
        grid.addWidget(modules, 1, 1)
        self.col.addWidget(row)

    def _add_learning_skill(self, name: str) -> None:
        if name.strip():
            career.add_skill(self._user_id, name)
            self.refresh()


# --------------------------------------------------------------------------- #
# Stoic page — the measured path to eudaimonia
# --------------------------------------------------------------------------- #
class StoicPage(_ScrollPage):
    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        snap = get_stoic_snapshot(self._user_id)

        eud_label = f"EUDAIMONIA {snap.eudaimonia_index:.0f}" if snap.eudaimonia_index is not None \
            else "EUDAIMONIA —"
        self.col.addWidget(
            SystemHeader(
                snap.title,
                _nav_code("stoic"),
                subtitle=snap.subtitle,
                sync_label=eud_label,
                database_label=f"DATA {snap.eudaimonia_coverage * 100:.0f}%",
            )
        )

        # Honesty banner: how the numbers are derived, in one line.
        banner = QLabel(
            "This page now works as a practice cockpit: external sources feed the diagrams, "
            "and the local check-in gives sparse days a real Stoic signal."
        )
        banner.setObjectName("Faint")
        banner.setWordWrap(True)
        self.col.addWidget(banner)

        measured = sum(v.has_data for v in snap.virtues)
        self.col.addWidget(
            VitalsStrip(
                "Stoic Vitals",
                "STO-VTL",
                [
                    ("STO-EUD", Metric("Eudaimonia", f"{snap.eudaimonia_index:.0f}" if snap.eudaimonia_index is not None else "—",
                                       trend="flat")),
                    ("STO-VRT", Metric("Virtues Measured", f"{measured}/4", trend="flat")),
                    ("STO-CTL", Metric("Control", f"{snap.control.value * 100:.0f}%" if snap.control.has_data else "—",
                                       trend="up")),
                    ("STO-PRC", Metric("Practice", f"{snap.practice_consistency * 100:.0f}%" if snap.practice_consistency is not None else "—",
                                       trend="up")),
                    ("STO-LOG", Metric("Check-ins", str(len(snap.checkins)), trend="flat")),
                ],
            )
        )

        # Row 1: eudaimonia gauge | four-virtues radar | equanimity trend
        row1 = QWidget()
        g1 = QGridLayout(row1)
        g1.setContentsMargins(0, 0, 0, 0)
        g1.setHorizontalSpacing(16)
        g1.setVerticalSpacing(16)
        g1.setColumnStretch(0, 3)
        g1.setColumnStretch(1, 4)
        g1.setColumnStretch(2, 3)

        eud_status = "LIVE" if snap.eudaimonia_index is not None else "NO DATA"
        eud = HudPanel("Eudaimonia Index", "STO-EUD", status=eud_status)
        eud.body.addWidget(EudaimoniaGauge(snap.eudaimonia_index))
        eud.body.addWidget(
            SignalLineChart(snap.eudaimonia_trend, color=PALETTE.accent, height=70)
        )
        for f in snap.eudaimonia_factors:
            eud.body.addWidget(_factor_row(f))
        g1.addWidget(eud, 0, 0)

        # Radar uses 0 for unmeasured virtues but the breakdown shows NO DATA.
        virtues = HudPanel("Cardinal Virtues", "STO-VRT",
                           status=f"{sum(v.has_data for v in snap.virtues)}/4 MEASURED")
        virtues.body.addWidget(
            RadarDial(
                [v.name for v in snap.virtues],
                [(v.score / 100.0 if v.has_data else 0.0) for v in snap.virtues],
                color=PALETTE.accent,
            )
        )
        g1.addWidget(virtues, 0, 1)

        equ_status = f"{snap.equanimity.value * 100:.0f}%" if snap.equanimity.has_data else "NO DATA"
        equ = HudPanel("Equanimity · Ataraxia", "STO-EQU", status=equ_status)
        equ.body.addWidget(
            SignalLineChart(
                [v * 100 for v in snap.equanimity_trend], color=PALETTE.violet,
                unit="%", height=130,
            )
        )
        for f in snap.equanimity.factors:
            equ.body.addWidget(_factor_row(f))
        g1.addWidget(equ, 0, 2)
        self.col.addWidget(row1)

        # Virtue derivation panel: per-virtue score, coverage, and factor chain.
        self.col.addWidget(self._virtue_derivation_panel(snap.virtues))

        # Row 2: local check-in | dichotomy of control | daily practice
        row2 = QWidget()
        g2 = QGridLayout(row2)
        g2.setContentsMargins(0, 0, 0, 0)
        g2.setHorizontalSpacing(16)
        g2.setColumnStretch(0, 1)
        g2.setColumnStretch(1, 1)
        g2.setColumnStretch(2, 1)

        g2.addWidget(self._today_checkin_panel(snap), 0, 0)

        if snap.control.has_data:
            ctrl_status = "ALIGNED" if snap.control.value >= 0.5 else "DRIFT"
        else:
            ctrl_status = "NO DATA"
        ctrl = HudPanel("Dichotomy of Control", "STO-DOC", status=ctrl_status)
        ctrl.body.addWidget(ControlGauge(snap.control.value if snap.control.has_data else 0.0))
        for f in snap.control.factors:
            ctrl.body.addWidget(_factor_row(f))
        ctrl_note = QLabel("Epictetus: spend yourself only on what is up to you — your "
                           "judgements, your effort, your assent.")
        ctrl_note.setObjectName("Faint")
        ctrl_note.setWordWrap(True)
        ctrl.body.addWidget(ctrl_note)
        g2.addWidget(ctrl, 0, 1)

        prac_status = f"{snap.practice_consistency * 100:.0f}%" \
            if snap.practice_tracked and snap.practice_consistency is not None else "UNTRACKED"
        prac = HudPanel("Reflective Practice", "STO-PRC", status=prac_status)
        if snap.practice_tracked:
            src = QLabel("Ingested from Apple Health Mindfulness — including your Stoic "
                         "sessions. ORION never asks you to log a ritual twice.")
            src.setObjectName("Faint")
            src.setWordWrap(True)
            prac.body.addWidget(src)
        else:
            untracked = QLabel(
                "No mindful-session data yet. Log sessions in the Stoic app (they write to "
                "Apple Health Mindfulness), then import your Health export — ORION reads "
                "those rather than re-asking. Streaks are never invented."
            )
            untracked.setObjectName("Faint")
            untracked.setWordWrap(True)
            prac.body.addWidget(untracked)
        for pr in snap.practices:
            r = QWidget()
            rl = QHBoxLayout(r)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            mark = QLabel("◧" if pr.done else "□")
            mark.setStyleSheet(
                f"color:{PALETTE.positive if pr.done else PALETTE.text_faint}; font-size:13px;"
            )
            mark.setFixedWidth(18)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(pr.label.upper())
            name.setObjectName("PanelTitle")
            text.addWidget(name)
            if pr.detail:
                detail = QLabel(pr.detail)
                detail.setObjectName("Mono")
                text.addWidget(detail)
            streak = QLabel(f"{pr.streak}d streak" if pr.tracked else "untracked")
            streak.setObjectName("Mono")
            rl.addWidget(mark)
            rl.addLayout(text, 1)
            rl.addWidget(streak)
            prac.body.addWidget(r)
        g2.addWidget(prac, 0, 2)
        self.col.addWidget(row2)

        # Row 3: reflections feed | memento mori
        row3 = QWidget()
        g3 = QGridLayout(row3)
        g3.setContentsMargins(0, 0, 0, 0)
        g3.setHorizontalSpacing(16)
        g3.setColumnStretch(0, 3)
        g3.setColumnStretch(1, 2)

        g3.addWidget(
            _feed_panel("Reflections", "STO-REF", snap.reflections,
                        status=f"{len(snap.reflections)} NOTES"),
            0, 0,
        )

        memento = HudPanel("Memento Mori", "STO-MEM",
                           status=f"WK {snap.life_weeks_lived}")
        memento.body.addWidget(LifeWeeksGrid(snap.life_weeks_lived, snap.life_weeks_total))
        remaining = max(0, snap.life_weeks_total - snap.life_weeks_lived)
        mnote = QLabel(
            f"{snap.life_weeks_lived:,} weeks lived · {remaining:,} on the reference horizon. "
            "You could leave life right now — let that determine what you do."
        )
        mnote.setObjectName("Faint")
        mnote.setWordWrap(True)
        memento.body.addWidget(mnote)
        g3.addWidget(memento, 0, 1)
        self.col.addWidget(row3)

        # Maxim of the day
        maxim_panel = HudPanel("Maxim", "STO-MAX")
        maxim_panel.body.addWidget(MaximPlate(snap.maxim, snap.maxim_author))
        self.col.addWidget(maxim_panel)

    def _today_checkin_panel(self, snap) -> HudPanel:
        today = date.today()
        entry = next((e for e in snap.checkins if e.day == today), None)
        panel = HudPanel("Today Check-in", "STO-TDY",
                         status="LOGGED" if entry else "READY")
        virtue = QComboBox()
        virtue.addItems(["wisdom", "justice", "courage", "temperance"])
        virtue.setCurrentText(entry.virtue_focus if entry else "wisdom")
        panel.body.addWidget(QLabel("VIRTUE FOCUS"))
        panel.body.addWidget(virtue)

        control_meter = MeterBar("Attention on what is up to me", entry.control_pct if entry else 50,
                                 suffix="%", color=PALETTE.accent)
        control = QSlider(Qt.Horizontal)
        control.setRange(0, 100)
        control.setValue(entry.control_pct if entry else 50)
        control.valueChanged.connect(lambda v: control_meter.set_value(v))
        panel.body.addWidget(control_meter)
        panel.body.addWidget(control)

        checks = QWidget()
        cl = QVBoxLayout(checks)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        reflected = QCheckBox("REFLECTED")
        served = QCheckBox("SERVED SOMEONE")
        hard = QCheckBox("FACED HARD THING")
        restrained = QCheckBox("RESTRAINED IMPULSE")
        reflected.setChecked(entry.reflected if entry else False)
        served.setChecked(entry.served_others if entry else False)
        hard.setChecked(entry.faced_hard_thing if entry else False)
        restrained.setChecked(entry.restrained_impulse if entry else False)
        for box in (reflected, served, hard, restrained):
            cl.addWidget(box)
        panel.body.addWidget(checks)

        study = QSpinBox()
        study.setRange(0, 600)
        study.setSuffix(" study min")
        study.setValue(entry.study_minutes if entry else 0)
        panel.body.addWidget(study)

        reflection = QTextEdit(entry.reflection if entry else "")
        reflection.setMaximumHeight(92)
        reflection.setPlaceholderText("What did I assent to, resist, serve, or learn today?")
        panel.body.addWidget(reflection)

        save = QPushButton("SAVE CHECK-IN")
        save.setObjectName("GhostButton")
        save.clicked.connect(lambda: self._save_stoic_checkin(
            virtue.currentText(),
            control.value(),
            reflected.isChecked(),
            served.isChecked(),
            hard.isChecked(),
            restrained.isChecked(),
            study.value(),
            reflection.toPlainText(),
        ))
        panel.body.addWidget(save, 0, Qt.AlignRight)
        return panel

    def _save_stoic_checkin(
        self,
        virtue: str,
        control_pct: int,
        reflected: bool,
        served: bool,
        hard: bool,
        restrained: bool,
        study_minutes: int,
        reflection: str,
    ) -> None:
        upsert_today_entry(
            self._user_id,
            virtue_focus=virtue,
            control_pct=control_pct,
            reflected=reflected,
            served_others=served,
            faced_hard_thing=hard,
            restrained_impulse=restrained,
            study_minutes=study_minutes,
            reflection=reflection,
        )
        self.refresh()

    def _virtue_derivation_panel(self, virtues: list) -> HudPanel:
        """Per-virtue: score, coverage bar, and the factor chain that produced it."""
        panel = HudPanel("Virtue Derivation", "STO-VBD",
                         status=f"{sum(v.has_data for v in virtues)}/4 MEASURED")
        for v in virtues:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 4, 0, 4)
            bl.setSpacing(2)

            head = QHBoxLayout()
            head.setSpacing(8)
            name = QLabel(f"{v.name.upper()} · {v.greek}")
            name.setObjectName("PanelTitle")
            head.addWidget(name)
            head.addStretch(1)
            score = QLabel(v.display if v.has_data else "NO DATA")
            score.setStyleSheet(
                f"color:{PALETTE.text if v.has_data else PALETTE.text_faint};"
                f" font-size:{TYPE.h2}px; font-weight:700;"
            )
            head.addWidget(score)
            cov = QLabel(f"{v.coverage * 100:.0f}% data")
            cov.setObjectName("Mono")
            head.addWidget(cov)
            bl.addLayout(head)

            for f in v.factors:
                bl.addWidget(_factor_row(f))

            note = QLabel(v.note)
            note.setObjectName("Faint")
            note.setWordWrap(True)
            bl.addWidget(note)
            panel.body.addWidget(block)
        return panel


# --------------------------------------------------------------------------- #
# Custom training-card editor
# --------------------------------------------------------------------------- #
class CustomCardDialog(QDialog):
    """Create or edit a custom palette card (name, colour, load, goal)."""

    # A small palette of training-cost colours to choose from.
    _COLORS: tuple[tuple[str, str], ...] = (
        ("Base (green)", "#3ad6a0"),
        ("Strength (cyan)", "#2ee6ff"),
        ("Strength (violet)", "#a06bff"),
        ("High output (orange)", "#ff9d3d"),
        ("Aerobic stress (coral)", "#ff6b8a"),
        ("Max (yellow)", "#ffd166"),
        ("Mixed (blue)", "#6c8cff"),
        ("Recovery (grey)", "#7fa3b0"),
    )
    _INTENSITIES = ("LOW", "MOD", "MOD+", "HIGH", "MAX", "OFF")

    def __init__(self, parent=None, definition: fitness.SessionDefinition | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Card" if definition else "New Card")
        self.setMinimumWidth(360)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        def _field(label: str, widget) -> None:
            cap = QLabel(label)
            cap.setObjectName("CardLabel")
            lay.addWidget(cap)
            lay.addWidget(widget)

        self._title = QLineEdit(definition.title if definition else "")
        self._title.setPlaceholderText("e.g. Tempo Run")
        _field("NAME", self._title)

        # Category drives the strength/cardio breakdown.
        self._category = QComboBox()
        for cat in fitness.CATEGORIES:
            self._category.addItem(fitness.CATEGORY_LABELS[cat], cat)
        if definition:
            cidx = self._category.findData(definition.category)
            if cidx >= 0:
                self._category.setCurrentIndex(cidx)
        _field("CATEGORY", self._category)

        self._color = QComboBox()
        for name, value in self._COLORS:
            self._color.addItem(name, value)
        if definition:
            idx = self._color.findData(definition.color)
            if idx >= 0:
                self._color.setCurrentIndex(idx)
        _field("COLOUR", self._color)

        self._intensity = QComboBox()
        self._intensity.addItems(self._INTENSITIES)
        if definition and definition.intensity in self._INTENSITIES:
            self._intensity.setCurrentText(definition.intensity)
        else:
            self._intensity.setCurrentText("MOD")
        _field("INTENSITY", self._intensity)

        self._duration = QSpinBox()
        self._duration.setRange(0, 600)
        self._duration.setSuffix(" min")
        self._duration.setValue(definition.duration_min if definition else 45)
        _field("DURATION", self._duration)

        self._recovery = QSpinBox()
        self._recovery.setRange(0, 5)
        self._recovery.setValue(definition.recovery_cost if definition else 3)
        _field("RECOVERY COST (0–5)", self._recovery)

        self._goal = QLineEdit(definition.goal if definition else "")
        self._goal.setPlaceholderText("What this stimulus is for")
        _field("GOAL", self._goal)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {
            "title": self._title.text(),
            "category": self._category.currentData(),
            "color": self._color.currentData(),
            "intensity": self._intensity.currentText(),
            "duration_min": self._duration.value(),
            "recovery_cost": self._recovery.value(),
            "goal": self._goal.text(),
        }


# --------------------------------------------------------------------------- #
# Training-plan editor
# --------------------------------------------------------------------------- #
class PlanDialog(QDialog):
    """Create a new training block with a purpose, focus and timeline."""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QSpinBox

        super().__init__(parent)
        self.setWindowTitle("New Training Plan")
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        def _field(label: str, widget) -> None:
            cap = QLabel(label)
            cap.setObjectName("CardLabel")
            lay.addWidget(cap)
            lay.addWidget(widget)

        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. Strength Base — Block 2")
        _field("BLOCK NAME", self._name)

        self._purpose = QLineEdit()
        self._purpose.setPlaceholderText("e.g. Build lower-body strength")
        _field("PURPOSE", self._purpose)

        self._focus = QComboBox()
        for f in fitness.PLAN_FOCUSES:
            self._focus.addItem(fitness.PLAN_FOCUS_LABELS[f], f)
        self._focus.setCurrentIndex(self._focus.findData("hybrid"))
        _field("FOCUS", self._focus)

        self._goal = QLineEdit()
        self._goal.setPlaceholderText("A measurable target for this block")
        _field("GOAL / TARGET", self._goal)

        self._start = QLineEdit(
            (date.today() - timedelta(days=date.today().weekday())).isoformat()
        )
        _field("START (YYYY-MM-DD)", self._start)

        self._weeks = QSpinBox()
        self._weeks.setRange(1, 52)
        self._weeks.setValue(6)
        _field("WEEKS", self._weeks)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        start = None
        try:
            start = date.fromisoformat(self._start.text().strip())
        except ValueError:
            start = None
        return {
            "block_name": self._name.text() or "Training Block",
            "purpose": self._purpose.text(),
            "focus": self._focus.currentData(),
            "goal": self._goal.text(),
            "start_date": start,
            "weeks": self._weeks.value(),
            "activate": True,
        }


class RouteDialog(QDialog):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create route")
        self._workouts = routes.list_workouts(user_id, limit=80)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel("CREATE ROUTE")
        title.setObjectName("PanelTitle")
        lay.addWidget(title)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Route name")
        lay.addWidget(self._name)

        self._sport = QComboBox()
        for sport in routes.SPORT_TYPES:
            self._sport.addItem(sport.title(), sport)
        lay.addWidget(self._sport)

        self._description = QTextEdit()
        self._description.setPlaceholderText("Description")
        self._description.setFixedHeight(72)
        lay.addWidget(self._description)

        self._template = QComboBox()
        self._template.addItem("No template workout", None)
        for workout in self._workouts:
            dist = f"{(workout.distance_meters or 0) / 1000:.2f}km" if workout.distance_meters else "no distance"
            self._template.addItem(
                f"{workout.started_at:%d %b %Y} · {workout.title} · {dist}",
                workout.id,
            )
        lay.addWidget(self._template)

        note = QLabel("If the template workout has GPS, ORION copies its route geometry and creates the first attempt.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {
            "name": self._name.text().strip(),
            "sport_type": self._sport.currentData(),
            "description": self._description.toPlainText().strip(),
            "template_workout_id": self._template.currentData(),
        }


class SegmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create route segment")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel("CREATE SEGMENT")
        title.setObjectName("PanelTitle")
        lay.addWidget(title)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Segment name")
        lay.addWidget(self._name)
        row = QHBoxLayout()
        self._start = QSpinBox()
        self._start.setRange(0, 100000)
        self._start.setSuffix(" m start")
        self._end = QSpinBox()
        self._end.setRange(0, 100000)
        self._end.setSuffix(" m end")
        row.addWidget(self._start)
        row.addWidget(self._end)
        lay.addLayout(row)
        self._description = QLineEdit()
        self._description.setPlaceholderText("Optional description")
        lay.addWidget(self._description)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {
            "name": self._name.text().strip(),
            "start_m": self._start.value(),
            "end_m": self._end.value(),
            "description": self._description.text().strip(),
        }


class WorkoutLogDialog(QDialog):
    """Fast manual workout logger for strength/cardio sessions."""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QDoubleSpinBox

        super().__init__(parent)
        self.setWindowTitle("Log workout")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(9)

        title = QLabel("LOG WORKOUT")
        title.setObjectName("PanelTitle")
        lay.addWidget(title)

        self._title = QLineEdit()
        self._title.setPlaceholderText("e.g. Upper Strength")
        lay.addWidget(self._title)

        row = QHBoxLayout()
        self._category = QComboBox()
        for category in personal_os.WORKOUT_CATEGORIES:
            self._category.addItem(category.title(), category)
        self._duration = QSpinBox()
        self._duration.setRange(0, 300)
        self._duration.setValue(45)
        self._duration.setSuffix(" min")
        self._rpe = QDoubleSpinBox()
        self._rpe.setRange(0.0, 10.0)
        self._rpe.setSingleStep(0.5)
        self._rpe.setValue(7.0)
        row.addWidget(self._category)
        row.addWidget(self._duration)
        row.addWidget(self._rpe)
        lay.addLayout(row)

        hint = QLabel(
            "One exercise per line. Examples: Bench press 3x5 60kg RPE 8, Squat 5x3 @ 90."
        )
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._sets = QTextEdit()
        self._sets.setMinimumHeight(150)
        self._sets.setPlaceholderText("Bench press 3x5 60kg RPE 8\nRow 3x8 45kg\nPlank 3x45")
        lay.addWidget(self._sets)

        self._notes = QTextEdit()
        self._notes.setMaximumHeight(76)
        self._notes.setPlaceholderText("Notes, constraints, or progression target")
        lay.addWidget(self._notes)

        self._complete = QCheckBox("Mark complete")
        self._complete.setChecked(True)
        lay.addWidget(self._complete)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {
            "title": self._title.text().strip() or self._category.currentText(),
            "category": self._category.currentData(),
            "duration_minutes": self._duration.value() or None,
            "rpe": self._rpe.value() or None,
            "exercises_text": self._sets.toPlainText(),
            "notes": self._notes.toPlainText(),
            "completed": self._complete.isChecked(),
        }


# --------------------------------------------------------------------------- #
# Fitness page — practical 3-week training block planner
# --------------------------------------------------------------------------- #
class FitnessPage(_ScrollPage):
    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._selected_day = date.today()
        self._selected_route_id: int | None = None
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        if self._user_id is None:
            self.add_placeholder_note("No data yet. Run the seeder: python -m app.db.seed")
            return

        plan = fitness.get_or_create_plan(self._user_id)
        subtitle = f"{plan.block_name.upper()} · {plan.focus_label.upper()} FOCUS"
        if plan.purpose:
            subtitle += f" · {plan.purpose.upper()}"
        self.col.addWidget(
            SystemHeader(
                "Training", _nav_code("fitness"),
                subtitle=subtitle,
                sync_label=plan.week_label, database_label="PLAN LOCAL",
            )
        )

        self.col.addWidget(self._workout_tracker_panel())

        # Today card lives in a swappable host so a drop can refresh it in
        # place without rebuilding the whole page (which reshapes the calendar).
        self._today_host = QWidget()
        self._today_host_lay = QVBoxLayout(self._today_host)
        self._today_host_lay.setContentsMargins(0, 0, 0, 0)
        self._today_host_lay.addWidget(self._today_card())
        self.col.addWidget(self._today_host)

        top = QWidget()
        tg = QGridLayout(top)
        tg.setContentsMargins(0, 0, 0, 0)
        tg.setHorizontalSpacing(16)
        tg.setVerticalSpacing(16)
        tg.setColumnStretch(0, 4)
        tg.setColumnStretch(1, 4)
        tg.setColumnStretch(2, 3)
        tg.addWidget(self._run_plan_command_panel(), 0, 0)
        tg.addWidget(self._fitness_status_panel(), 0, 1)
        tg.addWidget(self._body_state_panel(), 0, 2)
        tg.addWidget(self._block_panel(plan), 1, 0, 1, 2)
        tg.addWidget(self._breakdown_panel(plan), 1, 2)
        self.col.addWidget(top)

        self.col.addWidget(self._routes_section())

        # Palette + three-week planner + selected day details.
        body = QWidget()
        hl = QHBoxLayout(body)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        # Palette in a swappable host so adding a custom card refreshes only it.
        self._palette_host = QWidget()
        self._palette_host_lay = QVBoxLayout(self._palette_host)
        self._palette_host_lay.setContentsMargins(0, 0, 0, 0)
        self._palette_host_lay.addWidget(self._palette_panel())
        hl.addWidget(self._palette_host, 0)

        planner_panel = HudPanel("Training Planner", "FIT-PLAN", status="3 WEEK BLOCK")
        self._planner = TrainingBlockPlanner(self._user_id, self._selected_day)
        self._planner.changed.connect(self._on_planner_changed)
        self._planner.day_selected.connect(self._select_day)
        planner_panel.body.addWidget(self._planner, 0, Qt.AlignTop)
        hl.addWidget(planner_panel, 1)

        # Selected-day details in a swappable host (same reasoning as above).
        self._day_host = QWidget()
        self._day_host_lay = QVBoxLayout(self._day_host)
        self._day_host_lay.setContentsMargins(0, 0, 0, 0)
        self._day_host_lay.addWidget(self._selected_day_panel())
        hl.addWidget(self._day_host, 0)
        self.col.addWidget(body)

    @staticmethod
    def _swap_host(host_layout, widget) -> None:
        """Replace the single child of a host layout in place."""
        while host_layout.count():
            it = host_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        host_layout.addWidget(widget)

    def _refresh_side_panels(self) -> None:
        """Update the lightweight panels without rebuilding the calendar."""
        self._swap_host(self._today_host_lay, self._today_card())
        self._swap_host(self._day_host_lay, self._selected_day_panel())

    def _on_planner_changed(self) -> None:
        # The calendar already updated the affected cells in place; just refresh
        # the side summaries so they stay in sync. The grid keeps its shape.
        self._refresh_side_panels()

    def _select_day(self, day: date) -> None:
        self._selected_day = day
        self._refresh_side_panels()

    def _sessions_for(self, day: date) -> list[fitness.SessionItem]:
        return fitness.sessions_for_day(self._user_id, day)

    def _workout_tracker_panel(self) -> HudPanel:
        snap = personal_os.get_workout_tracker_snapshot(self._user_id, days=7)
        panel = HudPanel("Workout Tracker", "TRN-LOG", status=f"{snap.weekly_sessions} THIS WEEK")
        actions = QHBoxLayout()
        log_btn = QPushButton("Start Workout")
        log_btn.setObjectName("PrimaryButton")
        log_btn.clicked.connect(self._open_workout_log_dialog)
        repeat = QPushButton("Repeat Last Workout")
        repeat.setObjectName("GhostButton")
        repeat.setEnabled(bool(snap.recent_sessions))
        repeat.clicked.connect(self._repeat_last_workout)
        actions.addWidget(log_btn)
        actions.addWidget(repeat)
        actions.addStretch(1)
        panel.body.addLayout(actions)

        vitals = QWidget()
        grid = QGridLayout(vitals)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._mini_readout("Weekly Volume", f"{snap.weekly_volume:,.0f} kg", PALETTE.accent), 0, 0)
        grid.addWidget(self._mini_readout("Sessions", str(snap.weekly_sessions), PALETTE.positive if snap.weekly_sessions else PALETTE.text_faint), 0, 1)
        grid.addWidget(self._mini_readout("Progression", snap.progression_insight, PALETTE.orange), 0, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        panel.body.addWidget(vitals)

        body = QWidget()
        body_grid = QGridLayout(body)
        body_grid.setContentsMargins(0, 0, 0, 0)
        body_grid.setHorizontalSpacing(16)
        body_grid.setVerticalSpacing(12)
        body_grid.addWidget(self._recent_workouts_panel(snap), 0, 0)
        body_grid.addWidget(self._workout_progress_panel(snap), 0, 1)
        body_grid.setColumnStretch(0, 3)
        body_grid.setColumnStretch(1, 2)
        panel.body.addWidget(body)
        return panel

    def _recent_workouts_panel(self, snap: personal_os.WorkoutTrackerSnapshot) -> HudPanel:
        panel = HudPanel("Recent Sessions", "TRN-REC", status=str(len(snap.recent_sessions)))
        if not snap.recent_sessions:
            empty = QLabel("No workout logs yet. Start with a simple session: category, exercises, sets, RPE.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel
        for session in snap.recent_sessions[:5]:
            panel.body.addWidget(self._workout_row(session))
        return panel

    def _workout_row(self, session: personal_os.WorkoutLogReadout) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        status = QLabel("✓" if session.completed else "□")
        status.setStyleSheet(
            f"color:{PALETTE.positive if session.completed else PALETTE.text_faint}; font-size:16px;"
        )
        lay.addWidget(status)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(f"{session.title}  ·  {session.category.upper()}")
        title.setObjectName("PanelTitle")
        meta = QLabel(
            f"{session.day:%d %b}  ·  {session.set_count} SETS  ·  "
            f"{session.volume:,.0f} KG VOLUME"
            + (f"  ·  RPE {session.rpe:g}" if session.rpe else "")
        )
        meta.setObjectName("Mono")
        text.addWidget(title)
        text.addWidget(meta)
        if session.notes:
            note = QLabel(session.notes)
            note.setObjectName("Faint")
            note.setWordWrap(True)
            text.addWidget(note)
        lay.addLayout(text, 1)
        complete = QPushButton("Undo" if session.completed else "Complete")
        complete.setObjectName("GhostButton")
        complete.clicked.connect(
            lambda _=False, sid=session.id, done=session.completed:
                self._toggle_workout_log(sid, not done)
        )
        lay.addWidget(complete)
        return row

    def _workout_progress_panel(self, snap: personal_os.WorkoutTrackerSnapshot) -> HudPanel:
        panel = HudPanel("Progression", "TRN-PRG", status="LOCAL")
        panel.body.addWidget(_mini_heading("Personal bests"))
        if not snap.personal_bests:
            none = QLabel("PBs appear once weighted sets are logged.")
            none.setObjectName("Faint")
            panel.body.addWidget(none)
        for item in snap.personal_bests[:6]:
            label = QLabel(item)
            label.setObjectName("Muted")
            panel.body.addWidget(label)
        panel.body.addWidget(Divider())
        panel.body.addWidget(_mini_heading("Exercise history"))
        if not snap.exercise_history:
            none = QLabel("Exercise history appears after the first completed log.")
            none.setObjectName("Faint")
            panel.body.addWidget(none)
        for item in snap.exercise_history[:6]:
            label = QLabel(item)
            label.setObjectName("Faint")
            label.setWordWrap(True)
            panel.body.addWidget(label)
        return panel

    def _open_workout_log_dialog(self) -> None:
        dlg = WorkoutLogDialog(self)
        if dlg.exec():
            personal_os.log_workout_session(self._user_id, **dlg.values())
            self.refresh()

    def _repeat_last_workout(self) -> None:
        personal_os.repeat_last_workout(self._user_id)
        self.refresh()

    def _toggle_workout_log(self, session_id: int, completed: bool) -> None:
        personal_os.mark_workout_complete(session_id, completed)
        self.refresh()

    def _routes_section(self) -> QWidget:
        route_list = routes.list_routes(self._user_id)
        if self._selected_route_id is None and route_list:
            self._selected_route_id = route_list[0].id
        if self._selected_route_id is not None and all(r.id != self._selected_route_id for r in route_list):
            self._selected_route_id = route_list[0].id if route_list else None

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 5)
        grid.addWidget(self._routes_index_panel(route_list), 0, 0)
        grid.addWidget(self._route_dashboard_panel(), 0, 1)
        grid.addWidget(self._workout_route_tagging_panel(route_list), 1, 0, 1, 2)
        return host

    def _routes_index_panel(self, route_list: list[routes.RouteReadout]) -> HudPanel:
        panel = HudPanel("Routes", "FIT-RTE", status=f"{len(route_list)} SAVED")
        top = QHBoxLayout()
        create = QPushButton("+ Create Route")
        create.setObjectName("PrimaryButton")
        create.clicked.connect(lambda _=False: self._create_route())
        top.addWidget(create)
        top.addStretch(1)
        panel.body.addLayout(top)
        if not route_list:
            empty = QLabel("No saved routes yet. Create one manually, or create one from a completed workout once workout imports are present.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel
        for route in route_list[:8]:
            card = QWidget()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(0, 4, 0, 8)
            lay.setSpacing(5)
            head = QHBoxLayout()
            name = QLabel(route.name.upper())
            name.setObjectName("PanelTitle")
            head.addWidget(name, 1)
            select = QPushButton("View")
            select.setObjectName("GhostButton")
            select.clicked.connect(lambda _=False, rid=route.id: self._select_route(rid))
            head.addWidget(select)
            lay.addLayout(head)
            stats = route.stats
            meta = QLabel(
                f"{route.sport_type.upper()}  ·  {_distance_label(route.distance_meters)}  ·  "
                f"{stats.attempts} ATTEMPTS  ·  BEST {routes.format_duration(stats.best_time_seconds)}"
            )
            meta.setObjectName("Mono")
            meta.setWordWrap(True)
            lay.addWidget(meta)
            latest = QLabel(
                f"LATEST {routes.format_duration(stats.latest_time_seconds)}  ·  AVG PACE "
                f"{routes.format_pace(stats.fastest_pace_seconds_per_km)}"
            )
            latest.setObjectName("Faint")
            latest.setWordWrap(True)
            lay.addWidget(latest)
            if route.route_geometry:
                preview = RouteMap(route_geometry=route.route_geometry, show_distance_markers=False)
                preview.setFixedHeight(116)
                lay.addWidget(preview)
            panel.body.addWidget(card)
        return panel

    def _route_dashboard_panel(self) -> HudPanel:
        if self._selected_route_id is None:
            panel = HudPanel("Route Dashboard", "FIT-RDB", status="NO ROUTE")
            empty = QLabel("Create or select a route to open route intelligence.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel
        dashboard = routes.get_route_dashboard(self._user_id, self._selected_route_id)
        if dashboard is None:
            self._selected_route_id = None
            return self._route_dashboard_panel()

        route = dashboard.route
        stats = route.stats
        panel = HudPanel(route.name, "FIT-RDB", status=f"{stats.attempts} ATTEMPTS")
        header = QLabel(
            f"{route.sport_type.upper()}  ·  {_distance_label(route.distance_meters)}  ·  "
            f"ELEV {_meters_label(route.elevation_gain_meters)}"
        )
        header.setObjectName("Mono")
        header.setWordWrap(True)
        panel.body.addWidget(header)

        metrics = QWidget()
        grid = QGridLayout(metrics)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        cells = [
            ("Best", routes.format_duration(stats.best_time_seconds), PALETTE.positive),
            ("Latest", routes.format_duration(stats.latest_time_seconds), PALETTE.accent),
            ("Average", routes.format_duration(stats.average_time_seconds), PALETTE.text),
            ("Fastest Pace", routes.format_pace(stats.fastest_pace_seconds_per_km), PALETTE.orange),
            ("Lowest HR", f"{stats.lowest_average_heart_rate:.0f} bpm" if stats.lowest_average_heart_rate else "—", PALETTE.violet),
            ("Latest vs PB", _signed_duration(stats.latest_vs_pb_seconds), PALETTE.coral if (stats.latest_vs_pb_seconds or 0) > 0 else PALETTE.positive),
        ]
        for idx, (label, value, color) in enumerate(cells):
            grid.addWidget(self._mini_readout(label, value, color), idx // 3, idx % 3)
        panel.body.addWidget(metrics)

        panel.body.addWidget(
            RouteMap(
                route_geometry=route.route_geometry,
                attempt_geometry=dashboard.latest_attempt.route_geometry if dashboard.latest_attempt else None,
                comparison_geometry=dashboard.best_attempt.route_geometry if dashboard.best_attempt else None,
                segments=dashboard.segments,
            )
        )

        if dashboard.best_attempt and dashboard.latest_attempt:
            delta = routes.calculate_attempt_delta(dashboard.latest_attempt, dashboard.best_attempt)
            compare = QLabel(
                f"LATEST VS PB  ·  TIME {_signed_duration(delta['time'])}  ·  "
                f"PACE {_signed_pace(delta['pace'])}  ·  AVG HR {_signed_number(delta['avg_hr'], ' bpm')}"
            )
            compare.setObjectName("Mono")
            compare.setWordWrap(True)
            panel.body.addWidget(compare)

        panel.body.addWidget(self._route_attempts_table(dashboard.attempts))
        panel.body.addWidget(self._segments_panel(dashboard))
        panel.body.addWidget(self._route_insights_panel(dashboard.insights))
        actions = QHBoxLayout()
        seg = QPushButton("+ Segment")
        seg.setObjectName("GhostButton")
        seg.clicked.connect(lambda _=False, rid=route.id: self._create_segment(rid))
        delete = QPushButton("Delete Route")
        delete.setObjectName("GhostButton")
        delete.clicked.connect(lambda _=False, rid=route.id: self._delete_route(rid))
        actions.addWidget(seg)
        actions.addWidget(delete)
        actions.addStretch(1)
        panel.body.addLayout(actions)
        return panel

    def _route_attempts_table(self, attempts: list[routes.RouteAttemptReadout]) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        title = QLabel("ATTEMPTS")
        title.setObjectName("ModuleCode")
        lay.addWidget(title)
        if not attempts:
            empty = QLabel("No attempts yet. Assign a workout to this route to start comparison.")
            empty.setObjectName("Faint")
            lay.addWidget(empty)
            return host
        for attempt in attempts[:8]:
            row = QHBoxLayout()
            row.setSpacing(8)
            values = [
                attempt.attempt_date.strftime("%d %b %Y").upper(),
                routes.format_duration(attempt.duration_seconds),
                _distance_label(attempt.distance_meters),
                routes.format_pace(attempt.average_pace_seconds_per_km),
                f"{attempt.average_heart_rate:.0f}" if attempt.average_heart_rate else "—",
                f"{attempt.route_match_confidence:.0f}%" if attempt.route_match_confidence is not None else "—",
            ]
            widths = [92, 58, 64, 74, 42, 48]
            for value, width in zip(values, widths):
                label = QLabel(value)
                label.setObjectName("Mono")
                label.setFixedWidth(width)
                row.addWidget(label)
            row.addStretch(1)
            lay.addLayout(row)
        return host

    def _segments_panel(self, dashboard: routes.RouteDashboard) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        title = QLabel("SEGMENTS")
        title.setObjectName("ModuleCode")
        lay.addWidget(title)
        if not dashboard.segments:
            empty = QLabel("No segments yet. Add ranges like final kilometre or first climb.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            lay.addWidget(empty)
            return host
        for seg in dashboard.segments:
            label = QLabel(
                f"{seg.name.upper()}  ·  {seg.start_distance_meters / 1000:.2f}–{seg.end_distance_meters / 1000:.2f} KM"
            )
            label.setObjectName("Mono")
            lay.addWidget(label)
        return host

    def _route_insights_panel(self, insights: list[str]) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        title = QLabel("INSIGHTS")
        title.setObjectName("ModuleCode")
        lay.addWidget(title)
        for insight in insights:
            text = QLabel(insight)
            text.setObjectName("Faint")
            text.setWordWrap(True)
            lay.addWidget(text)
        return host

    def _workout_route_tagging_panel(self, route_list: list[routes.RouteReadout]) -> HudPanel:
        workouts = routes.list_workouts(self._user_id, limit=8)
        panel = HudPanel("Workout Route Tagging", "FIT-TAG", status=f"{len(workouts)} WORKOUTS")
        if not workouts:
            empty = QLabel(
                "No completed workouts are stored yet. Future Apple Health / Health Auto Export workout imports can hydrate this table; route creation still works manually."
            )
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel
        for workout in workouts:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(0)
            title = QLabel(workout.title.upper())
            title.setObjectName("PanelTitle")
            meta = QLabel(
                f"{workout.started_at:%d %b %Y}  ·  {workout.sport_type.upper()}  ·  "
                f"{_distance_label(workout.distance_meters)}  ·  {routes.format_duration(workout.duration_seconds)}"
            )
            meta.setObjectName("Mono")
            text.addWidget(title)
            text.addWidget(meta)
            suggestions = routes.possible_route_matches(self._user_id, workout.id)
            if suggestions:
                sug = QLabel("POSSIBLE MATCHES  ·  " + "  ·  ".join(f"{s.route_name} {s.confidence:.0f}%" for s in suggestions[:3]))
                sug.setObjectName("Faint")
                sug.setWordWrap(True)
                text.addWidget(sug)
            lay.addLayout(text, 1)
            if route_list:
                assign = QPushButton("Assign")
                assign.setObjectName("GhostButton")
                assign.clicked.connect(lambda _=False, wid=workout.id: self._assign_workout_dialog(wid))
                lay.addWidget(assign)
            create = QPushButton("New Route")
            create.setObjectName("GhostButton")
            create.clicked.connect(lambda _=False, wid=workout.id: self._create_route(template_workout_id=wid))
            lay.addWidget(create)
            panel.body.addWidget(row)
        return panel

    def _select_route(self, route_id: int) -> None:
        self._selected_route_id = route_id
        self.refresh()

    def _create_route(self, template_workout_id: int | None = None) -> None:
        dlg = RouteDialog(self._user_id, self)
        if template_workout_id is not None:
            idx = dlg._template.findData(template_workout_id)
            if idx >= 0:
                dlg._template.setCurrentIndex(idx)
        if dlg.exec():
            data = dlg.values()
            self._selected_route_id = routes.create_route(self._user_id, **data)
            self.refresh()

    def _delete_route(self, route_id: int) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(self, "Delete route", "Delete this route and its attempts?") != QMessageBox.Yes:
            return
        routes.delete_route(self._user_id, route_id)
        self._selected_route_id = None
        self.refresh()

    def _create_segment(self, route_id: int) -> None:
        dlg = SegmentDialog(self)
        if dlg.exec():
            routes.create_segment(route_id, **dlg.values())
            self.refresh()

    def _assign_workout_dialog(self, workout_id: int) -> None:
        from PySide6.QtWidgets import QInputDialog

        route_list = routes.list_routes(self._user_id)
        if not route_list:
            return
        labels = [f"{r.name} · {_distance_label(r.distance_meters)}" for r in route_list]
        label, ok = QInputDialog.getItem(self, "Assign route", "Route", labels, 0, False)
        if not ok:
            return
        route = route_list[labels.index(label)]
        routes.assign_workout_to_route(self._user_id, workout_id, route.id)
        self._selected_route_id = route.id
        self.refresh()

    def _today_card(self) -> HudPanel:
        sessions = self._sessions_for(date.today())
        primary = sessions[0] if sessions else None
        status = "COMPLETE" if primary and primary.completed else "READY" if primary else "UNPLANNED"
        panel = HudPanel("Today", "FIT-TDY", status=status)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(4)
        date_label = QLabel(date.today().strftime("%A %d %B").upper())
        date_label.setObjectName("Mono")
        title = QLabel(primary.title if primary else "No session planned")
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:26px; font-weight:750;")
        title.setWordWrap(True)
        goal = QLabel(primary.definition.goal if primary else "Drop a session into today to set the plan.")
        goal.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.small}px;")
        goal.setWordWrap(True)
        left.addWidget(date_label)
        left.addWidget(title)
        left.addWidget(goal)
        rl.addLayout(left, 1)

        meta = QHBoxLayout()
        meta.setSpacing(10)
        if primary:
            for label, value, color in (
                ("DURATION", primary.duration_label, PALETTE.accent),
                ("INTENSITY", primary.definition.intensity, primary.color),
                (
                    "RECOVERY",
                    primary.recovery_label,
                    PALETTE.orange if primary.definition.recovery_cost >= 4 else PALETTE.text_dim,
                ),
                (
                    "STATUS",
                    "DONE" if primary.completed else "PLANNED",
                    PALETTE.positive if primary.completed else PALETTE.accent,
                ),
            ):
                meta.addWidget(self._mini_readout(label, value, color))
        else:
            meta.addWidget(self._mini_readout("STATE", "NO SESSION", PALETTE.text_faint))
            meta.addWidget(self._mini_readout("ACTION", "PLAN TODAY", PALETTE.accent))
        rl.addLayout(meta, 1)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        start = QPushButton("Start Session")
        swap = QPushButton("Swap")
        complete = QPushButton("Mark Complete" if not (primary and primary.completed) else "Completed")
        for button in (start, swap, complete):
            button.setObjectName("GhostButton")
            button.setMinimumWidth(132)
            actions.addWidget(button)
        if primary:
            start.clicked.connect(lambda _=False, sid=primary.id: self._start_session(sid))
            swap.clicked.connect(lambda _=False, sid=primary.id: self._swap_session(sid))
            complete.clicked.connect(lambda _=False, sid=primary.id: self._complete_session(sid))
            complete.setEnabled(not primary.completed)
        else:
            start.setEnabled(False)
            swap.setEnabled(False)
            complete.setEnabled(False)
        rl.addLayout(actions)
        panel.body.addWidget(row)
        return panel

    def _mini_readout(self, label: str, value: str, color: str) -> QWidget:
        cell = QWidget()
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        label_widget = QLabel(label)
        label_widget.setObjectName("CardLabel")
        v = QLabel(value)
        v.setStyleSheet(
            f"color:{color}; font-family:{TYPE.mono}; font-size:{TYPE.h2}px;"
            " font-weight:700;"
        )
        lay.addWidget(label_widget)
        lay.addWidget(v)
        return cell

    def _run_plan_command_panel(self) -> HudPanel:
        recovery = personal_os.get_recovery_snapshot(self._user_id)
        plan = personal_os.get_run_plan_snapshot(self._user_id, recovery)
        panel = HudPanel("Run Command", "RUN-02", status=plan.adherence_label.upper())

        title = QLabel(plan.next_run.title)
        title.setStyleSheet(f"color:{PALETTE.text}; font-size:24px; font-weight:760;")
        title.setWordWrap(True)
        panel.body.addWidget(title)

        detail = QLabel(plan.next_run.detail)
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        panel.body.addWidget(detail)

        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.addWidget(
            self._mini_readout(
                "Week",
                f"{plan.week_distance_km:g}/{plan.weekly_target_km:g} km",
                PALETTE.orange if plan.adherence_label == "behind plan" else PALETTE.accent,
            ),
            0,
            0,
        )
        grid.addWidget(
            self._mini_readout("Next", plan.next_run.session_type, PALETTE.positive),
            0,
            1,
        )
        grid.addWidget(
            self._mini_readout("Recovery", recovery.label, PALETTE.violet),
            0,
            2,
        )
        panel.body.addWidget(row)

        guardrail = QLabel(plan.guardrail)
        guardrail.setObjectName("Faint")
        guardrail.setWordWrap(True)
        panel.body.addWidget(guardrail)
        return panel

    def _fitness_status_panel(self) -> HudPanel:
        fr = fitness.fitness_frame(self._user_id)
        dist = fr["distance_km"].dropna() if not fr.empty else []
        vo2 = fr["vo2max"].dropna() if not fr.empty else []
        dist7 = float(dist.tail(7).sum()) if len(dist) else 0.0
        dist30 = float(dist.sum()) if len(dist) else 0.0
        runs = int((fr["distance_km"].fillna(0) > 0).sum()) if not fr.empty else 0

        panel = HudPanel("Fitness Status", "FIT-AH", status=self._status_summary(dist7, vo2))
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        hl.addWidget(
            self._status_cell(
                "Distance",
                f"{dist7:.1f} km",
                self._distance_label(dist7),
                f"30d total {dist30:.1f} km",
                PALETTE.orange if dist7 >= 35 else PALETTE.positive if dist7 >= 20 else PALETTE.text_dim,
                dist.tolist() if len(dist) else [],
            ),
            1,
        )
        hl.addWidget(
            self._status_cell(
                "VO₂ Max",
                f"{vo2.iloc[-1]:.1f}" if len(vo2) else "—",
                self._trend_label(vo2.tolist(), "trending up", "trending down"),
                "cardio fitness",
                PALETTE.positive if len(vo2) and vo2.iloc[-1] >= vo2.mean() else PALETTE.accent,
                vo2.tolist() if len(vo2) else [],
            ),
            1,
        )
        hl.addWidget(
            self._status_cell(
                "Runs",
                str(runs),
                "consistent" if runs >= 8 else "light" if runs else "sync needed",
                "last 30 days",
                PALETTE.positive if runs >= 8 else PALETTE.text_dim,
                [],
            ),
            1,
        )
        panel.body.addWidget(row)
        return panel

    def _body_state_panel(self) -> HudPanel:
        body = fitness.body_state_snapshot(self._user_id)
        panel = HudPanel("Body State", "FIT-BIO", status=body.readiness_label)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        hl.addWidget(
            self._body_metric_cell(
                body.resting_hr,
                lower_is_better=True,
                detail="Compare today with your 7-day baseline before high-output work.",
            ),
            1,
        )
        hl.addWidget(
            self._body_metric_cell(
                body.weight,
                lower_is_better=False,
                detail="Useful for load tolerance, fuelling, and longer-term body composition.",
            ),
            1,
        )
        panel.body.addWidget(row)

        note = QLabel(self._body_state_note(body))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        panel.body.addWidget(note)
        return panel

    def _breakdown_panel(self, plan) -> HudPanel:
        """Strength vs cardio (and mobility/recovery) split for the plan window."""
        bd = fitness.training_breakdown(self._user_id, plan.start_date, plan.end_date)
        strength_share, cardio_share = bd.strength_cardio_ratio
        if bd.total_sessions == 0:
            status = "NO SESSIONS"
        else:
            status = f"{bd.total_sessions} SESSIONS · {bd.total_minutes} MIN"
        panel = HudPanel("Strength / Cardio Breakdown", "FIT-MIX", status=status)

        if bd.total_sessions == 0:
            empty = QLabel(
                "Drop sessions onto the planner to see how this block splits "
                "between strength and cardio work."
            )
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            return panel

        # Headline strength-vs-cardio balance of training minutes.
        balance = QLabel(
            f"STRENGTH {strength_share * 100:.0f}%   ·   CARDIO {cardio_share * 100:.0f}%"
        )
        balance.setStyleSheet(
            f"color:{PALETTE.text}; font-family:{TYPE.mono};"
            f" font-size:{TYPE.body}px; font-weight:700;"
        )
        panel.body.addWidget(balance)
        panel.body.addWidget(
            self._split_bar(strength_share, cardio_share)
        )

        # Per-category meters by share of training minutes.
        for stat in bd.stats:
            if stat.sessions == 0:
                continue
            share = bd.minute_share(stat.category)
            readout = (
                f"{stat.sessions}× · {stat.minutes}min · {stat.completed}/{stat.sessions} done"
            )
            panel.body.addWidget(
                MeterBar(
                    f"{stat.label.upper()}",
                    share * 100.0,
                    suffix="%",
                    color=stat.color,
                    readout=readout,
                )
            )

        # Focus alignment hint: does the mix match the plan's stated focus?
        hint = self._focus_alignment_note(plan.focus, strength_share, cardio_share)
        if hint:
            note = QLabel(hint)
            note.setObjectName("Muted")
            note.setWordWrap(True)
            panel.body.addWidget(note)
        return panel

    def _split_bar(self, strength_share: float, cardio_share: float) -> QWidget:
        """A single horizontal bar split strength | cardio."""
        bar = QWidget()
        bar.setFixedHeight(12)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        s = QWidget()
        s.setStyleSheet(f"background:{fitness.CATEGORY_COLORS['strength']};")
        c = QWidget()
        c.setStyleSheet(f"background:{fitness.CATEGORY_COLORS['cardio']};")
        lay.addWidget(s, max(1, int(round(strength_share * 1000))))
        lay.addWidget(c, max(1, int(round(cardio_share * 1000))))
        return bar

    def _focus_alignment_note(self, focus: str, strength: float, cardio: float) -> str:
        if strength + cardio == 0:
            return ""
        if focus == "strength" and strength < 0.5:
            return "This block is set to a STRENGTH focus, but cardio currently dominates the minutes."
        if focus == "cardio" and cardio < 0.5:
            return "This block is set to a CARDIO focus, but strength currently dominates the minutes."
        if focus == "hybrid" and (strength > 0.75 or cardio > 0.75):
            return "Hybrid focus, but the mix is heavily skewed — add the lighter side to balance it."
        return "The training mix matches this block's focus."

    def _status_summary(self, dist7: float, vo2) -> str:
        if not len(vo2) and dist7 == 0:
            return "SYNC NEEDED"
        if dist7 >= 35:
            return "HIGH LOAD"
        return "CONSISTENT"

    def _distance_label(self, dist7: float) -> str:
        if dist7 >= 35:
            return "high load"
        if dist7 >= 20:
            return "consistent"
        if dist7 > 0:
            return "building"
        return "sync needed"

    def _trend_label(self, values: list[float], up_label: str, down_label: str) -> str:
        if len(values) < 2:
            return "sync needed"
        delta = values[-1] - values[0]
        if delta > 0.8:
            return up_label
        if delta < -0.8:
            return down_label
        return "stable"

    def _rhr_label(self, values: list[float]) -> str:
        if len(values) < 2:
            return "sync needed"
        delta = values[-1] - values[0]
        if delta <= -2:
            return "trending down"
        if delta >= 3:
            return "elevated"
        return "stable"

    def _body_metric_cell(
        self,
        metric: fitness.BodyMetric,
        *,
        lower_is_better: bool,
        detail: str,
    ) -> QWidget:
        if not metric.has_data:
            return self._status_cell(
                metric.label,
                "—",
                "sync needed",
                detail,
                PALETTE.text_faint,
                [],
            )
        value = self._format_body_value(metric)
        interpretation = self._body_delta_label(metric, lower_is_better=lower_is_better)
        color = self._body_delta_color(metric, lower_is_better=lower_is_better)
        baseline = (
            f"7d baseline {metric.baseline_7d:.1f} {metric.unit}"
            if metric.baseline_7d is not None
            else detail
        )
        return self._status_cell(
            metric.label,
            value,
            interpretation,
            baseline,
            color,
            metric.series,
        )

    def _format_body_value(self, metric: fitness.BodyMetric) -> str:
        if metric.value is None:
            return "—"
        if metric.key == "resting_hr":
            return f"{metric.value:.0f} {metric.unit}"
        return f"{metric.value:.1f} {metric.unit}"

    def _body_delta_label(self, metric: fitness.BodyMetric, *, lower_is_better: bool) -> str:
        if metric.delta_7d is None:
            return "baseline pending"
        delta = metric.delta_7d
        if abs(delta) < 0.8:
            return "on baseline"
        if lower_is_better:
            return "elevated" if delta > 0 else "below baseline"
        direction = "up" if delta > 0 else "down"
        return f"{direction} {abs(delta):.1f}"

    def _body_delta_color(self, metric: fitness.BodyMetric, *, lower_is_better: bool) -> str:
        if metric.delta_7d is None or abs(metric.delta_7d) < 0.8:
            return PALETTE.accent
        if lower_is_better:
            return PALETTE.orange if metric.delta_7d > 0 else PALETTE.positive
        return PALETTE.text_dim

    def _body_state_note(self, body: fitness.BodyStateSnapshot) -> str:
        if not body.has_data:
            return "Import Health Auto Export or Apple Health to bring resting HR and weight into fitness planning."
        if body.readiness_label == "RECOVERY WATCH":
            return "Resting HR is above baseline. Consider swapping intervals or heavy lower work for Zone 2, mobility, or rest."
        if body.readiness_label == "PRIMED":
            return "Resting HR is below baseline. If sleep and soreness agree, today can tolerate quality work."
        return "Body-state signals are steady. Use the planner normally and watch changes across the week."

    def _status_cell(
        self,
        label: str,
        value: str,
        interpretation: str,
        detail: str,
        color: str,
        series: list[float],
    ) -> QWidget:
        cell = QWidget()
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        k = QLabel(label.upper())
        k.setObjectName("CardLabel")
        v = QLabel(value)
        v.setStyleSheet(f"color:{PALETTE.text}; font-size:22px; font-weight:750;")
        tag = QLabel(interpretation.upper())
        tag.setStyleSheet(
            f"color:{color}; font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            f" border:1px solid {PALETTE.border}; padding:2px 6px;"
        )
        sub = QLabel(detail)
        sub.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;")
        sub.setWordWrap(True)
        lay.addWidget(k)
        lay.addWidget(v)
        lay.addWidget(tag, 0, Qt.AlignLeft)
        lay.addWidget(sub)
        if len(series) > 1:
            lay.addWidget(SignalLineChart(series, color=color, height=42))
        else:
            lay.addStretch(1)
        return cell

    def _block_panel(self, plan) -> HudPanel:
        from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox

        plans = fitness.list_plans(self._user_id)
        panel = HudPanel("Training Block", "FIT-BLK", status=plan.week_label)

        # Plan switcher + new-plan control.
        switch_row = QHBoxLayout()
        switch_row.setSpacing(8)
        sel = QComboBox()
        for p in plans:
            sel.addItem(f"{p.block_name}  ·  {p.focus_label}", p.id)
        idx = sel.findData(plan.id)
        if idx >= 0:
            sel.setCurrentIndex(idx)
        sel.currentIndexChanged.connect(
            lambda _=0, combo=sel: self._switch_plan(combo.currentData())
        )
        switch_row.addWidget(sel, 1)
        new_btn = QPushButton("+ New Plan")
        new_btn.setObjectName("GhostButton")
        new_btn.clicked.connect(lambda _=False: self._new_plan())
        switch_row.addWidget(new_btn)
        if len(plans) > 1:
            del_btn = QPushButton("Delete")
            del_btn.setObjectName("GhostButton")
            del_btn.clicked.connect(lambda _=False, pid=plan.id: self._delete_plan(pid))
            switch_row.addWidget(del_btn)
        panel.body.addWidget(self._wrap_row(switch_row))

        # Timeline + progress readout.
        timeline = QLabel(
            f"{plan.timeline_label}   ·   {plan.weeks} WEEKS   ·   "
            f"{plan.days_remaining}D LEFT"
        )
        timeline.setObjectName("Mono")
        timeline.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;")
        panel.body.addWidget(timeline)
        panel.body.addWidget(
            MeterBar(
                f"BLOCK PROGRESS · WEEK {plan.current_week} OF {plan.weeks}",
                plan.progress * 100.0, suffix="%", color=PALETTE.accent,
                readout=f"{plan.progress * 100:.0f}%",
            )
        )

        # Editable fields: name, purpose, focus, goal, start, weeks.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        name_edit = QLineEdit(plan.block_name)
        name_edit.editingFinished.connect(
            lambda: self._save_plan(plan.id, name=name_edit.text())
        )
        purpose_edit = QLineEdit(plan.purpose)
        purpose_edit.setPlaceholderText("e.g. Build aerobic base")
        purpose_edit.editingFinished.connect(
            lambda: self._save_plan(plan.id, purpose=purpose_edit.text())
        )
        focus_sel = QComboBox()
        for f in fitness.PLAN_FOCUSES:
            focus_sel.addItem(fitness.PLAN_FOCUS_LABELS[f], f)
        fidx = focus_sel.findData(plan.focus)
        if fidx >= 0:
            focus_sel.setCurrentIndex(fidx)
        focus_sel.currentIndexChanged.connect(
            lambda _=0, combo=focus_sel: self._save_plan(plan.id, focus=combo.currentData())
        )
        start_edit = QLineEdit(plan.start_date.isoformat())
        start_edit.setMaximumWidth(130)
        start_edit.editingFinished.connect(
            lambda: self._save_plan(plan.id, start=start_edit.text())
        )
        weeks_spin = QSpinBox()
        weeks_spin.setRange(1, 52)
        weeks_spin.setValue(plan.weeks)
        weeks_spin.valueChanged.connect(lambda v: self._save_plan(plan.id, weeks=v))

        grid.addWidget(self._field_label("BLOCK NAME"), 0, 0)
        grid.addWidget(self._field_label("FOCUS"), 0, 1)
        grid.addWidget(name_edit, 1, 0)
        grid.addWidget(focus_sel, 1, 1)
        grid.addWidget(self._field_label("PURPOSE"), 2, 0)
        grid.addWidget(self._field_label("START / WEEKS"), 2, 1)
        grid.addWidget(purpose_edit, 3, 0)
        sw = QHBoxLayout()
        sw.setSpacing(6)
        sw.addWidget(start_edit)
        sw.addWidget(weeks_spin)
        grid.addWidget(self._wrap_row(sw), 3, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        host = QWidget()
        host.setLayout(grid)
        panel.body.addWidget(host)

        goal_lbl = self._field_label("GOAL / TARGET")
        panel.body.addWidget(goal_lbl)
        goal_edit = QLineEdit(plan.goal)
        goal_edit.setPlaceholderText("A measurable target for this block")
        goal_edit.editingFinished.connect(
            lambda: self._save_plan(plan.id, goal=goal_edit.text())
        )
        panel.body.addWidget(goal_edit)
        return panel

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("CardLabel")
        return lbl

    @staticmethod
    def _wrap_row(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _switch_plan(self, plan_id) -> None:
        if plan_id is None:
            return
        fitness.activate_plan(self._user_id, plan_id)
        self.refresh()

    def _new_plan(self) -> None:
        dlg = PlanDialog(self)
        if dlg.exec():
            fitness.create_plan(self._user_id, **dlg.values())
            self.refresh()

    def _delete_plan(self, plan_id) -> None:
        fitness.delete_plan(self._user_id, plan_id)
        self.refresh()

    def _save_plan(self, plan_id: int, *, name=None, purpose=None, focus=None,
                   goal=None, start=None, weeks=None) -> None:
        from datetime import date as _date

        start_date = None
        if start:
            try:
                start_date = _date.fromisoformat(start)
            except ValueError:
                start_date = None
        fitness.update_plan(
            plan_id, block_name=name, purpose=purpose, focus=focus, goal=goal,
            start_date=start_date, weeks=weeks,
        )
        self.refresh()

    def _palette_panel(self) -> HudPanel:
        panel = HudPanel("Palette", "FIT-PAL", status="DRAG")
        panel.setMaximumWidth(278)
        panel.setMinimumWidth(250)
        hint = QLabel("Drag a stimulus onto the 3-week block. Cards are grouped by "
                      "type — strength, cardio, mobility and recovery — so each "
                      "block's mix is easy to balance.")
        hint.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.small}px;")
        hint.setWordWrap(True)
        panel.body.addWidget(hint)

        # Built-in library cards, grouped by training category.
        by_cat: dict[str, list] = {c: [] for c in fitness.CATEGORIES}
        for d in fitness.SESSION_LIBRARY:
            by_cat.setdefault(d.category, []).append(d)
        for cat in fitness.CATEGORIES:
            defs = by_cat.get(cat) or []
            if not defs:
                continue
            sep = QLabel(fitness.CATEGORY_LABELS[cat].upper())
            sep.setObjectName("CardLabel")
            sep.setStyleSheet(
                f"color:{fitness.CATEGORY_COLORS[cat]}; font-size:{TYPE.nano}px;"
                " margin-top:4px;"
            )
            panel.body.addWidget(sep)
            for d in defs:
                panel.body.addWidget(SessionTile(d.key, d.color))

        # User-created custom cards (editable / removable).
        custom = fitness.custom_cards(self._user_id)
        if custom:
            sep = QLabel("CUSTOM CARDS")
            sep.setObjectName("CardLabel")
            sep.setStyleSheet(
                f"color:{PALETTE.text_faint}; font-size:{TYPE.nano}px; margin-top:6px;"
            )
            panel.body.addWidget(sep)
            for d in custom:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(4)
                tile = SessionTile(d.key, d.color)
                rl.addWidget(tile, 1)
                edit = QPushButton("✎")
                rem = QPushButton("✕")
                for b in (edit, rem):
                    b.setObjectName("GhostButton")
                    b.setFixedWidth(28)
                edit.clicked.connect(lambda _=False, key=d.key: self._edit_custom_card(key))
                rem.clicked.connect(lambda _=False, key=d.key: self._delete_custom_card(key))
                rl.addWidget(edit)
                rl.addWidget(rem)
                panel.body.addWidget(row)

        add = QPushButton("+ New Card")
        add.setObjectName("GhostButton")
        add.clicked.connect(lambda _=False: self._new_custom_card())
        panel.body.addWidget(add)
        panel.body.addStretch(1)
        return panel

    def _refresh_palette(self) -> None:
        self._swap_host(self._palette_host_lay, self._palette_panel())

    def _new_custom_card(self) -> None:
        dlg = CustomCardDialog(self)
        if dlg.exec():
            data = dlg.values()
            fitness.create_custom_card(self._user_id, **data)
            self._refresh_palette()

    def _edit_custom_card(self, key: str) -> None:
        existing = next(
            (d for d in fitness.custom_cards(self._user_id) if d.key == key), None
        )
        if existing is None:
            return
        dlg = CustomCardDialog(self, definition=existing)
        if dlg.exec():
            fitness.update_custom_card(self._user_id, key, **dlg.values())
            self._refresh_palette()
            # Placed sessions of this type may have changed colour/label source.
            self._planner.rebuild()
            self._refresh_side_panels()

    def _delete_custom_card(self, key: str) -> None:
        fitness.delete_custom_card(self._user_id, key)
        self._refresh_palette()

    def _selected_day_panel(self) -> HudPanel:
        from PySide6.QtWidgets import QLineEdit

        sessions = self._sessions_for(self._selected_day)
        status = f"{len(sessions)} PLANNED" if sessions else "EMPTY"
        panel = HudPanel("Selected Day", "FIT-DAY", status=status)
        panel.setMinimumWidth(292)
        panel.setMaximumWidth(330)

        day = QLabel(self._selected_day.strftime("%A %d %B").upper())
        day.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.h2}px; font-weight:700;")
        panel.body.addWidget(day)

        if not sessions:
            empty = QLabel("No session planned. Drop from the palette, or mark the day as rest.")
            empty.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.small}px;")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
            rest = QPushButton("Set Rest Day")
            rest.setObjectName("GhostButton")
            rest.clicked.connect(
                lambda _=False, d=self._selected_day: self._add_session(d, "REST")
            )
            panel.body.addWidget(rest)
            panel.body.addStretch(1)
            return panel

        for item in sessions:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 7, 0, 7)
            bl.setSpacing(5)

            head = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{item.color}; font-size:9px;")
            title = QLabel(item.title)
            title.setStyleSheet(f"color:{PALETTE.text}; font-size:{TYPE.body}px; font-weight:700;")
            status_text = QLabel("DONE" if item.completed else "PLANNED")
            status_text.setStyleSheet(
                f"color:{PALETTE.positive if item.completed else PALETTE.accent_dim};"
                f" font-family:{TYPE.mono}; font-size:{TYPE.nano}px;"
            )
            head.addWidget(dot)
            head.addWidget(title, 1)
            head.addWidget(status_text)
            bl.addLayout(head)

            meta = QLabel(
                f"{item.definition.intensity} · {item.duration_label} · recovery "
                f"{item.definition.recovery_cost}/5"
            )
            meta.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.nano}px;")
            bl.addWidget(meta)
            goal = QLabel(item.definition.goal)
            goal.setStyleSheet(f"color:{PALETTE.text_dim}; font-size:{TYPE.small}px;")
            goal.setWordWrap(True)
            bl.addWidget(goal)

            rename = QLineEdit(item.label)
            rename.setPlaceholderText(f"Rename (default: {item.definition.title})")
            rename.editingFinished.connect(
                lambda sid=item.id, edit=rename: self._save_session_label(sid, edit.text())
            )
            bl.addWidget(rename)

            notes = QLineEdit(item.notes)
            notes.setPlaceholderText("Notes, constraint, or target")
            notes.editingFinished.connect(
                lambda sid=item.id, edit=notes: self._save_session_notes(sid, edit.text())
            )
            bl.addWidget(notes)

            actions = QHBoxLayout()
            start = QPushButton("Start")
            swap = QPushButton("Swap")
            complete = QPushButton("Undo" if item.completed else "Complete")
            for button in (start, swap, complete):
                button.setObjectName("GhostButton")
                actions.addWidget(button)
            start.clicked.connect(lambda _=False, sid=item.id: self._start_session(sid))
            swap.clicked.connect(lambda _=False, sid=item.id: self._swap_session(sid))
            complete.clicked.connect(
                lambda _=False, sid=item.id, done=item.completed: self._toggle_complete(sid, done)
            )
            bl.addLayout(actions)
            panel.body.addWidget(block)
        panel.body.addStretch(1)
        return panel

    def _after_session_change(self, day: date | None) -> None:
        """In-place refresh after a session mutation — keeps the grid static."""
        if day is not None:
            self._planner.refresh_day(day)
        self._refresh_side_panels()

    def _add_session(self, day: date, session_type: str) -> None:
        fitness.add_session(self._user_id, day, session_type)
        self._selected_day = day
        self._after_session_change(day)

    def _start_session(self, session_id: int) -> None:
        stamp = datetime.now().strftime("%H:%M")
        session = fitness.get_session(session_id)
        if session is None:
            return
        existing = session.notes.strip()
        note = existing if "Started" in existing else f"Started {stamp}." + (f" {existing}" if existing else "")
        fitness.update_session(session_id, notes=note)
        self._after_session_change(session.day)

    def _swap_session(self, session_id: int) -> None:
        session = fitness.get_session(session_id)
        fitness.swap_session(session_id)
        self._after_session_change(session.day if session else None)

    def _complete_session(self, session_id: int) -> None:
        session = fitness.get_session(session_id)
        fitness.mark_complete(session_id, True)
        self._after_session_change(session.day if session else None)

    def _toggle_complete(self, session_id: int, was_done: bool) -> None:
        session = fitness.get_session(session_id)
        fitness.mark_complete(session_id, not was_done)
        self._after_session_change(session.day if session else None)

    def _save_session_notes(self, session_id: int, notes: str) -> None:
        fitness.update_session(session_id, notes=notes)

    def _save_session_label(self, session_id: int, label: str) -> None:
        session = fitness.get_session(session_id)
        fitness.update_session(session_id, label=label)
        self._after_session_change(session.day if session else None)


# --------------------------------------------------------------------------- #
# Insights page
# --------------------------------------------------------------------------- #
class InsightsPage(_ScrollPage):
    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.refresh()

    def refresh(self) -> None:
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        intro = QLabel("Deterministic findings — generated by rules and statistics. No LLM.")
        intro.setObjectName("Faint")
        self.col.addWidget(intro)
        insights = services.latest_insights(self._user_id) if self._user_id else []
        if not insights:
            self.add_placeholder_note("No insights yet. Sync sources to generate them.")
            return
        for ins in insights:
            self.col.addWidget(InsightCard(ins))


# --------------------------------------------------------------------------- #
# Settings page
# --------------------------------------------------------------------------- #
class SettingsPage(_ScrollPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.refresh()

    def refresh(self) -> None:
        from app.ingestion import iter_connectors

        self.clear()
        sources = GlassPanel()
        t = QLabel("Data Sources")
        t.setObjectName("PanelTitle")
        sources.body.addWidget(t)
        for c in iter_connectors():
            # Live-capable connectors probe their real source; the rest are mock.
            live = False
            if hasattr(c, "available"):
                try:
                    live = bool(c.available)
                except Exception:
                    live = False
            if live:
                label, color = "LIVE", PALETTE.positive
            elif hasattr(c, "available"):
                label, color = "OFFLINE · MOCK", PALETTE.orange
            else:
                label, color = "MOCK", PALETTE.text_faint

            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:8px;")
            name = QLabel(c.name)
            hint = QLabel("")
            if hasattr(c, "available") and not live:
                hints = {
                    "activitywatch": "start ActivityWatch on :5600 to go live",
                    "apple_health": "import an export.xml below to go live",
                }
                hint = QLabel(hints.get(c.key, "no live source configured"))
                hint.setObjectName("Mono")
            status = QLabel(label)
            status.setObjectName("Pill")
            row.addWidget(dot)
            row.addWidget(name)
            row.addStretch(1)
            if hint.text():
                row.addWidget(hint)
            row.addWidget(status)
            sources.body.addLayout(row)
        self.col.addWidget(sources)

        self.col.addWidget(self._health_auto_export_panel())
        self.col.addWidget(self._apple_health_panel())
        self.col.addWidget(self._apple_calendar_panel())
        self.col.addWidget(self._tasks_sync_panel())

        # Real-data hygiene: purge the mock seed across every module.
        purge = GlassPanel()
        pt = QLabel("Real Data")
        pt.setObjectName("PanelTitle")
        pbody = QLabel(
            "ORION ships with mock demo data so the UI isn't empty. Once your real "
            "sources are connected, purge the mock data so every tab shows only "
            "genuine, sourced figures — sparse at first, filling in as you sync."
        )
        pbody.setObjectName("Muted")
        pbody.setWordWrap(True)
        purge.body.addWidget(pt)
        purge.body.addWidget(pbody)
        btn = QPushButton("PURGE MOCK DATA · KEEP REAL")
        btn.setObjectName("GhostButton")
        btn.clicked.connect(self._purge_mock)
        purge.body.addWidget(btn)
        self.col.addWidget(purge)

        self.col.addWidget(self._icloud_sync_panel())

        sec = GlassPanel()
        st = QLabel("Security & Storage")
        st.setObjectName("PanelTitle")
        body = QLabel(
            "Local-first: data is stored in a local SQLite database under your OS "
            "app-data directory. No cloud, no hosted LLM. Tokens will move to the OS "
            "keychain; at-rest encryption is a planned enhancement."
        )
        body.setObjectName("Muted")
        body.setWordWrap(True)
        sec.body.addWidget(st)
        sec.body.addWidget(body)
        self.col.addWidget(sec)

    def _icloud_sync_panel(self) -> GlassPanel:
        from app.core.config import get_settings

        settings = get_settings()
        on = settings.icloud_sync
        available = settings.icloud_dir is not None

        panel = GlassPanel()
        title = QLabel("iCloud Drive sync (across your Macs)")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        if not available:
            note = QLabel(
                "iCloud Drive isn't available on this Mac. Enable it in System "
                "Settings → Apple ID → iCloud → iCloud Drive, then return here."
            )
            note.setObjectName("Faint")
            note.setWordWrap(True)
            panel.body.addWidget(note)
            return panel

        status = QLabel(
            "ON · the ORION database lives in iCloud Drive, so all your Macs share "
            "one command centre."
            if on else
            "OFF · the database is local to this Mac. Turn on to sync it across "
            "your Macs via iCloud Drive."
        )
        status.setObjectName("Muted" if on else "Faint")
        status.setWordWrap(True)
        panel.body.addWidget(status)

        caveat = QLabel(
            "Note: this syncs between Macs (and backs the data up to iCloud). Your "
            "iPhone can't open the ORION app itself — on the phone you reach the "
            "data through Calendar and your tasks app, which already sync. Don't "
            "run ORION on two Macs at the same time (SQLite is single-writer)."
        )
        caveat.setObjectName("Faint")
        caveat.setWordWrap(True)
        panel.body.addWidget(caveat)

        btn = QPushButton("TURN OFF ICLOUD SYNC" if on else "TURN ON ICLOUD SYNC")
        btn.setObjectName("GhostButton")
        btn.clicked.connect(lambda: self._toggle_icloud_sync(not on))
        panel.body.addWidget(btn)
        return panel

    def _toggle_icloud_sync(self, enable: bool) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.core.config import get_settings

        # Persist the choice to the project .env so it survives restarts.
        try:
            _set_env_var("ORION_ICLOUD_SYNC", "1" if enable else "0")
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't save setting", str(exc))
            return

        dest = "iCloud Drive" if enable else "this Mac (local)"
        get_settings.cache_clear()
        QMessageBox.information(
            self, "iCloud sync updated",
            f"ORION will store its data on {dest}.\n\nRestart ORION to apply. "
            + ("Your existing data is copied into iCloud on the next launch."
               if enable else "The local copy is used; the iCloud copy is left in place."),
        )
        self.refresh()

    def _purge_mock(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.analytics import generate_insights
        from app.db.purge import purge_mock_data, sync_real_sources

        confirm = QMessageBox.question(
            self, "Purge mock data?",
            "This deletes all demo data across every module (finance, health, "
            "activity, projects, insights, planned sessions). Real sources will "
            "then repopulate on sync. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        uid = services.get_default_user_id()
        purge_mock_data(uid)
        written = sync_real_sources(uid)
        generate_insights(uid)
        total = sum(written.values())
        detail = ", ".join(f"{k}:{v}" for k, v in written.items()) or "none yet"
        QMessageBox.information(
            self, "Mock data purged",
            f"All mock data removed. Real data synced: {total} rows ({detail}).\n"
            "Reopen the other tabs to see real-only figures.",
        )
        self.parent_refresh()

    # --- Health Auto Export (auto-updating) ------------------------------- #
    def _health_auto_export_panel(self) -> GlassPanel:
        from app.ingestion import get_connector

        panel = GlassPanel()
        title = QLabel("Health Auto Export  ·  auto-updating")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        hae = get_connector("health_auto_export")
        folder = hae.folder()
        latest = hae.latest_file()
        uid = services.get_default_user_id()
        fresh = hae.latest_day(uid) if uid else None

        if folder and latest:
            status = QLabel(
                f"LIVE · watching {folder}\n"
                f"latest file: {latest.name}"
                + (f"  ·  data through {fresh.isoformat()}" if fresh else "")
            )
            status.setObjectName("Muted")
        else:
            status = QLabel(
                "Not configured. Point ORION at the folder Health Auto Export "
                "writes to (e.g. an iCloud Drive folder). New files refresh "
                "automatically on each sync — no manual export."
            )
            status.setObjectName("Faint")
        status.setWordWrap(True)
        panel.body.addWidget(status)

        howto = QLabel(
            "In Health Auto Export (iPhone): create an Automation → Export "
            "format JSON → destination a folder in iCloud Drive → schedule daily. "
            "Then choose that same iCloud folder here. ORION reads the newest "
            "file each sync. Fully local once synced; no open ports."
        )
        howto.setObjectName("Faint")
        howto.setWordWrap(True)
        panel.body.addWidget(howto)

        row = QHBoxLayout()
        choose = QPushButton("CHOOSE FOLDER")
        choose.setObjectName("GhostButton")
        choose.clicked.connect(self._choose_hae_folder)
        sync = QPushButton("SYNC NOW")
        sync.setObjectName("GhostButton")
        sync.clicked.connect(self._sync_hae)
        row.addWidget(choose)
        row.addWidget(sync)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        panel.body.addWidget(wrap)
        return panel

    def _choose_hae_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from app.ingestion import get_connector

        path = QFileDialog.getExistingDirectory(
            self, "Select the Health Auto Export folder", ""
        )
        if not path:
            return
        get_connector("health_auto_export").set_folder(path)
        self._sync_hae()

    def _sync_hae(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.db.database import session_scope
        from app.ingestion import get_connector

        hae = get_connector("health_auto_export")
        uid = services.get_default_user_id()
        rows = hae.fetch_raw_data()
        if hae.is_mock:
            QMessageBox.information(
                self, "No export found",
                "No Health Auto Export JSON found in that folder yet. Run an "
                "export on your iPhone, let iCloud sync, then Sync Now.",
            )
            return
        with session_scope() as s:
            written = hae.store_normalised_data(s, uid, 0, rows)
        QMessageBox.information(
            self, "Health Auto Export synced",
            f"Imported {written} days of real Apple Health data. Health, Fitness "
            "and the Stoic observatory now reflect it.",
        )
        self.parent_refresh()

    def parent_refresh(self) -> None:
        # Rebuild this settings page to reflect new freshness.
        self.refresh()

    # --- Apple Health import ---------------------------------------------- #
    def _apple_health_panel(self) -> GlassPanel:
        from app.ingestion import get_connector

        panel = GlassPanel()
        title = QLabel("Apple Health")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        aw = get_connector("apple_health")
        current = aw.export_path()
        status = QLabel(
            f"LIVE · {current.name}" if current else
            "No export imported yet — mood, HRV, sleep and resting HR are mock."
        )
        status.setObjectName("Muted" if current else "Faint")
        status.setWordWrap(True)
        panel.body.addWidget(status)

        howto = QLabel(
            "On iPhone: Health app → profile → Export All Health Data → unzip → "
            "import the export.xml here. Parsed locally; mood comes from your "
            "State of Mind logs (iOS 17+). Nothing leaves this machine."
        )
        howto.setObjectName("Faint")
        howto.setWordWrap(True)
        panel.body.addWidget(howto)

        btn = QPushButton("IMPORT EXPORT.XML")
        btn.setObjectName("GhostButton")
        btn.clicked.connect(self._import_apple_health)
        panel.body.addWidget(btn)
        return panel

    def _import_apple_health(self) -> None:
        import shutil

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from app.core.config import get_settings
        from app.ingestion import get_connector

        path, _ = QFileDialog.getOpenFileName(
            self, "Select Apple Health export.xml", "", "Health export (*.xml)"
        )
        if not path:
            return
        dest_dir = get_settings().data_dir / "apple_health"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "export.xml"
        try:
            shutil.copyfile(path, dest)
            # Parse + persist immediately so the change is visible now.
            aw = get_connector("apple_health")
            rows = aw.fetch_raw_data()
            from app.db.database import session_scope
            from app.services import get_default_user_id

            uid = get_default_user_id()
            with session_scope() as s:
                written = aw.store_normalised_data(s, uid, 0, rows)
            QMessageBox.information(
                self, "Apple Health imported",
                f"Imported {written} days. Sync/reopen the Stoic tab to see live "
                "HRV, sleep, resting HR and mood.",
            )
        except Exception as exc:  # surface, don't crash
            QMessageBox.warning(self, "Import failed", str(exc))

    def _apple_calendar_panel(self) -> GlassPanel:
        from app.ingestion import get_connector

        panel = GlassPanel()
        title = QLabel("Apple Calendar (iCloud)")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        cal = get_connector("apple_calendar")
        if not cal.available:
            status = QLabel(
                "EventKit unavailable on this platform — the Calendar tab shows a "
                "small sample instead. (macOS only.)"
            )
            status.setObjectName("Faint")
            status.setWordWrap(True)
            panel.body.addWidget(status)
            return panel

        authorized = cal.authorization_status() == 3
        status = QLabel(
            "Connected · reading your iCloud calendars (read-only)."
            if authorized else
            "Not connected yet — grant calendar access to mirror your iPhone's "
            "iCloud calendar into ORION. Read-only; ORION never edits your calendar."
        )
        status.setObjectName("Muted" if authorized else "Faint")
        status.setWordWrap(True)
        panel.body.addWidget(status)

        btn = QPushButton("SYNC ICLOUD CALENDAR" if authorized else "CONNECT ICLOUD CALENDAR")
        btn.setObjectName("GhostButton")
        btn.clicked.connect(self._connect_apple_calendar)
        panel.body.addWidget(btn)
        return panel

    def _connect_apple_calendar(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.db.database import session_scope
        from app.db.models import DataSource
        from app.ingestion import get_connector
        from app.services import get_default_user_id

        cal = get_connector("apple_calendar")
        granted = cal.request_access()  # triggers the macOS prompt on first run
        if not granted:
            QMessageBox.warning(
                self, "Calendar access",
                "Calendar access wasn't granted. Enable ORION under System "
                "Settings → Privacy & Security → Calendars, then try again.",
            )
            return
        uid = get_default_user_id()
        with session_scope() as s:
            src = s.query(DataSource).filter_by(user_id=uid, key=cal.key).one_or_none()
            if src is None:
                src = DataSource(user_id=uid, key=cal.key, name=cal.name,
                                 domain=cal.domain, status=cal.status)
                s.add(src)
                s.flush()
            res = cal.run(s, uid, src.id)
        QMessageBox.information(
            self, "iCloud calendar synced",
            f"Synced {res.normalised_records} events. Open the Calendar tab to see "
            "your real schedule.",
        )
        self.refresh()

    def _tasks_sync_panel(self) -> GlassPanel:
        from app.services import get_default_user_id, task_counts

        panel = GlassPanel()
        title = QLabel("Tasks (two-way sync)")
        title.setObjectName("PanelTitle")
        panel.body.addWidget(title)

        uid = get_default_user_id()
        counts = task_counts(uid) if uid else {"open": 0, "done": 0, "total": 0}
        status = QLabel(
            f"{counts['total']} tasks mirrored ({counts['open']} open). Synced both "
            "ways with your tasks app — completions and edits here push back."
        )
        status.setObjectName("Muted" if counts["total"] else "Faint")
        status.setWordWrap(True)
        panel.body.addWidget(status)

        btn = QPushButton("SYNC TASKS NOW")
        btn.setObjectName("GhostButton")
        btn.clicked.connect(self._sync_tasks)
        panel.body.addWidget(btn)
        return panel

    def _sync_tasks(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from app.db.database import session_scope
        from app.db.models import DataSource
        from app.ingestion import get_connector
        from app.services import get_default_user_id

        conn = get_connector("tasks_sync")
        if not conn.connect():
            QMessageBox.warning(
                self, "Tasks sync",
                "Couldn't reach the tasks backend. Check your connection and retry.",
            )
            return
        uid = get_default_user_id()
        with session_scope() as s:
            src = s.query(DataSource).filter_by(user_id=uid, key=conn.key).one_or_none()
            if src is None:
                src = DataSource(user_id=uid, key=conn.key, name=conn.name,
                                 domain=conn.domain, status=conn.status)
                s.add(src)
                s.flush()
            res = conn.run(s, uid, src.id)
        QMessageBox.information(
            self, "Tasks synced",
            f"Synced {res.normalised_records} tasks. Open the Tasks tab to view them.",
        )
        self.refresh()


# --------------------------------------------------------------------------- #
# Career page — editable career observatory (local, no LLM)
# --------------------------------------------------------------------------- #
class CareerPage(_ScrollPage):
    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        if self._user_id is None:
            self.add_placeholder_note("No profile yet. Run the seeder: python -m app.db.seed")
            return

        snap = career.get_snapshot(self._user_id)
        self.col.addWidget(
            SystemHeader(
                "Career", _nav_code("career"),
                subtitle=(f"{snap.profile.role_title.upper()} · {snap.profile.employer.upper()}"
                          if snap.profile.role_title else "ROLE NOT SET"),
                sync_label=snap.jeopardy.band, database_label="CAREER LOCAL",
            )
        )

        # Headline matrices.
        self.col.addWidget(self._matrices_strip(snap))

        # Current role + satisfaction.
        self.col.addWidget(self._role_panel(snap.profile))

        # Two matrices, side by side, factor-by-factor editable.
        mrow = QWidget()
        ml = QHBoxLayout(mrow)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(16)
        ml.addWidget(self._matrix_panel(snap.jeopardy, "jeopardy"), 1)
        ml.addWidget(self._matrix_panel(snap.resilience, "resilience"), 1)
        self.col.addWidget(mrow)

        # Planning journal + career map.
        prow = QWidget()
        pl = QHBoxLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(16)
        pl.addWidget(self._plan_panel(snap.plan_steps), 1)
        pl.addWidget(self._notes_panel(snap.notes), 1)
        self.col.addWidget(prow)

        # Goals, skills, opportunities, traineeships.
        grow = QWidget()
        gl = QHBoxLayout(grow)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(16)
        gl.addWidget(self._goals_panel(snap.goals), 1)
        gl.addWidget(self._skills_panel(snap.skills), 1)
        self.col.addWidget(grow)
        orow = QWidget()
        ol = QHBoxLayout(orow)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(16)
        ol.addWidget(self._opportunities_panel(snap.opportunities), 1)
        ol.addWidget(self._traineeships_panel(snap.traineeships), 1)
        self.col.addWidget(orow)

    # ---- headline ------------------------------------------------------- #
    def _matrices_strip(self, snap) -> QWidget:
        j, r = snap.jeopardy, snap.resilience
        # Tone reflects whether the band is good/bad; arrow reflects the score
        # direction. For jeopardy a HIGH score is bad (red), so high reads red
        # even though the arrow points up.
        j_tone = "bad" if j.band in ("HIGH RISK", "ELEVATED") else "good"
        r_tone = "bad" if r.band in ("EXPOSED", "FRAGILE") else "good"
        cells = [
            ("CAR-JPD", Metric("Job Jeopardy", f"{j.value:.0f}", j.band,
                               "up" if j.value >= 45 else "down", tone=j_tone)),
            ("CAR-RES", Metric("Economic Resilience", f"{r.value:.0f}", r.band,
                               "up" if r.value >= 50 else "down", tone=r_tone)),
            ("CAR-SAT", Metric("Role Satisfaction", f"{snap.profile.satisfaction}",
                               trend="flat")),
            ("CAR-GLS", Metric("Active Goals",
                               str(sum(1 for g in snap.goals if g.status == "active")),
                               trend="flat")),
            ("CAR-OPP", Metric("Open Opportunities", str(len(snap.opportunities)),
                               trend="flat")),
        ]
        return VitalsStrip("Career Vitals", "CAR-VTL", cells)

    # ---- current role --------------------------------------------------- #
    def _role_panel(self, prof) -> HudPanel:
        from PySide6.QtWidgets import QLineEdit, QSlider

        panel = HudPanel("Current Role", "CAR-ROL", status="EDITABLE")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)

        def field(label, edit):
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(label)
            lbl.setObjectName("CardLabel")
            col.addWidget(lbl)
            col.addWidget(edit)
            return col

        title_edit = QLineEdit(prof.role_title)
        title_edit.setMinimumWidth(200)
        title_edit.editingFinished.connect(
            lambda: self._save_profile(role_title=title_edit.text()))
        rl.addLayout(field("ROLE TITLE", title_edit))

        emp_edit = QLineEdit(prof.employer)
        emp_edit.setMinimumWidth(160)
        emp_edit.editingFinished.connect(
            lambda: self._save_profile(employer=emp_edit.text()))
        rl.addLayout(field("EMPLOYER", emp_edit))

        start_edit = QLineEdit(prof.started_on.isoformat() if prof.started_on else "")
        start_edit.setPlaceholderText("YYYY-MM-DD")
        start_edit.setMaximumWidth(120)
        start_edit.editingFinished.connect(
            lambda: self._save_profile(started=start_edit.text()))
        rl.addLayout(field("STARTED", start_edit))
        rl.addStretch(1)
        panel.body.addWidget(row)

        # Satisfaction slider with a live meter.
        sat_meter = MeterBar("Role satisfaction", prof.satisfaction, suffix="%",
                             color=PALETTE.positive)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(prof.satisfaction)
        slider.valueChanged.connect(lambda v: sat_meter.set_value(v))
        slider.sliderReleased.connect(
            lambda: self._save_profile(satisfaction=slider.value()))
        panel.body.addWidget(sat_meter)
        panel.body.addWidget(slider)
        return panel

    def _save_profile(self, **kwargs) -> None:
        from datetime import date as _date
        started = kwargs.pop("started", None)
        if started is not None:
            try:
                kwargs["started_on"] = _date.fromisoformat(started) if started else None
            except ValueError:
                pass
        career.update_profile(self._user_id, **kwargs)
        self.refresh()

    # ---- matrices ------------------------------------------------------- #
    def _matrix_panel(self, matrix, which: str) -> HudPanel:
        from PySide6.QtWidgets import QSlider

        panel = HudPanel(matrix.title, matrix.code, status=matrix.band)
        head = MeterBar(
            f"{matrix.title} — {'higher = safer' if matrix.higher_is_good else 'lower = safer'}",
            matrix.value, suffix="",
            color=self._matrix_color(matrix),
            readout=f"{matrix.value:.0f} / {matrix.band}",
        )
        panel.body.addWidget(head)
        hint = QLabel("Rate each factor 0–100. The headline score is a deterministic "
                      "weighted blend — no guesswork.")
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        panel.body.addWidget(hint)

        for f in matrix.factors:
            line = QWidget()
            ll = QHBoxLayout(line)
            ll.setContentsMargins(0, 0, 0, 0)
            ll.setSpacing(10)
            meter = MeterBar(f"{f.label}  ·  w{f.weight:.2f}", f.score, suffix="%")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(f.score)
            slider.setMaximumWidth(150)
            slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
            slider.sliderReleased.connect(
                lambda w=which, k=f.key, sl=slider: self._save_factor(w, k, sl.value()))
            ll.addWidget(meter, 1)
            ll.addWidget(slider, 0)
            panel.body.addWidget(line)
        return panel

    @staticmethod
    def _matrix_color(matrix) -> str:
        # Colour follows the qualitative band so the worst band always reads red.
        # Jeopardy: SECURE/GUARDED (good) → ELEVATED (caution) → HIGH RISK (red).
        # Resilience: STRONG/MODERATE (good) → FRAGILE (caution) → EXPOSED (red).
        good = {"SECURE", "GUARDED", "STRONG", "MODERATE"}
        bad = {"HIGH RISK", "EXPOSED"}
        if matrix.band in bad:
            return PALETTE.critical
        if matrix.band in good:
            return PALETTE.positive
        return PALETTE.orange

    def _save_factor(self, which: str, key: str, value: int) -> None:
        career.set_matrix_factor(self._user_id, which, key, value)
        self.refresh()

    # ---- planning + notes ---------------------------------------------- #
    def _plan_panel(self, steps) -> HudPanel:
        panel = HudPanel("Career Plan", "CAR-PLN", status=f"{len(steps)} MOVES")
        intro = QLabel("Plan the next visible moves: what you are doing now, next, and later.")
        intro.setObjectName("Faint")
        intro.setWordWrap(True)
        panel.body.addWidget(intro)
        for step in steps:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 5)
            bl.setSpacing(4)

            top = QHBoxLayout()
            title = QLineEdit(step.title)
            title.editingFinished.connect(
                lambda sid=step.id, edit=title: self._update_plan_step(sid, title=edit.text())
            )
            top.addWidget(title, 1)
            horizon = QComboBox()
            horizon.addItems(career.PLAN_HORIZONS)
            horizon.setCurrentText(step.horizon)
            horizon.setMaximumWidth(76)
            horizon.currentTextChanged.connect(
                lambda text, sid=step.id: self._update_plan_step(sid, horizon=text)
            )
            top.addWidget(horizon, 0)
            status = QComboBox()
            status.addItems(career.PLAN_STATUSES)
            status.setCurrentText(step.status)
            status.setMaximumWidth(92)
            status.currentTextChanged.connect(
                lambda text, sid=step.id: self._update_plan_step(sid, status=text)
            )
            top.addWidget(status, 0)
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, sid=step.id: self._del("plan", sid))
            top.addWidget(rm, 0)
            bl.addLayout(top)

            meter = MeterBar(step.status.upper(), step.progress, suffix="%",
                             color=PALETTE.positive if step.status == "done" else PALETTE.accent)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(step.progress)
            slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
            slider.sliderReleased.connect(
                lambda sid=step.id, sl=slider, st=step.status: self._update_plan_step(
                    sid,
                    progress=sl.value(),
                    status="done" if sl.value() >= 100 else st,
                )
            )
            bl.addWidget(meter)
            bl.addWidget(slider)
            notes = QLineEdit(step.notes)
            notes.setPlaceholderText("Next action, risk, or context")
            notes.editingFinished.connect(
                lambda sid=step.id, edit=notes: self._update_plan_step(sid, notes=edit.text())
            )
            bl.addWidget(notes)
            panel.body.addWidget(block)

        add = QLineEdit()
        add.setPlaceholderText("+ Add a career move, press Enter")
        add.returnPressed.connect(lambda: self._add_plan_step(add.text()))
        panel.body.addWidget(add)
        return panel

    def _notes_panel(self, notes) -> HudPanel:
        panel = HudPanel("Career Notes", "CAR-NOT", status=f"{len(notes)} NOTES")
        for note in notes:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 8)
            bl.setSpacing(5)
            top = QHBoxLayout()
            title = QLineEdit(note.title)
            top.addWidget(title, 1)
            tag = QComboBox()
            tags = ["reflection", "plan", "decision", "interview", "learning"]
            tag.addItems(tags)
            tag.setCurrentText(note.tag if note.tag in tags else "reflection")
            tag.setMaximumWidth(104)
            top.addWidget(tag, 0)
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, nid=note.id: self._del("note", nid))
            top.addWidget(rm, 0)
            bl.addLayout(top)
            body = QTextEdit(note.body)
            body.setMaximumHeight(82)
            body.setPlaceholderText("Write the thinking you want future-you to have.")
            bl.addWidget(body)
            meta = QLabel(f"UPDATED {note.updated_on.isoformat()}")
            meta.setObjectName("Mono")
            save = QPushButton("SAVE NOTE")
            save.setObjectName("GhostButton")
            save.clicked.connect(
                lambda _=False, nid=note.id, te=title, be=body, tg=tag:
                    self._update_note(nid, te.text(), be.toPlainText(), tg.currentText())
            )
            foot = QHBoxLayout()
            foot.addWidget(meta)
            foot.addStretch(1)
            foot.addWidget(save)
            bl.addLayout(foot)
            panel.body.addWidget(block)

        new_title = QLineEdit()
        new_title.setPlaceholderText("New note title")
        new_body = QTextEdit()
        new_body.setMaximumHeight(90)
        new_body.setPlaceholderText("Career notes, decision log, applications, ideas...")
        new_tag = QComboBox()
        new_tag.addItems(["reflection", "plan", "decision", "interview", "learning"])
        save_new = QPushButton("ADD NOTE")
        save_new.setObjectName("GhostButton")
        save_new.clicked.connect(
            lambda: self._add_note(new_title.text(), new_body.toPlainText(), new_tag.currentText())
        )
        panel.body.addWidget(new_title)
        panel.body.addWidget(new_body)
        addrow = QHBoxLayout()
        addrow.addWidget(new_tag)
        addrow.addStretch(1)
        addrow.addWidget(save_new)
        panel.body.addLayout(addrow)
        return panel

    def _add_plan_step(self, title: str) -> None:
        if title.strip():
            career.add_plan_step(self._user_id, title)
            self.refresh()

    def _update_plan_step(self, step_id: int, **kwargs) -> None:
        career.update_plan_step(step_id, **kwargs)
        self.refresh()

    def _add_note(self, title: str, body: str, tag: str) -> None:
        if title.strip() or body.strip():
            career.add_note(self._user_id, title or "Career note", body, tag)
            self.refresh()

    def _update_note(self, note_id: int, title: str, body: str, tag: str) -> None:
        career.update_note(note_id, title=title, body=body, tag=tag)
        self.refresh()

    # ---- goals ---------------------------------------------------------- #
    def _goals_panel(self, goals) -> HudPanel:
        from PySide6.QtWidgets import QLineEdit, QSlider

        panel = HudPanel("Goals & Milestones", "CAR-GOL", status=f"{len(goals)} TRACKED")
        for g in goals:
            row = QWidget()
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 4)
            rl.setSpacing(3)
            top = QHBoxLayout()
            name = QLabel(g.title + (f"  · {g.target_date.isoformat()}" if g.target_date else ""))
            name.setObjectName("Muted")
            top.addWidget(name, 1)
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, gid=g.id: self._del("goal", gid))
            top.addWidget(rm, 0)
            rl.addLayout(top)
            meter = MeterBar(g.status.upper(), g.progress, suffix="%",
                             color=PALETTE.accent if g.status == "active" else PALETTE.positive)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(g.progress)
            slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
            slider.sliderReleased.connect(
                lambda gid=g.id, sl=slider: self._update_goal(gid, sl.value()))
            rl.addWidget(meter)
            rl.addWidget(slider)
            panel.body.addWidget(row)

        add = QLineEdit()
        add.setPlaceholderText("+ Add a goal, press Enter")
        add.returnPressed.connect(lambda: self._add_goal(add.text()))
        panel.body.addWidget(add)
        return panel

    def _add_goal(self, title: str) -> None:
        if title.strip():
            career.add_goal(self._user_id, title)
            self.refresh()

    def _update_goal(self, gid: int, progress: int) -> None:
        career.update_goal(gid, progress=progress,
                           status="done" if progress >= 100 else "active")
        self.refresh()

    # ---- skills --------------------------------------------------------- #
    def _skills_panel(self, skills) -> HudPanel:
        from PySide6.QtWidgets import QComboBox, QLineEdit, QSlider

        panel = HudPanel("Skills & Competencies", "CAR-SKL", status=f"{len(skills)} TRACKED")
        for sk in skills:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            meter = MeterBar(sk.name, sk.proficiency, suffix="%")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(sk.proficiency)
            slider.setMaximumWidth(120)
            slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
            slider.sliderReleased.connect(
                lambda sid=sk.id, sl=slider: self._update_skill(sid, prof=sl.value()))
            mom = QComboBox()
            mom.addItems(["up", "flat", "down"])
            mom.setCurrentText(sk.momentum)
            mom.setMaximumWidth(70)
            mom.currentTextChanged.connect(
                lambda t, sid=sk.id: self._update_skill(sid, mom=t))
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, sid=sk.id: self._del("skill", sid))
            rl.addWidget(meter, 1)
            rl.addWidget(slider, 0)
            rl.addWidget(mom, 0)
            rl.addWidget(rm, 0)
            panel.body.addWidget(row)

        add = QLineEdit()
        add.setPlaceholderText("+ Add a skill, press Enter")
        add.returnPressed.connect(lambda: self._add_skill(add.text()))
        panel.body.addWidget(add)
        return panel

    def _add_skill(self, name: str) -> None:
        if name.strip():
            career.add_skill(self._user_id, name)
            self.refresh()

    def _update_skill(self, sid: int, *, prof=None, mom=None) -> None:
        career.update_skill(sid, proficiency=prof, momentum=mom)
        self.refresh()

    # ---- opportunities -------------------------------------------------- #
    def _opportunities_panel(self, opps) -> HudPanel:
        from PySide6.QtWidgets import QComboBox, QLineEdit

        panel = HudPanel("Opportunity Pipeline", "CAR-PIP", status=f"{len(opps)} OPEN")
        for o in opps:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            name = QLabel(f"{o.role}" + (f"  ·  {o.company}" if o.company else ""))
            name.setObjectName("Muted")
            stage = QComboBox()
            stage.addItems([s.title() for s in career.PIPELINE_STAGES])
            stage.setCurrentText(o.stage.title())
            stage.setMaximumWidth(120)
            stage.currentTextChanged.connect(
                lambda t, oid=o.id: self._update_opp(oid, t.lower()))
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, oid=o.id: self._del("opp", oid))
            rl.addWidget(name, 1)
            rl.addWidget(stage, 0)
            rl.addWidget(rm, 0)
            panel.body.addWidget(row)

        add = QLineEdit()
        add.setPlaceholderText("+ Add a role (use ' @ Company'), press Enter")
        add.returnPressed.connect(lambda: self._add_opp(add.text()))
        panel.body.addWidget(add)
        return panel

    def _add_opp(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        role, _, company = text.partition("@")
        career.add_opportunity(self._user_id, role.strip(), company.strip())
        self.refresh()

    def _update_opp(self, oid: int, stage: str) -> None:
        career.update_opportunity(oid, stage=stage)
        self.refresh()

    # ---- traineeships --------------------------------------------------- #
    def _traineeships_panel(self, rows) -> HudPanel:
        panel = HudPanel("Traineeship Tracker", "CAR-TRN", status=f"{len(rows)} TRACKED")
        if not rows:
            empty = QLabel("Track traineeships, apprenticeships, graduate schemes, and deadlines here.")
            empty.setObjectName("Faint")
            empty.setWordWrap(True)
            panel.body.addWidget(empty)
        for item in rows:
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 6)
            bl.setSpacing(4)
            top = QHBoxLayout()
            name = QLabel(item.programme + (f" · {item.provider}" if item.provider else ""))
            name.setObjectName("Muted")
            top.addWidget(name, 1)
            status = QComboBox()
            status.addItems(career.TRAINEESHIP_STATUSES)
            status.setCurrentText(item.status)
            status.setMaximumWidth(118)
            status.currentTextChanged.connect(
                lambda text, tid=item.id: self._update_traineeship(tid, status=text)
            )
            top.addWidget(status, 0)
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, tid=item.id: self._del("traineeship", tid))
            top.addWidget(rm, 0)
            bl.addLayout(top)

            color = PALETTE.positive if item.status == "offer" else PALETTE.orange if item.deadline else PALETTE.accent
            meter = MeterBar(item.status.upper(), item.progress, suffix="%", color=color)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(item.progress)
            slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
            slider.sliderReleased.connect(
                lambda tid=item.id, sl=slider: self._update_traineeship(tid, progress=sl.value())
            )
            bl.addWidget(meter)
            bl.addWidget(slider)
            detail = QLineEdit(item.notes)
            deadline = item.deadline.isoformat() if item.deadline else "no deadline"
            detail.setPlaceholderText(f"Notes, contact, or next step · {deadline}")
            detail.editingFinished.connect(
                lambda tid=item.id, edit=detail: self._update_traineeship(tid, notes=edit.text())
            )
            bl.addWidget(detail)
            panel.body.addWidget(block)

        add = QLineEdit()
        add.setPlaceholderText("+ Add programme (use ' @ Provider'), press Enter")
        add.returnPressed.connect(lambda: self._add_traineeship(add.text()))
        panel.body.addWidget(add)
        return panel

    def _add_traineeship(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        programme, _, provider = text.partition("@")
        career.add_traineeship(self._user_id, programme.strip(), provider.strip())
        self.refresh()

    def _update_traineeship(self, traineeship_id: int, **kwargs) -> None:
        career.update_traineeship(traineeship_id, **kwargs)
        self.refresh()

    def _del(self, kind: str, row_id: int) -> None:
        {
            "goal": career.delete_goal,
            "skill": career.delete_skill,
            "opp": career.delete_opportunity,
            "note": career.delete_note,
            "plan": career.delete_plan_step,
            "traineeship": career.delete_traineeship,
        }[kind](row_id)
        self.refresh()


# --------------------------------------------------------------------------- #
# Diploma page — editable study tracker (local, no LLM)
# --------------------------------------------------------------------------- #
class DiplomaPage(_ScrollPage):
    def __init__(self, user_id: int | None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        if self._user_id is None:
            self.add_placeholder_note("No program yet. Run the seeder: python -m app.db.seed")
            return

        snap = diploma.get_snapshot(self._user_id)
        self.col.addWidget(
            SystemHeader(
                "Diploma", _nav_code("diploma"),
                subtitle=(f"{snap.program.name.upper()}"
                          + (f" · {snap.program.awarding_body.upper()}"
                             if snap.program.awarding_body else "")),
                sync_label=f"{snap.progress_pct:.0f}% COMPLETE",
                database_label="STUDY LOCAL",
            )
        )
        self.col.addWidget(self._vitals_strip(snap))
        self.col.addWidget(self._program_panel(snap.program))
        self.col.addWidget(self._modules_panel(snap.modules))
        self.col.addWidget(self._assessments_panel(snap.assessments))

    def _vitals_strip(self, snap) -> QWidget:
        avg = f"{snap.weighted_average:.1f}" if snap.weighted_average is not None else "—"
        prepared = f"{snap.prepared_pct:.0f}%" if snap.prepared_pct is not None else "—"
        cells = [
            ("DIP-AVG", Metric("Weighted Average", avg, trend="flat")),
            ("DIP-PRG", Metric("Progress", f"{snap.progress_pct:.0f}%", trend="up")),
            ("DIP-CRD", Metric("Credits",
                               f"{snap.credits_earned}/{snap.program.credits_required}",
                               trend="flat")),
            ("DIP-RDY", Metric("Preparedness", prepared, trend="flat")),
            ("DIP-OPN", Metric("Open Assessments", str(snap.open_assessment_count),
                               trend="flat")),
        ]
        return VitalsStrip("Study Vitals", "DIP-VTL", cells)

    def _program_panel(self, prog) -> HudPanel:
        from PySide6.QtWidgets import QLineEdit, QSpinBox

        panel = HudPanel("Programme", "DIP-PRO", status="EDITABLE")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)

        def field(label, w):
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(label)
            lbl.setObjectName("CardLabel")
            col.addWidget(lbl)
            col.addWidget(w)
            return col

        name = QLineEdit(prog.name)
        name.setMinimumWidth(220)
        name.editingFinished.connect(lambda: self._save_program(name=name.text()))
        rl.addLayout(field("QUALIFICATION", name))

        body = QLineEdit(prog.awarding_body)
        body.setMinimumWidth(160)
        body.editingFinished.connect(lambda: self._save_program(awarding_body=body.text()))
        rl.addLayout(field("AWARDING BODY", body))

        credits = QSpinBox()
        credits.setRange(1, 1000)
        credits.setValue(prog.credits_required)
        credits.valueChanged.connect(lambda v: self._save_program(credits_required=v))
        rl.addLayout(field("CREDITS REQ.", credits))

        target = QLineEdit(prog.target_date.isoformat() if prog.target_date else "")
        target.setPlaceholderText("YYYY-MM-DD")
        target.setMaximumWidth(120)
        target.editingFinished.connect(lambda: self._save_program(target=target.text()))
        rl.addLayout(field("TARGET DATE", target))
        rl.addStretch(1)
        panel.body.addWidget(row)
        return panel

    def _save_program(self, **kwargs) -> None:
        from datetime import date as _date
        target = kwargs.pop("target", None)
        if target is not None:
            try:
                kwargs["target_date"] = _date.fromisoformat(target) if target else None
            except ValueError:
                pass
        diploma.update_program(self._user_id, **kwargs)
        self.refresh()

    def _modules_panel(self, modules) -> HudPanel:
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

        panel = HudPanel("Modules & Grades", "DIP-MOD", status=f"{len(modules)} MODULES")
        header = QLabel("MODULE · CREDITS · WEIGHT · GRADE · STATUS")
        header.setObjectName("CardLabel")
        panel.body.addWidget(header)

        for m in modules:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            name = QLabel(m.name)
            name.setObjectName("Muted")
            name.setMinimumWidth(160)

            credits = QSpinBox()
            credits.setRange(0, 200)
            credits.setValue(m.credits)
            credits.setMaximumWidth(64)
            credits.valueChanged.connect(lambda v, mid=m.id: self._update_module(mid, credits=v))

            weight = QDoubleSpinBox()
            weight.setRange(0.0, 5.0)
            weight.setSingleStep(0.25)
            weight.setValue(m.weight)
            weight.setMaximumWidth(64)
            weight.valueChanged.connect(lambda v, mid=m.id: self._update_module(mid, weight=v))

            grade = QSpinBox()
            grade.setRange(-1, 100)
            grade.setSpecialValueText("—")
            grade.setValue(int(m.grade) if m.grade is not None else -1)
            grade.setMaximumWidth(64)
            grade.valueChanged.connect(lambda v, mid=m.id: self._update_module(mid, grade=v))

            status = QComboBox()
            status.addItems([s.title() for s in diploma.MODULE_STATES])
            status.setCurrentText(m.status.title())
            status.setMaximumWidth(90)
            status.currentTextChanged.connect(
                lambda t, mid=m.id: self._update_module(mid, status=t.lower()))

            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, mid=m.id: self._del("module", mid))

            rl.addWidget(name, 1)
            rl.addWidget(credits, 0)
            rl.addWidget(weight, 0)
            rl.addWidget(grade, 0)
            rl.addWidget(status, 0)
            rl.addWidget(rm, 0)
            panel.body.addWidget(row)

        add = QLineEdit()
        add.setPlaceholderText("+ Add a module, press Enter")
        add.returnPressed.connect(lambda: self._add_module(add.text()))
        panel.body.addWidget(add)
        return panel

    def _add_module(self, name: str) -> None:
        if name.strip():
            diploma.add_module(self._user_id, name)
            self.refresh()

    def _update_module(self, mid: int, **kwargs) -> None:
        if "grade" in kwargs:
            g = kwargs["grade"]
            kwargs["grade"] = float(g) if g >= 0 else -1.0  # -1 clears (service maps to None)
        diploma.update_module(mid, **kwargs)
        self.refresh()

    def _assessments_panel(self, assessments) -> HudPanel:
        from PySide6.QtWidgets import QComboBox, QLineEdit, QSlider

        panel = HudPanel("Assessments & Readiness", "DIP-ASM",
                         status=f"{len(assessments)} TRACKED")
        hint = QLabel("Coursework tracked by submission status; exams by readiness — "
                      "not by hours logged.")
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        panel.body.addWidget(hint)

        for a in assessments:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            due = f"  · due {a.due_date.isoformat()}" if a.due_date else ""
            name = QLabel(f"[{a.kind[:4].upper()}] {a.title}{due}")
            name.setObjectName("Muted")
            name.setMinimumWidth(200)
            rl.addWidget(name, 1)

            if a.kind == "exam":
                meter = MeterBar("Readiness", a.readiness, suffix="%",
                                 color=PALETTE.positive if a.readiness >= 70 else PALETTE.orange)
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 100)
                slider.setValue(a.readiness)
                slider.setMaximumWidth(140)
                slider.valueChanged.connect(lambda v, m=meter: m.set_value(v))
                slider.sliderReleased.connect(
                    lambda aid=a.id, sl=slider: self._update_assessment(
                        aid, readiness=sl.value(),
                        status="ready" if sl.value() >= 100 else "revising"))
                rl.addWidget(meter, 1)
                rl.addWidget(slider, 0)
            else:
                status = QComboBox()
                status.addItems([s.replace("_", " ").title() for s in diploma.ASSIGNMENT_STATES])
                status.setCurrentText(a.status.replace("_", " ").title())
                status.setMaximumWidth(140)
                status.currentTextChanged.connect(
                    lambda t, aid=a.id: self._update_assessment(
                        aid, status=t.lower().replace(" ", "_")))
                rl.addWidget(status, 0)

            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda _=False, aid=a.id: self._del("assessment", aid))
            rl.addWidget(rm, 0)
            panel.body.addWidget(row)

        # Add row: title + kind.
        add_row = QWidget()
        al = QHBoxLayout(add_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        add = QLineEdit()
        add.setPlaceholderText("+ Add an assessment, press Enter")
        kind = QComboBox()
        kind.addItems(["assignment", "exam"])
        kind.setMaximumWidth(110)
        add.returnPressed.connect(lambda: self._add_assessment(add.text(), kind.currentText()))
        al.addWidget(add, 1)
        al.addWidget(kind, 0)
        panel.body.addWidget(add_row)
        return panel

    def _add_assessment(self, title: str, kind: str) -> None:
        if title.strip():
            diploma.add_assessment(self._user_id, title, kind)
            self.refresh()

    def _update_assessment(self, aid: int, **kwargs) -> None:
        diploma.update_assessment(aid, **kwargs)
        self.refresh()

    def _del(self, kind: str, row_id: int) -> None:
        {"module": diploma.delete_module,
         "assessment": diploma.delete_assessment}[kind](row_id)
        self.refresh()
