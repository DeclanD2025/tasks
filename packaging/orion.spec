# PyInstaller spec for ORION (macOS first; Windows/Linux later).
#
# Build a standalone, double-clickable .app bundle:
#     uv pip install -e ".[packaging]"
#     uv run pyinstaller packaging/orion.spec --noconfirm
#
# Output: dist/ORION.app (macOS). The app bundles Python, PySide6/Qt, and the
# ORION package. The local SQLite DB is created at runtime under the user's
# app-data directory — it is NOT bundled, so personal data never ships.
#
# Alternative: Briefcase (https://briefcase.readthedocs.io) gives nicer native
# installers per-OS; see README "Packaging" for the Briefcase route.

# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Resolve the project root from the spec location so the build works no matter
# which directory PyInstaller is invoked from.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(ROOT, "app", "main.py")
ICON = os.path.join(ROOT, "app", "ui", "assets", "orion.icns")
ICON = ICON if os.path.exists(ICON) else None
ASSETS = os.path.join(ROOT, "app", "ui", "assets")
DATAS = [(ASSETS, "app/ui/assets")] if os.path.exists(ASSETS) else []

hidden = (
    collect_submodules("app")
    + collect_submodules("app.integrations")
    + collect_submodules("apscheduler")
    + ["pyqtgraph"]
)

# pyobjc framework bindings for the Apple Calendar (EventKit) integration.
# Without these the frozen app cannot ``import EventKit`` — calendar access is
# silently unavailable and falls back to mock events. pyobjc frameworks ship
# bridgesupport *data* files that the lazy loader needs, so collect_all (not
# just submodules) is required. Foundation/CoreFoundation back NSDate usage.
pyobjc_datas = []
pyobjc_binaries = []
for _framework in ("EventKit", "Foundation", "CoreFoundation", "objc"):
    _d, _b, _h = collect_all(_framework)
    pyobjc_datas += _d
    pyobjc_binaries += _b
    hidden += _h

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=pyobjc_binaries,
    datas=DATAS + pyobjc_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ORION",
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="ORION")

app = BUNDLE(
    coll,
    name="ORION.app",
    icon=ICON,
    bundle_identifier="com.declandundas.orion.mac",
    info_plist={
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Required for macOS to show the calendar-access prompt (TCC). Without
        # these, EventKit access is silently denied and no dialog appears.
        # NSCalendarsUsageDescription covers macOS <= 13; the FullAccess key is
        # the macOS 14+ (Sonoma) replacement — we ship both for compatibility.
        "NSCalendarsUsageDescription": (
            "ORION reads your iCloud calendar to show your schedule alongside "
            "your other life data. It never edits or shares your calendar."
        ),
        "NSCalendarsFullAccessUsageDescription": (
            "ORION reads your iCloud calendar to show your schedule alongside "
            "your other life data. It never edits or shares your calendar."
        ),
    },
)
