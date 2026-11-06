#!/usr/bin/env bash
# Godot headless smoke for Game Zero (F0).
# Usage: ./scripts/smoke_godot.sh
# If Godot is not installed, exits 0 after structure check with a notice
# when ALLOW_STRUCTURE_ONLY=1 (default). Set REQUIRE_GODOT=1 to fail hard.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="$ROOT/games/game-zero"
REQUIRE_GODOT="${REQUIRE_GODOT:-0}"
ALLOW_STRUCTURE_ONLY="${ALLOW_STRUCTURE_ONLY:-1}"

if [[ ! -f "$PROJECT/project.godot" ]]; then
  echo "FAIL: missing project.godot"
  exit 1
fi

# Structure parse (Python, no Godot required)
"$ROOT/.venv/bin/python" - <<'PY' "$PROJECT/project.godot"
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
assert "config_version=5" in text
assert 'renderer/rendering_method="gl_compatibility"' in text
assert "[application]" in text
print("structure OK (Compatibility renderer)")
PY

GODOT_BIN="${GODOT_BIN:-}"
if [[ -z "$GODOT_BIN" ]]; then
  for c in godot godot4 Godot; do
    if command -v "$c" >/dev/null 2>&1; then
      GODOT_BIN="$(command -v "$c")"
      break
    fi
  done
fi
# Local download location used by bootstrap
if [[ -z "$GODOT_BIN" && -x "$ROOT/godot-bin/godot" ]]; then
  GODOT_BIN="$ROOT/godot-bin/godot"
fi

if [[ -z "$GODOT_BIN" ]]; then
  echo "Godot binary not found on PATH or godot-bin/."
  echo "Documented command:"
  echo "  godot --path games/game-zero --headless --quit-after 1"
  if [[ "$REQUIRE_GODOT" == "1" ]]; then
    exit 1
  fi
  if [[ "$ALLOW_STRUCTURE_ONLY" == "1" ]]; then
    echo "ALLOW_STRUCTURE_ONLY=1 — accepting structure smoke for F0."
    exit 0
  fi
  exit 1
fi

echo "Using Godot: $GODOT_BIN"
"$GODOT_BIN" --path "$PROJECT" --headless --quit-after 1
echo "headless smoke OK"
