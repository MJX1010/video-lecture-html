#!/usr/bin/env bash
# Example: dry-run then slides-only on one file
set -euo pipefail
VIDEO="${1:?usage: quickstart.sh /path/to/talk.mp4}"
OUT="${2:-./out_demo}"
vlh process "$VIDEO" -o "$OUT" --dry-run --site-title "Demo"
echo "Open $OUT/index.html"
