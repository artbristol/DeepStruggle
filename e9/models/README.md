# E9-A1-R1-S44 final model — 16B-step from-scratch self-play

Trained by NashPG self-play (documented E7 baseline recipe, seed 44) for 16,000,245,764
env steps in 4.77 days on a 2-core VM with an NVIDIA GPU (~3.1 GB VRAM used); final weights are a SWA over the last
10 snapshots. Full story, Elo curve, and caveats: `REPORT.md`.

| file | sha256 | bytes | what |
|---|---|---:|---|
| `swa_16B.pt` | `5c0f2679a7ce7ae910af687bc9c629b33963cfcb93668501dda0b89d0baeee8f` | 5,361,177 | final SWA checkpoint (PyTorch) |
| `E9-A1-R1-S44@16B-swa.onnx` | `83757ec03675d991ca775fe18f4e06178b4b1db9244c9c9b77bf35f84296e186` | 5,158,745 | ONNX export (browser-workbench-ready, self-describing metadata) |

**Provenance note:** trained on the pre-rule-bit engine (upstream `main` @ `7d3fd892`
+ the NATO/Solidarity action-mask fix that later merged as PR #33) — i.e. this network
predates the E8.1 `opp_event_gated` rule bit and plays E8-era rules. Anchored Elo
(E7-A4-R1-S44@4800M ≡ 1500, greedy): 1629 raw / 1652 SWA / **1751 with the rollout
root** `rollout(k=4, worlds=16, horizon=4, rule=z2)`; strongest published E8 checkpoint
measures 1684 in the same pool (head-to-head 57%–43%, ±10% CI per pairing).

Unlike upstream's convention (binaries on Hugging Face, hashes in
`leaderboard/networks.json`), the two files are checked in here for
self-containment — one-off experiment, exact bytes pinned by this branch's commit.
