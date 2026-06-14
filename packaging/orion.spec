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
from PyInstaller.utils.hooks import collect_submodules

# Resolve the project root from the spec location so the build works no matter
# which directory PyInstaller is invoked from.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(ROOT, "app", "main.py")
ICON = os.path.join(ROOT, "app", "ui", "assets", "orion.icns")
ICON = ICON if os.path.exists(ICON) else None

hidden = (
    collect_submodules("app")
    + collect_submodules("app.integrations")
    + collect_submodules("apscheduler")
    + ["pyqtgraph"]
)

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[(ICON, "app/ui/assets")] if ICON else [],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="ORION",
    console=False, disable_windowed_traceback=False, icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="ORION")

app = BUNDLE(
    coll,
    name="ORION.app",
    icon=ICON,
    bundle_identifier="local.orion.app",
    info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
)
