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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import services
from app.domains.health.health_service import get_health_dashboard_snapshot
from app.domains.stoic.stoic_service import get_stoic_snapshot
from app.domains.stoic.stoic_widgets import (
    ControlGauge,
    EudaimoniaGauge,
    LifeWeeksGrid,
    MaximPlate,
)
from app.ui.components.charts import ChartPanel
from app.ui.components.hud import HudPanel, MetricCell
from app.ui.components.panels import (
    BiometricScanPanel,
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
from app.ui.themes.theme import PALETTE, TYPE


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
        snapshot = get_health_dashboard_snapshot(self._user_id)
        self.col.addWidget(
            SystemHeader(
                snapshot.title,
                _nav_code("health"),
                subtitle=snapshot.subtitle,
                sync_label=snapshot.sync_status,
                database_label=snapshot.database_status,
            )
        )
        self.col.addWidget(BiometricScanPanel(snapshot))

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
            "Every score below is derived from real data only. Unmeasured virtues read "
            "NO DATA rather than an estimate. Coverage = share backed by a live source."
        )
        banner.setObjectName("Faint")
        banner.setWordWrap(True)
        self.col.addWidget(banner)

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
        eud.body.addWidget(EudaimoniaGauge(snap.eudaimonia_index or 0.0))
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

        # Row 2: dichotomy of control | daily practice
        row2 = QWidget()
        g2 = QGridLayout(row2)
        g2.setContentsMargins(0, 0, 0, 0)
        g2.setHorizontalSpacing(16)
        g2.setColumnStretch(0, 1)
        g2.setColumnStretch(1, 1)

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
        g2.addWidget(ctrl, 0, 0)

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
        g2.addWidget(prac, 0, 1)
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

        self.col.addWidget(self._apple_health_panel())

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
