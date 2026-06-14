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
from app.ui.components.charts import ChartPanel, TimelinePanel
from app.ui.components.hud import HudPanel, MetricCell
from app.ui.components.panels import (
    BiometricPanel,
    FinanceTerminalPanel,
    SystemHeader,
    VitalsStrip,
    ZoneDistribution,
)
from app.ui.components.viz import (
    DomainConstellation,
    DomainNode,
    InsightFeed,
    RadarDial,
    SignalLineChart,
)
from app.ui.components.widgets import GlassPanel, InsightCard, MetricCard
from app.services import Metric
from app.ui.navigation import NAV_ITEMS
from app.ui.themes.theme import PALETTE


_NAV_BY_KEY = {item.key: item for item in NAV_ITEMS}


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

    def clear(self) -> None:
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


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

        metrics = services.overview_metrics(self._user_id)
        insights = services.latest_insights(self._user_id, limit=4)
        self.col.addWidget(SystemHeader("Mission Overview", _nav_code("overview")))

        core_metrics = [m for m in metrics if m.label != "Weekly Insight"]
        main = QWidget()
        grid = QGridLayout(main)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 5)
        grid.setColumnStretch(2, 2)

        left = _metric_panel("Core Metrics", "OVW-MET", core_metrics, limit=7)
        left.setMinimumWidth(230)
        grid.addWidget(left, 0, 0)

        constellation = HudPanel("Domain Constellation", "OVW-NET", status="ACTIVE")
        constellation.body.addWidget(DomainConstellation(self._domain_nodes()), 1)
        grid.addWidget(constellation, 0, 1)

        feed = _feed_panel("Insight Feed", "INS-FEED", insights, status=f"{len(insights)} SIG")
        feed.setMinimumWidth(260)
        grid.addWidget(feed, 0, 2)
        self.col.addWidget(main)

        trend_metrics = core_metrics[:4] or [Metric("System State", "NOMINAL", trend="flat")]
        self.col.addWidget(
            VitalsStrip(
                "Trend Strip",
                "OVW-TND",
                [(f"TND-{i + 1:02d}", metric) for i, metric in enumerate(trend_metrics)],
            )
        )

        nw = services.net_worth_series(self._user_id)
        if not nw.empty:
            self.col.addWidget(
                _signal_panel(
                    "Net Worth Trajectory", "FIN-LINK", nw["value"].tolist(), unit="GBP", height=120
                )
            )

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
            training = (
                min(1.0, (af["training_load"].tail(7).mean() or 0) / 100) if not af.empty else 0.5
            )
            return [finance, health, focus, creative, projects, training]
        except Exception:
            return [0.6] * 6

    def _domain_nodes(self) -> list[DomainNode]:
        balance = self._system_balance()
        lookup = {
            "finance": balance[0],
            "health": balance[1],
            "productivity": balance[2],
            "creative": balance[3],
            "projects": balance[4],
            "football": balance[5],
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
    def _build_finance(self) -> None:
        uid = self._user_id
        nw = services.net_worth_series(uid)
        ms = services.monthly_spending(uid)
        accounts = services.account_snapshot_latest(uid)
        txns = services.recent_transactions(uid)
        categories = services.spending_by_category(uid)
        total_assets = sum(max(float(a["value"]), 0.0) for a in accounts)
        cash = sum(
            max(float(a["value"]), 0.0) for a in accounts if a["kind"] in ("current", "savings")
        )
        invested = sum(
            max(float(a["value"]), 0.0) for a in accounts if a["kind"] in ("investment", "crypto")
        )
        debt = abs(sum(min(float(a["value"]), 0.0) for a in accounts))
        burn = float(ms["spend"].iloc[-1]) if not ms.empty else 0.0
        latest = float(nw["value"].iloc[-1]) if not nw.empty else total_assets
        first = float(nw["value"].iloc[0]) if not nw.empty else latest
        pct = (latest - first) / first * 100 if first else 0.0

        self.col.addWidget(SystemHeader("Finance Terminal", _nav_code("finance")))
        self.col.addWidget(
            VitalsStrip(
                "Cash/Debt Strip",
                "FIN-VTL",
                [
                    (
                        "FIN-NW",
                        Metric(
                            "Net Worth",
                            f"£{latest:,.0f}",
                            f"{pct:+.1f}%",
                            "up" if pct > 0 else "down" if pct < 0 else "flat",
                            nw["value"].tolist() if not nw.empty else None,
                        ),
                    ),
                    ("FIN-CSH", Metric("Cash", f"£{cash:,.0f}", trend="flat")),
                    ("FIN-INV", Metric("Invested", f"£{invested:,.0f}", trend="flat")),
                    ("FIN-DBT", Metric("Debt", f"£{debt:,.0f}", trend="flat")),
                    ("FIN-BRN", Metric("Monthly Burn", f"£{burn:,.0f}", trend="down")),
                ],
            )
        )

        allocation: dict[str, float] = {}
        for account in accounts:
            value = max(float(account["value"]), 0.0)
            if value:
                label = str(account["kind"]).replace("_", " ")
                allocation[label] = allocation.get(label, 0.0) + value

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)

        grid.addWidget(FinanceTerminalPanel(allocation), 0, 0)
        trajectory = _signal_panel(
            "Capital Trajectory",
            "FIN-TRJ",
            nw["value"].tolist() if not nw.empty else [latest, latest],
            height=220,
        )
        grid.addWidget(trajectory, 0, 1)
        grid.addWidget(self._transaction_panel(txns), 1, 0)
        grid.addWidget(self._risk_panel(cash, debt, burn, total_assets, pct), 1, 1)
        self.col.addWidget(grid_host)

        zones = [
            (
                str(row["category"]),
                float(row["spend"]),
                [PALETTE.accent, PALETTE.violet, PALETTE.orange, PALETTE.positive, PALETTE.coral][
                    i % 5
                ],
            )
            for i, row in enumerate(categories[:5])
        ] or [("idle", 1.0, PALETTE.border)]
        self.col.addWidget(ZoneDistribution("Spend Distribution", "FIN-SPD", zones))

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

    def _risk_panel(
        self, cash: float, debt: float, burn: float, total_assets: float, trend_pct: float
    ) -> HudPanel:
        panel = HudPanel("Risk Monitor", "FIN-RSK", status="WATCH")
        runway = cash / burn if burn else 12.0
        values = [
            _clamp(cash / (total_assets or 1.0)),
            _clamp(1.0 - debt / (total_assets or 1.0)),
            _clamp(runway / 6.0),
            0.72,
            _clamp((trend_pct + 8.0) / 16.0),
        ]
        panel.body.addWidget(
            RadarDial(
                ["Cash", "Debt", "Runway", "Spread", "Trend"],
                values,
                color=PALETTE.orange if min(values) < 0.35 else PALETTE.accent,
            )
        )
        readout = QLabel(
            f"RUNWAY {runway:.1f} MO  ·  ASSETS £{total_assets:,.0f}  ·  DEBT £{debt:,.0f}"
        )
        readout.setObjectName("Mono")
        panel.body.addWidget(readout)
        return panel

    def _build_health(self) -> None:
        uid = self._user_id
        hf = services.health_frame(uid)
        af = services.activity_frame(uid)

        sleep_series = (hf["sleep_minutes"] / 60).dropna().tolist() if not hf.empty else []
        hrv_series = hf["hrv_ms"].dropna().tolist() if not hf.empty else []
        rhr_series = hf["resting_hr"].dropna().tolist() if not hf.empty else []
        weight_series = hf["weight_kg"].dropna().tolist() if not hf.empty else []
        load_series = af["training_load"].dropna().tolist() if not af.empty else []
        active_series = af["active_minutes"].dropna().tolist() if not af.empty else []

        sleep = sum(sleep_series[-7:]) / min(len(sleep_series), 7) if sleep_series else 0.0
        hrv = sum(hrv_series[-7:]) / min(len(hrv_series), 7) if hrv_series else 0.0
        rhr = sum(rhr_series[-7:]) / min(len(rhr_series), 7) if rhr_series else 0.0
        weight = weight_series[-1] if weight_series else 0.0
        load = sum(load_series[-7:]) / min(len(load_series), 7) if load_series else 0.0
        active = sum(active_series[-7:]) / min(len(active_series), 7) if active_series else 0.0

        sleep_score = _clamp(sleep / 8.0)
        hrv_score = _clamp(hrv / 80.0)
        rhr_score = _clamp(1.0 - ((rhr or 62.0) - 48.0) / 34.0)
        load_score = _clamp(1.0 - max(0.0, load - 65.0) / 55.0)
        recovery_score = _clamp(
            sleep_score * 0.34 + hrv_score * 0.30 + rhr_score * 0.22 + load_score * 0.14
        )
        vo2 = 34.0 + hrv * 0.12 + active * 0.035 - max(0.0, rhr - 52.0) * 0.18
        vo2_score = _clamp((vo2 - 32.0) / 24.0)
        weight_score = _clamp(1.0 - abs((weight or 79.0) - 79.0) / 8.0)

        telemetry = [
            {"label": "Sleep", "value": f"{sleep:.1f}h", "score": sleep_score},
            {"label": "HRV", "value": f"{hrv:.0f} ms", "score": hrv_score},
            {"label": "Recovery", "value": f"{recovery_score * 100:.0f}%", "score": recovery_score},
            {"label": "RHR", "value": f"{rhr:.0f} bpm", "score": rhr_score},
            {
                "label": "Weight",
                "value": f"{weight:.1f} kg" if weight else "—",
                "score": weight_score,
            },
            {"label": "VO2", "value": f"{vo2:.1f}", "score": vo2_score},
            {"label": "Training Load", "value": f"{load:.0f}", "score": load_score},
        ]

        self.col.addWidget(SystemHeader("Health Telemetry", _nav_code("health")))
        self.col.addWidget(BiometricPanel(telemetry))

        trends = QWidget()
        hl = QHBoxLayout(trends)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)
        hl.addWidget(
            _signal_panel(
                "Sleep Signal",
                "HLT-SLP",
                sleep_series or [0, 0],
                unit="h",
                color=PALETTE.accent,
                height=130,
            )
        )
        hl.addWidget(
            _signal_panel(
                "HRV Signal",
                "HLT-HRV",
                hrv_series or [0, 0],
                unit="ms",
                color=PALETTE.positive,
                height=130,
            )
        )
        self.col.addWidget(trends)

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

    def _build_projects(self) -> None:
        uid = self._user_id
        pm = services.project_momentum(uid)
        self.add_metric_strip(
            [
                Metric("Active Projects", str(pm["project"].nunique()) if not pm.empty else "0"),
                Metric("Avg Momentum", f"{pm['momentum'].mean():.0f}/100" if not pm.empty else "—"),
            ]
        )
        chart = ChartPanel("Project Momentum")
        if not pm.empty:
            import pandas as pd

            pm = pm.copy()
            pm["day"] = pd.to_datetime(pm["day"])
            daily = pm.groupby("day")["momentum"].mean().sort_index()
            chart.line(daily.tolist(), color=PALETTE.accent)
        self.col.addWidget(chart)

    def _build_football(self) -> None:
        self.add_metric_strip(
            [
                Metric("Form (last 6)", "W W D L W D"),
                Metric("Goals For", "12"),
                Metric("Goals Against", "7"),
            ]
        )
        self.col.addWidget(
            TimelinePanel(
                "Recent Fixtures",
                [
                    ("Sat 07 Jun", "Win 3–1 — strong second half"),
                    ("Wed 04 Jun", "Draw 1–1 — late equaliser conceded"),
                    ("Sat 31 May", "Win 2–0 — clean sheet"),
                ],
            )
        )


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
