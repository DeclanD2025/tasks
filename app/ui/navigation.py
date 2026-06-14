"""Module navigation model shared by the sidebar and the page stack."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str    # a glyph used as a lightweight icon (no asset dependency)
    code: str    # technical module ID, e.g. "FIN-01"
    subtitle: str


NAV_ITEMS: list[NavItem] = [
    NavItem("overview", "Overview", "◎", "OVW-00", "Mission status across all systems"),
    NavItem("finance", "Finance", "▤", "FIN-01", "Accounts, balances and spending"),
    NavItem("health", "Health", "✛", "HLT-02", "Sleep, HRV and recovery"),
    NavItem("productivity", "Productivity", "▣", "PRD-03", "Deep work and focus"),
    NavItem("creative", "Creative", "✦", "CRV-04", "Writing and creative output"),
    NavItem("calendar", "Calendar", "▦", "CAL-05", "Schedule load and commitments"),
    NavItem("learning", "Learning", "❖", "LRN-06", "Study and skill acquisition"),
    NavItem("football", "Football", "⚽", "FBL-07", "Matches, form and training"),
    NavItem("projects", "Projects", "◈", "PRJ-08", "Momentum across initiatives"),
    NavItem("insights", "Insights", "✺", "INS-09", "Deterministic findings"),
    NavItem("settings", "Settings", "⚙", "SYS-10", "Sources, sync and security"),
]
