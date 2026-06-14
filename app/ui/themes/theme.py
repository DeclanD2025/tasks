"""ORION design system — the single source of truth for the dark, futuristic
intelligence-dashboard look.

Defines the colour palette, typography, spacing and a global Qt stylesheet
(QSS). Screens and components pull tokens from `Palette`/`Type` and apply
`build_stylesheet()` at app start. Keeping all visual tokens here means the
look can be re-skinned in one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    # Backgrounds — near-black with a deep violet/indigo undertone (matches the
    # ORION icon). Darker and moodier than before.
    bg_void: str = "#04030a"          # window base — almost black
    bg_deep: str = "#070512"          # panels base
    bg_panel: str = "#0a0818"         # glass panel fill
    bg_panel_alt: str = "#0e0b20"     # raised card
    bg_elevated: str = "#140f2b"

    # Borders / grid — thin, cool violet.
    border: str = "#241a3f"
    border_soft: str = "#19122e"
    grid: str = "#0c0a1a"

    # Text.
    text: str = "#ece8fb"
    text_dim: str = "#9b93c4"
    text_faint: str = "#5a527e"

    # Soft neon accents — violet primary (icon), cyan + coral secondaries.
    accent: str = "#a26bff"           # ORION violet (primary)
    accent_2: str = "#3fd2ff"         # cyber cyan
    accent_3: str = "#ff6b8a"         # coral (from the icon's red nodes)
    positive: str = "#3ad6a0"
    warning: str = "#ffb454"
    critical: str = "#ff5d7a"

    star: str = "#d9d2ff"


@dataclass(frozen=True)
class Type:
    family: str = "SF Pro Display, Inter, Segoe UI, Helvetica Neue, Arial, sans-serif"
    mono: str = "SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    display: int = 30
    h1: int = 21
    h2: int = 16
    body: int = 13
    small: int = 11
    micro: int = 10


PALETTE = Palette()
TYPE = Type()


def build_stylesheet() -> str:
    """Return the global QSS applied to the QApplication."""
    p = PALETTE
    return f"""
    QWidget {{
        background: transparent;
        color: {p.text};
        font-family: {TYPE.family};
        font-size: {TYPE.body}px;
    }}
    QMainWindow, #RootWindow {{
        background-color: {p.bg_void};
    }}

    /* Sidebar */
    #Sidebar {{
        background-color: {p.bg_deep};
        border-right: 1px solid {p.border_soft};
    }}
    #SidebarBrand {{
        color: {p.text};
        font-size: {TYPE.h1}px;
        font-weight: 700;
        letter-spacing: 6px;
    }}
    #SidebarTagline {{
        color: {p.text_faint};
        font-size: {TYPE.micro}px;
        letter-spacing: 2px;
    }}
    QPushButton#NavButton {{
        text-align: left;
        padding: 9px 14px;
        border: 1px solid transparent;
        border-radius: 9px;
        color: {p.text_dim};
        font-size: {TYPE.body}px;
    }}
    QPushButton#NavButton:hover {{
        background-color: {p.bg_panel};
        color: {p.text};
    }}
    QPushButton#NavButton:checked {{
        background-color: {p.bg_panel_alt};
        color: {p.accent};
        border: 1px solid {p.border};
    }}

    /* Top bar */
    #TopBar {{
        background-color: {p.bg_deep};
        border-bottom: 1px solid {p.border_soft};
    }}
    #PageTitle {{ font-size: {TYPE.h1}px; font-weight: 600; }}
    #PageSubtitle {{ color: {p.text_faint}; font-size: {TYPE.small}px; }}

    /* Glass panels / cards */
    #GlassPanel, #MetricCard, #ModuleCard, #InsightCard, #ChartPanel {{
        background-color: {p.bg_panel};
        border: 1px solid {p.border};
        border-radius: 14px;
    }}
    #CardLabel {{ color: {p.text_faint}; font-size: {TYPE.micro}px; letter-spacing: 2px; }}
    #CardValue {{ color: {p.text}; font-size: 26px; font-weight: 700; }}
    #DeltaUp {{ color: {p.positive}; font-size: {TYPE.small}px; }}
    #DeltaDown {{ color: {p.critical}; font-size: {TYPE.small}px; }}
    #DeltaFlat {{ color: {p.text_faint}; font-size: {TYPE.small}px; }}

    #PanelTitle {{ font-size: {TYPE.h2}px; font-weight: 600; color: {p.text}; }}
    #Muted {{ color: {p.text_dim}; }}
    #Faint {{ color: {p.text_faint}; }}

    /* Inputs (login) */
    QLineEdit {{
        background-color: {p.bg_panel_alt};
        border: 1px solid {p.border};
        border-radius: 9px;
        padding: 11px 13px;
        color: {p.text};
        selection-background-color: {p.accent_2};
    }}
    QLineEdit:focus {{ border: 1px solid {p.accent}; }}

    QPushButton#PrimaryButton {{
        background-color: {p.accent};
        color: #0a0414;
        border: 1px solid {p.accent_3};
        border-radius: 9px;
        padding: 12px 18px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QPushButton#PrimaryButton:hover {{ background-color: #b888ff; border-color: {p.accent}; }}
    QPushButton#GhostButton {{
        background-color: {p.bg_panel_alt};
        border: 1px solid {p.border};
        border-radius: 9px;
        padding: 8px 14px;
        color: {p.text_dim};
    }}
    QPushButton#GhostButton:hover {{ color: {p.text}; border-color: {p.accent}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    #Pill {{
        background-color: {p.bg_elevated};
        border: 1px solid {p.border};
        border-radius: 10px;
        color: {p.text_dim};
        padding: 3px 9px;
        font-size: {TYPE.micro}px;
    }}
    """
