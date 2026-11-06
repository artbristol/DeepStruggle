#!/bin/bash
# Anchored Elo ladder for a snapshot. Usage: run_ladder.sh [--snapshot PATH.pt] [--tag TAG]
# Requires deep-exp/env.sh sourced. Anchor fixed at 1500; greedy play.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[ -f "$HERE/env.sh" ] && source "$HERE/env.sh"

SNAPSHOT="${2:-}"
TAG="${4:-ladder}"
if [ -z "$SNAPSHOT" ]; then
  SNAPSHOT=$(ls "$RUN_DIR"/snapshot_*steps.pt 2>/dev/null | grep -v '/snapshot_0s\.pt$' | \
    sed -n 's/^\(.*snapshot_\)\([0-9][0-9]*\)steps\.pt$/\2 \1\2steps.pt/p' | sort -n | tail -1 | cut -d' ' -f2-)
  [ -n "$SNAPSHOT" ] || { echo "no snapshot found in $RUN_DIR" >&2; exit 1; }
fi
SNAP_LABEL="E9-deep@$(basename "$SNAPSHOT" | sed 's/snapshot_//; s/steps\.pt//')s"
OUT="$WORKSPACE/eval/ladders/$(date -u +%Y%m%dT%H%M%SZ)_$TAG"
mkdir -p "$OUT"

ANCHOR="$ANCHORS_DIR/E7-A4-R1-S44@4800M.pt"
PUBLISHED="$ANCHORS_DIR/E8-A8-R1-S44@17520..17600M.onnx"
[ -f "$ANCHOR" ] || { echo "missing anchor $ANCHOR — download from HF mihaild/deepstruggle" >&2; exit 1; }

nice -n 19 env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  OMP_WAIT_POLICY=PASSIVE PYTHONPATH="$PYTHONPATH" \
  "$VENV_PY" "$REPO_DIR/tools/tournament.py" \
  --models "name:$SNAP_LABEL:$SNAPSHOT" "name:E7anchor@4800M:$ANCHOR" \
  ${PUBLISHED:+name:E8strong:$PUBLISHED} heuristic random \
  --games-per-side "${LADDER_GAMES_PER_SIDE:-200}" --base-seed 20261106 \
  --temperature 0 --device cpu --pack-pairs 25 \
  --anchor-model E7anchor@4800M --anchor-elo 1500.0 \
  --output-report "$OUT/report.md" --output-json "$OUT/results.json" \
  > "$OUT/stdout.log" 2>&1
echo "$(date -u +%FT%TZ) ladder $TAG done: $(python3 -c "import json;r=json.load(open('$OUT/results.json'));print({k:round(v,1) for k,v in r['elo_ratings'].items()})")" >> "$WORKSPACE/eval/LADDER.log"
