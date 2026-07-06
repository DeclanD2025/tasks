"""Module navigation model shared by the sidebar and the page stack."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str  # a glyph used as a lightweight icon (no asset dependency)
    code: str  # technical module ID, e.g. "FIN-01"
    subtitle: str


NAV_ITEMS: list[NavItem] = [
    NavItem("overview", "Today", "◎", "TDY-00", "Daily command centre"),
    NavItem("fitness", "Training", "▲", "TRN-01", "Strength, running, routes and block planning"),
    NavItem("health", "Recovery", "✛", "RCV-03", "Sleep, HRV, strain and readiness"),
    NavItem("finance", "Money", "▤", "MNY-04", "Cashflow, bills and safe-to-spend"),
    NavItem("mental_health", "Mind", "◌", "MND-05", "Check-ins, protocols, mindfulness and Stoic practice"),
    NavItem("data", "Data", "▥", "DAT-06", "Health Auto Export coverage and freshness"),
    NavItem("productivity", "Productivity", "▣", "PRD-03", "Deep work and focus"),
    NavItem("creative", "Creative", "✦", "CRV-04", "Writing and creative output"),
    NavItem("calendar", "Calendar", "▦", "CAL-05", "Schedule load and commitments"),
    NavItem("tasks", "Tasks", "✓", "TSK-05B", "Synced tasks across all areas"),
    NavItem("learning", "Learning", "❖", "LRN-06", "Study and skill acquisition"),
    NavItem("career", "Career", "▰", "CAR-11", "Role, trajectory and resilience"),
    NavItem("diploma", "Diploma", "✑", "DIP-12", "Modules, grades and readiness"),
    NavItem("projects", "Projects", "◈", "PRJ-08", "Momentum across initiatives"),
    NavItem("insights", "Insights", "✺", "INS-09", "Deterministic findings"),
    NavItem("settings", "Settings", "⚙", "SYS-10", "Sources, sync and security"),
]
