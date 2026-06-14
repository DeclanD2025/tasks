#!/usr/bin/env bash
# Generate app/ui/assets/orion.icns from a square source PNG.
#
#   ./packaging/make_icon.sh [source.png]
#
# Defaults to app/ui/assets/orion_source.png. Produces the full macOS iconset
# (16..1024, @1x/@2x) and compiles it to orion.icns via iconutil.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:-app/ui/assets/orion_source.png}"
OUT="app/ui/assets/orion.icns"
ICONSET="build/orion.iconset"

[[ -f "$SRC" ]] || { echo "Source not found: $SRC" >&2; exit 1; }

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# size:filename pairs required by iconutil.
for spec in \
  16:icon_16x16.png 32:icon_16x16@2x.png \
  32:icon_32x32.png 64:icon_32x32@2x.png \
  128:icon_128x128.png 256:icon_128x128@2x.png \
  256:icon_256x256.png 512:icon_256x256@2x.png \
  512:icon_512x512.png 1024:icon_512x512@2x.png ; do
  size="${spec%%:*}"; name="${spec##*:}"
  sips -z "$size" "$size" "$SRC" --out "$ICONSET/$name" >/dev/null
done

iconutil -c icns "$ICONSET" -o "$OUT"
echo "==> Wrote $OUT"
