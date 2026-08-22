#!/bin/sh
# Rebuild the integration's brand icons from a source SVG.
#
#   ./build.sh              # rebuild the variant named in VARIANT below
#   ./build.sh band         # rebuild from icon-band.svg instead
#
# Output lands in the parent directory as icon.png (256x256) and icon@2x.png
# (512x512), which is where Home Assistant 2026.3+ looks for them. Nothing else
# reads these files, so switching variants is just a re-run plus a Core restart.
#
# Requires ImageMagick 7 built with the librsvg delegate. The internal MSVG
# renderer also handles these shapes, but librsvg is what was used to produce
# the committed PNGs.

set -e

VARIANT="${1:-v18}"

SRC="$(cd "$(dirname "$0")" && pwd)"
OUT="$(dirname "$SRC")"
SVG="$SRC/icon-$VARIANT.svg"

[ -f "$SVG" ] || { echo "no such variant: $SVG" >&2; exit 1; }

# Render well above target, then downscale with Lanczos. Rendering straight to
# 256 leaves the 12px strokes noticeably harsher on the circle.
MASTER="$(mktemp -t brandXXXXXX).miff"
trap 'rm -f "$MASTER"' EXIT INT TERM
magick -background none -density 768 "$SVG" -resize 2048x2048 "$MASTER"

for size in 256 512; do
    case "$size" in
        256) name="icon.png" ;;
        512) name="icon@2x.png" ;;
    esac
    # PNG32 keeps the pink from being flattened: ImageMagick will silently
    # re-encode as Grayscale otherwise on some intermediate steps.
    magick "$MASTER" -filter Lanczos -resize "${size}x${size}" \
        -strip -define png:compression-level=9 -colorspace sRGB \
        "PNG32:$OUT/$name"
    echo "$name  $(magick identify -format '%wx%h %[colorspace] %B bytes' "$OUT/$name")"
done

echo "built from icon-$VARIANT.svg"
