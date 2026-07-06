#!/usr/bin/env bash
# Build the double-clickable macOS app bundle for ORION.
#
#   ./packaging/build_macos.sh
#
# Produces dist/ORION.app. Optionally copies it into /Applications when run
# with `--install`.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing packaging dependencies"
uv pip install -e ".[dev]" "pyinstaller>=6.8" >/dev/null

echo "==> Building dist/ORION.app"
uv run pyinstaller packaging/orion.spec --noconfirm \
  --distpath dist --workpath build/pyi

echo "==> Built: $(pwd)/dist/ORION.app"

if [[ -n "${ORION_CODESIGN_IDENTITY:-}" ]]; then
  echo "==> Signing dist/ORION.app with CloudKit entitlements"
  codesign --force --deep --options runtime \
    --entitlements packaging/orion.mac.entitlements \
    --sign "$ORION_CODESIGN_IDENTITY" \
    dist/ORION.app
fi

if [[ "${1:-}" == "--install" ]]; then
  rm -rf /Applications/ORION.app
  cp -R dist/ORION.app /Applications/ORION.app
  echo "==> Installed to /Applications/ORION.app"
fi

echo "Done. Double-click dist/ORION.app (or /Applications/ORION.app) to launch."
