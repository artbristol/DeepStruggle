#!/usr/bin/env python3
"""repro_setup_bonus.py -- minimal repro for DS-1 (US +2 setup handicap).

Walks DeepStruggle's setup with the lowest-legal-action policy and prints the
decision sequence. Per rules/rules.md §3 and the Twilight Struggle Deluxe
rulebook, the setup is EXACTLY: USSR places 6 influence in Eastern Europe,
US places 7 influence in Western Europe, then the Headline Phase begins.

DeepStruggle (pinned 7d3fd89) instead asks the US for TWO MORE placements
("Stage 1: 2 bonus influence in any country with existing US influence",
engine/src/state_machine.cpp ~line 976) -- the reference engine's default
handicap=-2 baked into the engine with no way to turn it off (init_game takes
only a seed). The pre-AI reference driver explicitly uses handicap=0.

Expected (correct): 13 setup POINT_NODE decisions, then SELECT_CARD (US headline).
Observed (bug):     15 setup POINT_NODE decisions; decisions 13 and 14 offer only
                    countries with existing US influence.

Run: PYTHONPATH=/data/repos/DeepStruggle:build/release /data/venv/bin/python repro_setup_bonus.py [seed]
"""
from __future__ import annotations

import sys

import ts_engine as ts

FLAT_NODE = int(ts.FLAT_NODE)
FLAT_CARD = int(ts.FLAT_CARD)
COUNTRY = [ts.MapData.get_country_name(i) for i in range(84)]


def main(seed: int = 7) -> int:
    state = ts.GameState()
    ts.Engine.init_game(state, seed)
    decisions = []
    for idx in range(20):
        mask = ts.Engine.get_flat_action_mask(state, False)
        legal = [i for i in range(220) if mask[i]]
        dt = int(state.ctx().decision_type)
        if dt != int(ts.DecisionType.POINT_NODE) or state.current_phase != ts.Phase.SETUP:
            names = ([COUNTRY[i - FLAT_NODE] for i in legal if FLAT_NODE <= i < FLAT_NODE + 84][:4])
            decisions.append((idx, ts.Phase(state.current_phase).name,
                              ts.DecisionType(dt).name, names))
            break
        target = min(legal)  # lowest legal flat index = lowest country id
        decisions.append((idx, "SETUP", "POINT_NODE", [COUNTRY[target - FLAT_NODE]]))
        ts.Engine.step_flat(state, target, False)

    print(f"seed {seed}: setup decision sequence")
    for idx, phase, kind, tgts in decisions:
        print(f"  decision {idx}: phase={phase} kind={kind} targets={tgts}")

    setup_placements = sum(1 for d in decisions if d[1] == "SETUP")
    ok = setup_placements == 13 and decisions[-1][2] == "SELECT_CARD"
    print(f"setup placements: {setup_placements} (expected 13) -> "
          f"{'OK' if ok else 'BUG: US +2 handicap bonus present (DS-1)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
