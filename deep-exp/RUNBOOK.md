# RUNBOOK — from-scratch deep-architecture training run

You are a coding agent asked to run a **from-scratch deep-architecture** DeepStruggle
training experiment on this box. Work autonomously, log everything, leave artifacts
for review. This branch is downstream of `fix/nato-event-prerequisite` (a validated
rules fix; see `git log -1`). Engine sources are READ-ONLY for you — document any
suspected engine bug instead of patching.

## What this experiment is

Standard DeepStruggle recipes train shallow ladders (~1.5–2.3M params). This
experiment trains a **deep ladder from scratch with self-play** (no distillation,
no teacher): hidden 1024, 8 residual blocks, 512-wide input projections, A8
branch/play-mode heads — the A20 *architecture* without its `--policy-only`
distillation pipeline. The upstream repo's research logs record that deep trunks
doing RL need a smaller PPO clip (`research/`: "clip 0.1 bounded the deep trunk's
step", P39 arm 3) and a lower learning rate for wide trunks (2e-4 for 768-wide,
R84) — both are baked into the recipe below. **This recipe is unproven upstream**;
that is the point of the experiment. Expect possible instability and treat the
monitoring gates as binding.

## Step 0 — bootstrap

1. Root packages (ask the owner or run as root): `clang llvm lld g++` — see
   `deep-exp/bootstrap-root.sh`. The engine is clang-only; CMake refuses GCC.
   Ubuntu 24.04 works (clang 18); Debian 13 works (clang 19).
2. User-level: `deep-exp/bootstrap-user.sh <workspace-dir>` — installs uv, creates a
   Python 3.14 venv, installs `torch` CUDA wheels for this platform **first**, then
   the repo's `requirements.txt`, clones this branch. If you already have a venv,
   reuse it; just make sure `python -c "import torch; torch.cuda.is_available()"`.
3. Copy `deep-exp/env.example` to `deep-exp/env.sh`, fill in the paths (workspace, venv,
   anchors dir), and `source` it for every subsequent step.

## Step 1 — build + validation gate (binding; do not skip)

```
cmake -B build/release -S . -DPython_EXECUTABLE="$VENV_PY" -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j"$(nproc)"
./build/release/engine/ts_tests                 # expect 438 passed
./build/release/engine/ts_fuzz --games 10000    # expect clean
./build/release/engine/ts_fuzz_events
PYTHONPATH=.:build/release "$VENV_PY" -m pytest tests/engine_logic/test_observation_golden.py tests/bindings -x -q
bash tools/scripts/check_engine_fresh.sh
```

