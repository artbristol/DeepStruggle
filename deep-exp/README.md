# deep-exp/ — box-agnostic tooling for the from-scratch deep experiment

Branch provenance: `experiment/deep-from-scratch` = upstream `main` (7d3fd892) +
`fix/nato-event-prerequisite` (aeff2374, a validated action-mask rules fix with
regression tests) + this `deep-exp/` directory. No other changes to the engine.

| file | purpose |
|---|---|
| `RUNBOOK.md` | **Start here** — the full mission for a coding agent: bootstrap, validation gate, the deep recipe, watchdog/eval design, deliverables, hard rules |
| `env.example` | copy to `env.sh`, fill in paths; sourced by all scripts |
| `bootstrap-root.sh` | OS packages (run as root): clang, llvm, lld, g++ |
| `bootstrap-user.sh` | user-level: uv, Python 3.14 venv, CUDA torch, repo requirements, branch clone |
| `watchdog.sh` | tmux-loop watchdog: status log, auto-resume, pruning, milestone ladders + SWA |
| `run_ladder.sh` | anchored Bradley-Terry Elo ladder (anchor = E7@4800M ≡ 1500, greedy) |
| `monitor.py` | observation-only metric flags (entropy/EV/side-balance/KL/throughput) |

Anchors are public models from Hugging Face `mihaild/deepstruggle`; verify
sha256s against `leaderboard/networks.json` in the repo.

All scripts take paths from `env.sh` — nothing here hardcodes a host or user.
