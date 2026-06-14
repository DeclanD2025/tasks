# PyInstaller spec for ORION (macOS first; Windows/Linux later).
#
# Build a standalone .app bundle:
#     uv pip install -e ".[packaging]"
#     uv run pyinstaller packaging/orion.spec
#
# Output: dist/ORION.app (macOS). The app bundles Python, PySide6/Qt, and the
# ORION package. The local SQLite DB is created at runtime under the user's
# app-data directory — it is NOT bundled, so personal data never ships.
#
# Alternative: Briefcase (https://briefcase.readthedocs.io) gives nicer native
# installers per-OS; see README "Packaging" for the Briefcase route.

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = (
    collect_submodules("app.integrations")
    + collect_submodules("apscheduler")
    + ["pyqtgraph"]
)

a = Analysis(
    ["../app/main.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="ORION",
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="ORION")

app = BUNDLE(
    coll,
    name="ORION.app",
    icon=None,  # TODO: add app/ui/assets/orion.icns
    bundle_identifier="local.orion.app",
    info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
)
