"""Module navigation model shared by the sidebar and the page stack."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str  # a glyph used as a lightweight icon (no asset dependency)
    subtitle: str


NAV_ITEMS: list[NavItem] = [
    NavItem("overview", "Overview", "◎", "Mission status across all systems"),
    NavItem("finance", "Finance", "▤", "Accounts, balances and spending"),
    NavItem("health", "Health", "✛", "Sleep, HRV and recovery"),
    NavItem("productivity", "Productivity", "▣", "Deep work and focus"),
    NavItem("creative", "Creative", "✦", "Writing and creative output"),
    NavItem("calendar", "Calendar", "▦", "Schedule load and commitments"),
    NavItem("learning", "Learning", "❖", "Study and skill acquisition"),
    NavItem("football", "Football", "⚽", "Matches, form and training"),
    NavItem("projects", "Projects", "◈", "Momentum across initiatives"),
    NavItem("insights", "Insights", "✺", "Deterministic findings"),
    NavItem("settings", "Settings", "⚙", "Sources, sync and security"),
]