Then measure throughput: time 1M `step_flat` calls with random legal actions
(a ~20-line script; `bindings/ts_env.py` and `tools/scripts/bench_throughput.py`
may exist — prefer the repo's). Record steps/s. Deep trunks are GPU-heavier than
shallow ones; the measured number sizes the step budget in wall-clock terms.

## Step 2 — recipe

Two smoke variants, 3M steps each, then pick one and launch the main run.

```
DEEP="--arch ladder \
  --ladder-input-mode grouped --ladder-aggregation flatten \
  --ladder-entity-dim 16 --ladder-entity-proj-dim 512 \
  --ladder-hidden-dim 1024 --ladder-res-blocks 8 \
  --drop-static --per-entity-heads 64 \
  --ladder-head-context --ladder-head-static --ladder-head-entities country \
  --ladder-branch-head --ladder-play-mode-head"
DEEP_EXTRA="--clip-eps 0.1 --lr 2e-4"     # deep-trunk stability; verify exact
                                           # flag names in tools/README.md first
COMMON="--reward-scheme blunder_aware --opponent-frac 0.3 --opponent-self-pool \
  --opponent-pool-size 12 --eval-opponents heuristic random --ladder-head-center \
  --block-lambda off --rollout-temps 1.0 1.0 1.0 1.0"
```

- Variant A: `--batch-size 16384` (R48-style large minibatch).
- Variant B: default minibatch (4096).
- Verify every flag exists (`tools/train.py --help`, tools/README.md flag table)
  before launching; if a flag name differs, adapt and record the change.
- Smoke each in `$WORKSPACE/runs/SMOKE-deep-A` / `SMOKE-deep-B`; compare steps/s,
  early EV (want >0.6 by 3M), clip fraction (want <40%), entropy trend. Delete
  smoke dirs afterwards.
- If BOTH variants look unstable (EV collapsing, entropy crashing toward 0 within
  the smoke), fall back to `--ladder-hidden-dim 768 --ladder-res-blocks 4`
  (the A22-class architecture) with the same DEEP_EXTRA, note the deviation, and
  proceed — a stable 3M-param run beats a dead 20M-param one.

Main run:

```
"$VENV_PY" tools/train.py $DEEP $DEEP_EXTRA $COMMON --seed 44 \
  --train-steps 24000000000 --snapshot-every-steps 20000000 \
  --run-name E9-A19-R1-S44 --description "from-scratch deep ladder, hidden 1024 x 8 res blocks, 512 proj, A8 heads, clip 0.1 lr 2e-4" \
  --output-dir "$RUN_DIR"
```

Run-name grammar is `E<n>-A<n>-R<n>-S<n>` and the CLI requires the output dir's
basename to contain it. Environment: `TRITON_CACHE_DIR` somewhere writable,
`PYTHONPATH=.:build/release` (train.py sets `OMP_WAIT_POLICY=PASSIVE` itself).

**If another training run is already active on this box** (e.g. an `E9-A8-R1-S44`
E8-class run): stop it first — `tmux kill-session train` — unless the owner said
otherwise. Its snapshots remain on disk and stay ladder-able. One training per box.

## Step 3 — watchdog + evaluation (no root, no cron required)

Adapt `deep-exp/watchdog.sh` (env-driven) and run it in its own tmux window as a
`while true; …; sleep 300; done` loop. It must:

- append a status line every 5 min (steps, steps/s, entropy, EV, GPU util, disk free)
  to `$WORKSPACE/logs/watchdog.log`;
- restart training via `--resume "$RUN_DIR"` if the process dies and the step
  budget is unreached (only when `resume_state.pt` exists);
- prune `snapshot_*steps.pt` / `pool_*steps.pt` (keep newest 10 + every 5th);
- every 15 min, check `total_steps` against milestones {1B, 2B, 4B, 8B, 12B, 16B,
  20B, 24B} and, the first time each is crossed, run an anchored ladder
  (`deep-exp/run_ladder.sh`): Bradley-Terry Elo, anchor fixed at 1500, greedy
  (`--temperature 0`), 200 games/side, plus a second ladder of the SWA (weights
  averaged over the newest 10 snapshots via `tools/scripts/average_weights.py`).
  Marker files so each milestone runs once.

Anchor models (public, download once):
- `E7-A4-R1-S44@4800M` (anchor, Elo 1500) and `E8-A8-R1-S44@17520..17600M.onnx`
  (strongest published, ~1676) from Hugging Face `mihaild/deepstruggle`
  (paths listed in its `models.json`; verify sha256 against the repo's
  `leaderboard/networks.json` entries).
- `shallow_E7-02+03+04+05_1200M.onnx` (a 4-seed soup @1.2B, ~1470) is a useful
  extra curve point.

Also run the metric monitor every 15 min into `$WORKSPACE/eval/MONITOR.log` with
flags: entropy <0.3 sustained, EV <0.7 sustained, US self-play share <0.40 or
>0.60 sustained, KL >0.08, throughput <15k steps/s. **Observation only** — never
restart or alter training because of a metric flag; log loudly and continue.
Deep-trunk runs are expected to be touchier: if EV degrades persistently below
0.5 or entropy collapses under 0.15, write an URGENT note in
`$WORKSPACE/HANDOFF-REPORT.md` for the owner instead of acting.

## Deliverables

- `$WORKSPACE/HANDOFF-REPORT.md` — updated as you go: gate results, chosen smoke
  variant and why, final command line, throughput, watchdog/eval status, milestones
  as they land, any deviations from this runbook with reasons.
- `$WORKSPACE/notes/` — anything the owner must decide or do (root steps, branch
  changes, budget changes).
- Keep the training and watchdog tmux sessions alive; document the exact restart
  commands in the report so the owner can recover after a reboot.

## Hard rules

- No pushes to any remote. Engine sources read-only. No `apt-get update` if the
  owner says mirrors are degraded (plain `apt-get install` is fine).
- Public-repo hygiene does not apply to runtime files, but never write credentials
  into any file under the repo checkout.
