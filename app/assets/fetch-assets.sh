#!/bin/sh
# Download every asset referenced by the compiled Vanilla CSS (Ubuntu web
# fonts), plus the Canonical logo, from assets.ubuntu.com into the given
# directory, so they can be served by the app itself.
#
# assets.ubuntu.com is unreliable, so every file is retried aggressively and
# the script fails (failing the image build) if any file is still missing:
# better a failed build than an image with broken fonts.
#
# Usage: fetch-assets.sh <compiled-css> <output-dir>
set -eu

CSS="$1"
OUT="$2"
BASE_URL="${ASSETS_BASE_URL:-https://assets.ubuntu.com/v1}"
LOGO="82818827-CoF_white.svg"

mkdir -p "$OUT"

# Files referenced by the CSS as url("/static/vendor/<file>")
FILES="$(grep -oE '/static/vendor/[^")?#]+' "$CSS" | sed 's#^/static/vendor/##' | sort -u) $LOGO"

for f in $FILES; do
    echo "Fetching $f"
    curl -fsSL \
        --retry 10 --retry-all-errors --retry-delay 3 \
        --connect-timeout 10 --max-time 60 \
        -o "$OUT/$f" "$BASE_URL/$f"
    [ -s "$OUT/$f" ] || { echo "ERROR: $f is empty" >&2; exit 1; }
done

echo "Fetched $(echo $FILES | wc -w) asset(s) into $OUT"
