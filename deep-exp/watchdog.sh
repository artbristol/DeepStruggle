#!/bin/bash
# Training watchdog + milestone ladders + metric monitor, all in one loop.
# Run inside its own tmux window:  tmux new-session -d -s watchdog 'bash deep-exp/watchdog.sh'
# Requires deep-exp/env.sh sourced. No root, no cron needed.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[ -f "$HERE/env.sh" ] && source "$HERE/env.sh"
mkdir -p "$WORKSPACE/logs" "$WORKSPACE/eval" "$WORKSPACE/eval/milestones"
LOG="$WORKSPACE/logs/watchdog.log"
MILESTONES=(1000000000 2000000000 4000000000 8000000000 12000000000 16000000000 20000000000 24000000000)

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
last_metric() {
  "$VENV_PY" - "$RUN_DIR/training_metrics.jsonl" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], "rb") as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 65536))
        rows = [l for l in f.read().splitlines() if l.strip()]
    d = json.loads(rows[-1])
    print(d.get("total_steps", 0))
except Exception:
    print(0)
PYEOF
}

while true; do
  STEPS=$(last_metric)
  METRIC=$(tail -1 "$RUN_DIR/training_metrics.jsonl" 2>/dev/null | "$VENV_PY" -c "
import json,sys
try:
    d=json.loads(sys.stdin.read())
    print(f\"steps={d.get('total_steps',0)} sps={d.get('steps_per_sec_avg',0)} ent={d.get('entropy',-1)} ev={d.get('explained_variance', d.get('ev',-1))}\")
except Exception: print('no-metrics')" 2>/dev/null)
  GPU=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null || echo "n/a")
  DISK=$(df -h "$WORKSPACE" | tail -1 | awk '{print $4" free"}')
  echo "$(ts) status | ${METRIC:-no-metrics} | gpu=$GPU | $DISK" >> "$LOG"

  # ---- liveness: restart on death unless budget reached ----
  if ! pgrep -f "tools/train.py" > /dev/null 2>&1; then
    if [ "${STEPS:-0}" -ge "$TRAIN_BUDGET" ]; then
      echo "$(ts) training complete at $STEPS steps; not restarting" >> "$LOG"
    else
      echo "$(ts) TRAINING DOWN at ${STEPS:-unknown}; restarting" >> "$LOG"
      if [ -f "$RUN_DIR/resume_state.pt" ]; then RESUME="--resume $RUN_DIR"; else RESUME=""; rm -rf "$RUN_DIR"; fi
      tmux kill-session -t train 2>/dev/null
      tmux new-session -d -s train "cd '$REPO_DIR' && TRITON_CACHE_DIR='$WORKSPACE/scratch/triton' \
        PYTHONPATH='$PYTHONPATH' '$VENV_PY' tools/train.py \
        --arch ladder --ladder-input-mode grouped --ladder-aggregation flatten \
        --ladder-entity-dim 16 --ladder-entity-proj-dim 512 --ladder-hidden-dim 1024 --ladder-res-blocks 8 \
        --drop-static --per-entity-heads 64 --ladder-head-context --ladder-head-static --ladder-head-entities country \
        --ladder-branch-head --ladder-play-mode-head --clip-eps 0.1 --lr 2e-4 \
        --reward-scheme blunder_aware --opponent-frac 0.3 --opponent-self-pool --opponent-pool-size 12 \
        --eval-opponents heuristic random --ladder-head-center --block-lambda off --rollout-temps 1.0 1.0 1.0 1.0 \
        --seed 44 --train-steps $TRAIN_BUDGET --snapshot-every-steps $SNAPSHOT_EVERY \
        --run-name E9-A19-R1-S44 --output-dir '$RUN_DIR' $RESUME 2>&1 | tee -a '$WORKSPACE/logs/main.log'"
      echo "$(ts) restart issued (resume=${RESUME:-fresh})" >> "$LOG"
    fi
  fi

  # ---- milestone ladders (once each) + SWA variant ----
  for M in "${MILESTONES[@]}"; do
    LABEL="$((M / 1000000000))B"
    [ "${STEPS:-0}" -ge "$M" ] || continue
    [ -f "$WORKSPACE/eval/milestones/$LABEL.done" ] && continue
    touch "$WORKSPACE/eval/milestones/$LABEL.done"
    echo "$(ts) milestone $LABEL crossed at steps=${STEPS:-?}" >> "$LOG"
    "$HERE/run_ladder.sh" --tag "milestone_$LABEL" >> "$LOG" 2>&1 || true
    SWA_OUT="$RUN_DIR/swa_$LABEL.pt"
    SNAPS=$(ls -1t "$RUN_DIR"/snapshot_*steps.pt 2>/dev/null | head -10 | sort)
    if [ -n "$SNAPS" ]; then
      nice -n 19 "$VENV_PY" "$REPO_DIR/tools/scripts/average_weights.py" --snapshots $SNAPS --output "$SWA_OUT" >> "$LOG" 2>&1 || true
      "$HERE/run_ladder.sh" --snapshot "$SWA_OUT" --tag "milestone_${LABEL}_swa" >> "$LOG" 2>&1 || true
    fi
  done

  # ---- snapshot / pool pruning: keep newest 10 + every 5th ----
  for pat in "snapshot_*steps.pt" "pool_*steps.pt"; do
    ls -1t "$RUN_DIR"/$pat 2>/dev/null | tail -n +11 | while read -r f; do
      n=$(echo "$f" | grep -oE '[0-9]+' | head -1)
      if [ $((n / SNAPSHOT_EVERY % 5)) -ne 0 ]; then rm -f "$f"; fi
    done
  done

  sleep 300
done
