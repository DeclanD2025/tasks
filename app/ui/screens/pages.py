"""Module pages.

Each navigation key maps to a page widget. The Overview page is built from real
seeded data via `app.services`; the other module pages show a polished
placeholder layout (metric strip + chart + panel) so the modular structure is
visible and each is ready to be filled in later.

Pages are decoupled from the ORM — they only call `app.services`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import services
from app.ui.components.charts import ChartPanel, RadarPanel, TimelinePanel
from app.ui.components.widgets import GlassPanel, InsightCard, MetricCard, ModuleCard
from app.services import Metric
from app.ui.navigation import NAV_ITEMS
from app.ui.themes.theme import PALETTE


class _ScrollPage(QScrollArea):
    """A vertically scrolling page with a content column."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.col = QVBoxLayout(container)
        self.col.setContentsMargins(24, 18, 24, 24)
        self.col.setSpacing(16)
        self.col.setAlignment(Qt.AlignTop)
        self.setWidget(container)

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
        # Clear and rebuild.
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._user_id is None:
            self.add_placeholder_note("No data yet. Run the seeder: python -m app.db.seed")
            return

        metrics = services.overview_metrics(self._user_id)
        self.add_metric_strip(metrics)

        # Net-worth chart + radar of system health, side by side.
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        nw = services.net_worth_series(self._user_id)
        chart = ChartPanel("Net Worth — 30 day", note="GBP")
        if not nw.empty:
            chart.line(nw["value"].tolist(), color=PALETTE.accent)
        hl.addWidget(chart, 2)

        radar = RadarPanel(
            "System Balance",
            ["Finance", "Health", "Focus", "Creative", "Projects", "Training"],
            self._system_balance(),
        )
        hl.addWidget(radar, 1)
        self.col.addWidget(row)

        # Module grid.
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        modules = [n for n in NAV_ITEMS if n.key not in ("overview", "settings", "insights")]
        for i, item in enumerate(modules):
            card = ModuleCard(item.icon, item.label, item.subtitle)
            card.mousePressEvent = lambda _e, k=item.key: self.open_module.emit(k)
            grid.addWidget(card, i // 4, i % 4)
        self.col.addWidget(grid_host)

        # Latest insights.
        insights = services.latest_insights(self._user_id, limit=4)
        if insights:
            host = QWidget()
            il = QHBoxLayout(host)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(14)
            for ins in insights:
                il.addWidget(InsightCard(ins))
            self.col.addWidget(host)

    def _system_balance(self) -> list[float]:
        """Normalised 0..1 scores for the radar (deterministic heuristics)."""
        uid = self._user_id
        try:
            af = services.activity_frame(uid)
            hf = services.health_frame(uid)
            pm = services.project_momentum(uid)
            finance = 0.7
            health = min(1.0, (hf["sleep_minutes"].tail(7).mean() or 0) / 480) if not hf.empty else 0.5
            focus = min(1.0, (af["deep_work_minutes"].tail(7).mean() or 0) / 240) if not af.empty else 0.5
            creative = 0.55
            projects = min(1.0, (pm["momentum"].mean() or 0) / 100) if not pm.empty else 0.5
            training = min(1.0, (af["training_load"].tail(7).mean() or 0) / 100) if not af.empty else 0.5
            return [finance, health, focus, creative, projects, training]
        except Exception:
            return [0.6] * 6


# --------------------------------------------------------------------------- #
# Generic module page (placeholder layout, ready to flesh out)
# --------------------------------------------------------------------------- #
class ModulePage(_ScrollPage):
    def __init__(self, key: str, user_id: int | None, parent=None):
        super().__init__(parent)
        self._key = key
        self._user_id = user_id
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
        self.add_metric_strip([
            Metric("Primary", "—"),
            Metric("Secondary", "—"),
            Metric("Tertiary", "—"),
        ])
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
    def _build_finance(self) -> None:
        uid = self._user_id
        nw = services.net_worth_series(uid)
        ms = services.monthly_spending(uid)
        cards = [
            Metric("Net Worth", f"£{nw['value'].iloc[-1]:,.0f}" if not nw.empty else "—"),
            Metric("Accounts", "4"),
            Metric("This Month Spend", f"£{ms['spend'].iloc[-1]:,.0f}" if not ms.empty else "—"),
        ]
        self.add_metric_strip(cards)
        chart = ChartPanel("Net Worth — 30 day", note="GBP")
        if not nw.empty:
            chart.line(nw["value"].tolist(), color=PALETTE.accent)
        self.col.addWidget(chart)
        spend = ChartPanel("Monthly Spending")
        if not ms.empty:
            spend.bars(ms["spend"].tolist(), color=PALETTE.accent_2)
        self.col.addWidget(spend)

    def _build_health(self) -> None:
        uid = self._user_id
        hf = services.health_frame(uid)
        self.add_metric_strip([
            Metric("Sleep (7d avg)", f"{hf['sleep_minutes'].tail(7).mean()/60:.1f}h" if not hf.empty else "—"),
            Metric("HRV (7d avg)", f"{hf['hrv_ms'].tail(7).mean():.0f} ms" if not hf.empty else "—"),
            Metric("Resting HR", f"{hf['resting_hr'].tail(7).mean():.0f} bpm" if not hf.empty else "—"),
        ])
        sleep = ChartPanel("Sleep — minutes/night", note="30 day")
        if not hf.empty:
            sleep.line(hf["sleep_minutes"].tolist(), color=PALETTE.accent_3)
        self.col.addWidget(sleep)
        hrv = ChartPanel("HRV — ms")
        if not hf.empty:
            hrv.line(hf["hrv_ms"].tolist(), color=PALETTE.positive)
        self.col.addWidget(hrv)

    def _build_productivity(self) -> None:
        uid = self._user_id
        af = services.activity_frame(uid)
        self.add_metric_strip([
            Metric("Deep Work (7d)", f"{af['deep_work_minutes'].tail(7).sum()/60:.1f}h" if not af.empty else "—"),
            Metric("Active min (7d avg)", f"{af['active_minutes'].tail(7).mean():.0f}" if not af.empty else "—"),
            Metric("Steps (7d avg)", f"{af['steps'].tail(7).mean():,.0f}" if not af.empty else "—"),
        ])
        dw = ChartPanel("Deep Work — minutes/day", note="30 day")
        if not af.empty:
            dw.bars(af["deep_work_minutes"].tolist(), color=PALETTE.accent)
        self.col.addWidget(dw)

    def _build_projects(self) -> None:
        uid = self._user_id
        pm = services.project_momentum(uid)
        self.add_metric_strip([
            Metric("Active Projects", str(pm["project"].nunique()) if not pm.empty else "0"),
            Metric("Avg Momentum", f"{pm['momentum'].mean():.0f}/100" if not pm.empty else "—"),
        ])
        chart = ChartPanel("Project Momentum")
        if not pm.empty:
            import pandas as pd
            pm = pm.copy()
            pm["day"] = pd.to_datetime(pm["day"])
            daily = pm.groupby("day")["momentum"].mean().sort_index()
            chart.line(daily.tolist(), color=PALETTE.accent_2)
        self.col.addWidget(chart)

    def _build_football(self) -> None:
        self.add_metric_strip([
            Metric("Form (last 6)", "W W D L W D"),
            Metric("Goals For", "12"),
            Metric("Goals Against", "7"),
        ])
        self.col.addWidget(TimelinePanel("Recent Fixtures", [
            ("Sat 07 Jun", "Win 3–1 — strong second half"),
            ("Wed 04 Jun", "Draw 1–1 — late equaliser conceded"),
            ("Sat 31 May", "Win 2–0 — clean sheet"),
        ]))


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
        from app.ingestion import iter_connectors

        sources = GlassPanel()
        t = QLabel("Data Sources")
        t.setObjectName("PanelTitle")
        sources.body.addWidget(t)
        for c in iter_connectors():
            row = QHBoxLayout()
            name = QLabel(f"{c.name}")
            status = QLabel("MOCK" if c.is_mock else "CONNECTED")
            status.setObjectName("Pill")
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(status)
            sources.body.addLayout(row)
        self.col.addWidget(sources)

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
