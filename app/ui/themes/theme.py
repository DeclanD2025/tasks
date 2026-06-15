"""ORION design system — the single source of truth for the dark, cinematic
mission-control / HUD look.

Defines the colour palette, typography, radii and a global Qt stylesheet (QSS).
Screens and components pull tokens from `Palette`/`Type` and apply
`build_stylesheet()` at app start. Keeping all visual tokens here means the
look can be re-skinned in one place.

Aesthetic: aerospace intelligence console — near-black with a faint teal/navy
undertone, cyan as the primary accent, sharp corners, thin technical borders,
mono-forward labels. Violet / orange / coral are reserved for *meaningful*
highlights only (severity, cross-domain links).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    # Backgrounds — near-black with a faint teal/navy undertone.
    bg_void: str = "#020509"          # window base — almost black
    bg_deep: str = "#04080e"          # rails / header base
    bg_panel: str = "#070d16"         # HUD panel fill
    bg_panel_alt: str = "#0a131f"     # raised inner fill
    bg_elevated: str = "#0e1a28"

    # Borders / grid — thin, cool.
    border: str = "#163040"           # panel borders (teal-tinted)
    border_soft: str = "#0e2330"
    grid: str = "#0a1a24"             # coordinate-grid lines
    scan: str = "#12404f"             # scanline / tick colour

    # Text.
    text: str = "#dff3f7"
    text_dim: str = "#7fa3b0"
    text_faint: str = "#4a6b78"

    # Accents — cyan primary; the rest meaningful-only.
    accent: str = "#2ee6ff"           # ORION cyan (primary)
    accent_dim: str = "#15a6c4"
    violet: str = "#a06bff"           # cross-domain links / secondary
    orange: str = "#ff9d3d"           # warnings / risk
    coral: str = "#ff5d7a"            # critical / alerts
    positive: str = "#3ad6a0"
    warning: str = "#ffb454"
    critical: str = "#ff5d7a"

    star: str = "#bfe9f2"


@dataclass(frozen=True)
class Radius:
    panel: int = 4      # sharp, technical
    inner: int = 3
    pill: int = 3


@dataclass(frozen=True)
class Type:
    family: str = "SF Pro Display, Inter, Segoe UI, Helvetica Neue, Arial, sans-serif"
    mono: str = "SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    display: int = 30
    h1: int = 20
    h2: int = 15
    body: int = 13
    small: int = 11
    micro: int = 10
    nano: int = 9


PALETTE = Palette()
RADIUS = Radius()
TYPE = Type()


def build_stylesheet() -> str:
    """Return the global QSS applied to the QApplication."""
    p = PALETTE
    r = RADIUS
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
    QToolTip {{
        background-color: {p.bg_elevated};
        color: {p.text};
        border: 1px solid {p.border};
    }}

    /* --- Technical sidebar (control rail) --- */
    #Sidebar {{
        background-color: {p.bg_deep};
        border-right: 1px solid {p.border_soft};
    }}
    QPushButton#NavButton {{
        text-align: left;
        padding: 8px 12px;
        border: 1px solid transparent;
        border-left: 2px solid transparent;
        border-radius: {r.inner}px;
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
        border-left: 2px solid {p.accent};
    }}

    /* --- Header / top bar --- */
    #TopBar {{
        background-color: {p.bg_deep};
        border-bottom: 1px solid {p.border_soft};
    }}
    #PageTitle {{ font-size: {TYPE.h1}px; font-weight: 600; letter-spacing: 1px; }}
    #PageSubtitle {{ color: {p.text_faint}; font-size: {TYPE.small}px; }}

    /* --- HUD panels --- */
    #HudPanel, #ChartPanel, #GlassPanel {{
        background-color: {p.bg_panel};
        border: 1px solid {p.border};
        border-radius: {r.panel}px;
    }}
    #PanelInner {{ background: transparent; }}

    /* Text roles */
    #CardLabel {{ color: {p.text_faint}; font-size: {TYPE.micro}px; letter-spacing: 2px; }}
    #ModuleCode {{ color: {p.accent_dim}; font-family: {TYPE.mono}; font-size: {TYPE.nano}px;
                   letter-spacing: 1px; }}
    #CardValue {{ color: {p.text}; font-size: 24px; font-weight: 700; }}
    #BigValue {{ color: {p.text}; font-size: 30px; font-weight: 700; }}
    #DeltaUp {{ color: {p.positive}; font-size: {TYPE.small}px; }}
    #DeltaDown {{ color: {p.critical}; font-size: {TYPE.small}px; }}
    #DeltaFlat {{ color: {p.text_faint}; font-size: {TYPE.small}px; }}
    #PanelTitle {{ font-size: {TYPE.small}px; font-weight: 700; color: {p.text};
                   letter-spacing: 2px; }}
    #Mono {{ font-family: {TYPE.mono}; color: {p.text_dim}; font-size: {TYPE.nano}px;
             letter-spacing: 1px; }}
    #Muted {{ color: {p.text_dim}; }}
    #Faint {{ color: {p.text_faint}; }}

    /* --- Inputs (login) --- */
    QLineEdit {{
        background-color: {p.bg_panel_alt};
        border: 1px solid {p.border};
        border-radius: {r.inner}px;
        padding: 11px 13px;
        color: {p.text};
        selection-background-color: {p.accent_dim};
    }}
    QLineEdit:focus {{ border: 1px solid {p.accent}; }}

    /* Spin box — match the HUD line inputs, no native chrome */
    QSpinBox {{
        background-color: {p.bg_panel_alt};
        border: 1px solid {p.border};
        border-radius: {r.inner}px;
        padding: 6px 8px;
        color: {p.text};
        font-family: {TYPE.mono};
        selection-background-color: {p.accent_dim};
    }}
    QSpinBox:focus {{ border: 1px solid {p.accent}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 16px;
        border-left: 1px solid {p.border};
        background-color: {p.bg_elevated};
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; border-bottom: 1px solid {p.border}; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color: {p.border}; }}
    QSpinBox::up-arrow {{
        image: none; width: 0; height: 0;
        border-left: 3px solid transparent; border-right: 3px solid transparent;
        border-bottom: 4px solid {p.accent};
    }}
    QSpinBox::down-arrow {{
        image: none; width: 0; height: 0;
        border-left: 3px solid transparent; border-right: 3px solid transparent;
        border-top: 4px solid {p.accent};
    }}

    QPushButton#PrimaryButton {{
        background-color: {p.accent};
        color: #021016;
        border: none;
        border-radius: {r.inner}px;
        padding: 12px 18px;
        font-weight: 700;
        letter-spacing: 3px;
    }}
    QPushButton#PrimaryButton:hover {{ background-color: #5cf0ff; }}
    QPushButton#GhostButton {{
        background-color: {p.bg_panel_alt};
        border: 1px solid {p.border};
        border-radius: {r.inner}px;
        padding: 7px 13px;
        color: {p.text_dim};
        font-family: {TYPE.mono};
        font-size: {TYPE.small}px;
    }}
    QPushButton#GhostButton:hover {{ color: {p.accent}; border-color: {p.accent}; }}

    /* --- Scroll --- */
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.accent_dim}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    /* --- Pills / status chips --- */
    #Pill {{
        background-color: {p.bg_elevated};
        border: 1px solid {p.border};
        border-radius: {r.pill}px;
        color: {p.text_dim};
        padding: 2px 8px;
        font-family: {TYPE.mono};
        font-size: {TYPE.nano}px;
        letter-spacing: 1px;
    }}
    """
