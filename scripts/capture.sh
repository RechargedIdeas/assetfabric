#!/usr/bin/env bash
# Record frames of a Game Zero scene with Godot Movie Maker (needs a GL context;
# uses xvfb-run when no $DISPLAY). Usage:
#   ./scripts/capture.sh <out_dir> <frames> [game user args...]
#   ./scripts/capture.sh /tmp/f1 240 --scene=sandbox --autoplay
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?out dir}"; FRAMES="${2:-240}"; shift 2 || true
GODOT_BIN="${GODOT_BIN:-$(command -v godot || echo "$ROOT/godot-bin/godot")}"
mkdir -p "$OUT"
RUN=("$GODOT_BIN" --path "$ROOT/games/game-zero" --rendering-driver opengl3 --write-movie "$OUT/frame.png" --fixed-fps 60 --quit-after "$FRAMES" -- "$@")
if [[ -z "${DISPLAY:-}" ]] && command -v xvfb-run >/dev/null; then
  xvfb-run -a -s "-screen 0 1280x720x24" "${RUN[@]}"
else
  "${RUN[@]}"
fi
echo "frames in $OUT"
