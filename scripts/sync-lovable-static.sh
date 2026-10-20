#!/usr/bin/env bash
# Build frontend-reimagined (TanStack Start SPA) into src/clawhouse/static for FastAPI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UI="$ROOT/frontend-reimagined"
DEST="$ROOT/src/clawhouse/static"

cd "$UI"
if command -v bun >/dev/null 2>&1; then
  bun install
  bun run build
else
  npm install
  npm run build
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$UI/.output/public/." "$DEST/"
cp "$DEST/_shell.html" "$DEST/index.html"
rm -f "$DEST/_headers"
# Prerender embeds a per-build hydration timestamp; normalize so CI drift checks are stable.
python3 - "$DEST" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
for name in ("index.html", "_shell.html"):
    path = root / name
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"u:\d+", "u:0", text)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
PY

echo "Synced Lovable SPA static bundle to $DEST"
