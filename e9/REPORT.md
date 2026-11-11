# Twilight Struggle ML training — final report

**Date:** 2026-11-11 · **VM:** a 2-core VM, an NVIDIA GPU (~3.1 GB VRAM used), 26GB RAM · **Run:** `E9-A1-R1-S44` @ 16,000,245,764 steps

## Result

A from-scratch NashPG self-play model that, with play-time search, **measures above the strongest published DeepStruggle checkpoint** on our anchored ladder:

| entrant | Elo (anchor E7@4800M = 1500) |
|---|---:|
| **E9-swa16B + rollout root (k=4, w=16, h=4, z2)** | **1750.7** |
| E8 strongest published (17.6B steps) | 1684.1 |
| E9-swa16B + gumbel(64,8) | 1666.4 |
| E9-swa16B greedy | 1629.1 |
| E9 raw @16B (no SWA) | 1500.6 → 1629.0 at final |

Head-to-head vs E8-strongest: **57%–43%** (100 games, ±10% CI). Search delta in-pool: **+122 Elo** (rollout vs greedy), within the upstream-documented +40–140 band. All tournament numbers greedy (`--temperature 0`), 50–200 games/side, Bradley-Terry anchored at 1500.

**Caveats:** per-pairing CI at these game counts is ±8–35 Elo depending on count; the Elo scale is ladder-internal (anchored to the E7 checkpoint), not human-Elo comparable. "Matches or exceeds the published frontier" is the defensible claim; the precise 1751 is a point estimate.

## Method

- **Engine:** DeepStruggle (mihaild), pinned `7d3fd892`. **Validated against a pre-AI (2020) reference engine** (glowsplint/twilight-struggle-py @ `a30ad14`) per the owner's mandate: 600 mirrored games with forced deals + shared dice streams → 98.1% identical legal-move sets, 0 invariant violations in 186k decisions, 45-case scenario battery. Findings: 2 engine bugs — (1) phantom US +2 setup handicap → **withdrawn** after the owner ruled it the tournament-standard balance rule (community record agrees); (2) NATO/Solidarity opponent-event gating → **shipped upstream as PR #33 (merged)**; the maintainer re-engineered it as a per-seat rule bit (E8.1, default-on for new networks).
- **Training:** NashPG (PPO + KL to periodically refreshed reference + opponent pool of 12 snapshots, frac 0.3), documented E7 baseline recipe, seed 44, blunder-aware reward, no search in the training loop. 16B env steps in 4.77 days at ~39k steps/s (GPU-bound at ~1.6 cores of the 2 available; zero crashes, zero manual interventions).
- **Evaluation hygiene:** fixed anchor, greedy eval, milestone ladders at 1/2/4/8/12/16B with SWA (weight-average of newest 10 snapshots) at each; search deltas measured in-pool, not across pools. Two silent tooling bugs found and fixed en route: milestone list integer-division (12B/16B ladders unreachable), final-metrics eval-row parser (watchdog would have "restarted" the finished run).

## Artifacts

| artifact | path |
|---|---|
| Final model (SWA, PyTorch) | `/data/runs/E9-A1-R1-S44-main/swa_16B.pt` |
| Final model (ONNX, workbench-ready) | `/data/eval/E9-A1-R1-S44@16B-swa.onnx` |
| Run dir (snapshots every 20M, TensorBoard, metrics) | `/data/runs/E9-A1-R1-S44-main/` |
| All ladder reports | `/data/eval/ladders/`, final search: `/data/eval/search/report.md` |
| Validation dossier + harness | `/data/repos/ts-validation/VALIDATION-REPORT.md` (+ drivers, canon.py, patches) |
| Tooling (watchdog, ladders, monitor) | `/data/scripts/watchdog.sh`, `/data/eval/` |
| Upstream contributions | fork `artbristol/DeepStruggle`: `fix/nato-event-prerequisite` (merged as PR #33), `experiment/deep-from-scratch` (runbook + tooling for the owner's deep experiment) |

## Follow-ups (not done)

- **Deep-architecture experiment** (`experiment/deep-from-scratch` branch): runbook + box-agnostic tooling for a from-scratch ~20M-param deep-ladder run, ready for any agent to execute.
- **Vassal showcase bot**: headless bridge + differential harness exist (`/data/repos/vassal-oracle/`); the bot itself (driving the rules-enforced module via command logs) is unbuilt — estimated 2.5–3 weeks per the bridge report.
- Human-corpus behavioral cloning and longer SWA/soup windows were skipped (measured neutral-to-negative upstream).
