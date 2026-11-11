#!/usr/bin/env python3
"""Headless DeepStruggle driver for the cross-engine rules-validation harness.

Plays games with the native ts_engine build (build/release/ts_engine.*.so) and writes ONE
JSON LINE PER DECISION in the harness schema (see DS-API.md for the full contract):

    {"game_id", "seed", "decision_idx", "actor", "kind", "legal", "vp", "defcon", "turn",
     "action_round", "ar_side", "milops", "space", "hand_sizes", "influence",
     "discard_count", "draw_count", "removed_count", "dice", "terminal", "winner"}

Conventions (mirrored by the reference engine's driver):
  * One line per engine-exposed decision, stepped with auto_advance=False so chance nodes
    (ROLL_DIE) are visible; the final line of a game is its terminal state, not a decision.
  * All state fields are read BEFORE the decision is taken; "dice" is the engine's last-roll
    record at that point (the dice of the immediately preceding step), [] when none.
  * VP is the engine's victory_points as-is: POSITIVE = US AHEAD (+20 = US win).
  * "legal" is the sorted list of canonical tokens for every legal FLAT action (220-wide
    space); policy "first" plays the lowest legal flat index, "random" samples uniformly
    from a per-game seeded RNG.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from typing import Any

import ts_engine as ts

FLAT_SIZE = int(ts.FLAT_ACTION_SPACE_SIZE)  # 220
CARD, RESOLUTION, OP_MODE, ROLL_DIE, NODE, BRANCH, CONFIRM_DONE, DEFCON_VALUE, REGION = (
    int(ts.FLAT_CARD), int(ts.FLAT_RESOLUTION), int(ts.FLAT_OP_MODE), int(ts.FLAT_ROLL_DIE),
    int(ts.FLAT_NODE), int(ts.FLAT_BRANCH), int(ts.FLAT_CONFIRM_DONE),
    int(ts.FLAT_DEFCON_VALUE), int(ts.FLAT_REGION))

DECISION_NAMES = {
    int(getattr(ts.DecisionType, n)): n
    for n in ("NONE", "SELECT_CARD", "SELECT_PLAY_MODE", "CHOOSE_TIMING_BRANCH",
              "SELECT_OP_MODE", "POINT_NODE", "CHOOSE_BRANCH", "ROLL_DIE")
}
RESOLUTION_NAMES = ("EVENT", "SPACE", "OPS_INFLUENCE", "OPS_COUP", "OPS_REALIGN")
OP_MODE_NAMES = ("INFLUENCE", "COUP", "REALIGN")
REGION_NAMES = ("Europe", "Asia", "Middle East", "Africa", "Central America", "South America")

# CHOOSE_BRANCH names, per resolving card (the engine asks for a branch in six events).
# Branch semantics from engine/src/events/*.cpp and the workbench's web/ui/src/game/branches.ts.
BRANCH_TOKENS = {
    "Warsaw Pact Formed": {0: "branch remove_us_influence", 1: "branch add_ussr_influence"},
    "Olympic Games": {0: "branch participate", 1: "branch boycott"},
    "Wargames": {0: "branch end_game", 1: "branch continue"},
}

COUNTRY_NAMES = [ts.MapData.get_country_name(i) for i in range(84)]
CARD_NAMES = [ts.CardData.get_card_name(i) for i in range(0, 111)]  # index by card id, [0] unused

LOCATION_HAND_US = (int(ts.CardLocation.HAND_US_UNKNOWN), int(ts.CardLocation.HAND_US_KNOWN))
LOCATION_HAND_USSR = (int(ts.CardLocation.HAND_USSR_UNKNOWN), int(ts.CardLocation.HAND_USSR_KNOWN))
LOC_DRAW = int(ts.CardLocation.DRAW_DECK)
LOC_DISCARD = int(ts.CardLocation.DISCARD_PILE)
LOC_REMOVED = int(ts.CardLocation.REMOVED_FROM_GAME)


def player_name(p: Any) -> str:
    p = int(p)
    if p == int(ts.Player.US):
        return "US"
    if p == int(ts.Player.USSR):
        return "USSR"
    return "NONE"


def canonical_token(state: ts.GameState, idx: int) -> str:
    """The canonical token for a legal flat action index (mapping documented in DS-API.md)."""
    if idx < RESOLUTION:  # SELECT_CARD: slot = card id - 1
        cid = idx + 1
        return f"card {cid} {CARD_NAMES[cid]}"
    if idx < ROLL_DIE:  # SELECT_PLAY_MODE (and the deferred SELECT_OP_MODE Ops choice)
        return RESOLUTION_NAMES[idx - RESOLUTION]
    if idx == ROLL_DIE:
        return "roll"
    if idx < BRANCH:  # POINT_NODE: country target
        cid = idx - NODE
        op = int(state.ctx().op_mode)
        name = COUNTRY_NAMES[cid]
        if op == int(ts.OpMode.COUP):
            return f"coup {name}"
        if op == int(ts.OpMode.REALIGN):
            return f"realign {name}"
        return f"+1 {name}"  # one influence per point-decision (cost 1 or 2 ops)
    if idx == CONFIRM_DONE:
        return "confirm_done"
    if DEFCON_VALUE <= idx < REGION:  # Summit / How I Learned: set DEFCON to 1..5
        return f"defcon {idx - DEFCON_VALUE + 1}"
    if idx >= REGION:  # Chernobyl: designated region
        return f"region {REGION_NAMES[idx - REGION]}"
    # CHOOSE_BRANCH generic slots 200..207
    branch = idx - BRANCH
    resolving = int(state.ctx().resolving_card)
    fixed = BRANCH_TOKENS.get(CARD_NAMES[resolving]) if 1 <= resolving <= 110 else None
    if fixed and branch in fixed:
        return fixed[branch]
    return f"branch {branch}"


def legal_tokens(state: ts.GameState, mask) -> list[str]:
    return sorted(canonical_token(state, i) for i in range(FLAT_SIZE) if mask[i])


def snapshot(state: ts.GameState) -> dict[str, Any]:
    """All per-decision state fields, from one to_save_dict() call (cheap, array-shaped)."""
    s = state.to_save_dict()
    locs = s["card_locations"]
    us_inf, ussr_inf = s["us_influence"], s["ussr_influence"]
    influence = {
        COUNTRY_NAMES[i]: [int(ussr_inf[i]), int(us_inf[i])]
        for i in range(84) if us_inf[i] or ussr_inf[i]
    }
    hand_us = sum(1 for l in locs if l in LOCATION_HAND_US)
    hand_ussr = sum(1 for l in locs if l in LOCATION_HAND_USSR)
    roll = s["last_roll"]
    if int(roll["type"]) != 0:
        dice = [int(roll["roll1"])] + ([int(roll["roll2"])] if int(roll["roll2"]) else [])
    else:
        dice = []
    return {
        "vp": int(s["victory_points"]),          # engine convention: positive = US ahead
        "defcon": int(s["defcon"]),
        "turn": int(s["turn"]),
        "action_round": int(s["action_round"]),
        "ar_side": player_name(s["phasing_player"]),
        "milops": [int(s["ussr_mil_ops"]), int(s["us_mil_ops"])],
        "space": [int(s["ussr_space_track"]), int(s["us_space_track"])],
        "hand_sizes": {"US": hand_us, "USSR": hand_ussr},
        "influence": influence,
        "discard_count": sum(1 for l in locs if l == LOC_DISCARD),
        "draw_count": sum(1 for l in locs if l == LOC_DRAW),
        "removed_count": sum(1 for l in locs if l == LOC_REMOVED),
        "dice": dice,
    }


def line_for(game_id: int, seed: int, decision_idx: int, state: ts.GameState,
             mask, terminal: bool) -> dict[str, Any]:
    ctx = state.ctx()
    dt = int(ctx.decision_type)
    actor = "CHANCE" if dt == int(ts.DecisionType.ROLL_DIE) else (
        player_name(ctx.decision_player) if int(ctx.decision_player) != int(ts.Player.NONE)
        else player_name(state.phasing_player))
    rec: dict[str, Any] = {
        "game_id": game_id,
        "seed": seed,
        "decision_idx": decision_idx,
        "actor": actor,
        "kind": DECISION_NAMES.get(dt, f"UNKNOWN_{dt}"),
        "legal": legal_tokens(state, mask) if mask is not None else [],
    }
    rec.update(snapshot(state))
    rec["terminal"] = bool(terminal)
    if terminal:
        u = float(ts.Engine.get_terminal_utility(state))
        rec["winner"] = "US" if u > 0 else ("USSR" if u < 0 else "DRAW")
    else:
        rec["winner"] = None
    return rec


def play_game(game_id: int, seed: int, policy: str, out) -> tuple[int, bool]:
    """Play one game; returns (decisions_logged, completed)."""
    rng = random.Random(f"{seed}:{game_id}")
    state = ts.GameState()
    ts.Engine.init_game(state, seed)
    mask = ts.Engine.get_flat_action_mask(state, False)
    idx = 0
    MAX_DECISIONS = 100_000
    while idx < MAX_DECISIONS:
        rec = line_for(game_id, seed, idx, state, mask, terminal=False)
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
        legal = [i for i in range(FLAT_SIZE) if mask[i]]
        if not legal:
            # Dead end with no legal action and no terminal state: a real defect.
            raise RuntimeError(f"seed {seed} game {game_id}: no legal action at decision {idx} "
                               f"({rec['kind']}) phase {int(state.current_phase)}")
        action = legal[0] if policy == "first" else rng.choice(legal)
        ts.Engine.step_flat(state, action, False)
        idx += 1
        if ts.Engine.is_terminal(state):
            rec = line_for(game_id, seed, idx, state, None, terminal=True)
            rec["legal"] = []
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")
            return idx + 1, True
        mask = ts.Engine.get_flat_action_mask(state, False)
    raise RuntimeError(f"seed {seed} game {game_id}: exceeded {MAX_DECISIONS} decisions")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--policy", choices=("first", "random"), default="random")
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    completed = 0
    crashed: list[tuple[int, str]] = []
    steps = 0
    t0 = time.perf_counter()
    with open(args.out, "w") as out:
        for game_id in range(args.games):
            try:
                n, done = play_game(game_id, args.seed, args.policy, out)
                steps += n
                if done:
                    completed += 1
            except Exception as exc:  # keep going; report at the end
                crashed.append((game_id, f"{type(exc).__name__}: {exc}"))
                print(f"CRASH game {game_id} (seed {args.seed}): {exc}", file=sys.stderr)
    dt = time.perf_counter() - t0
    print(f"games={args.games} completed={completed} crashed={len(crashed)} "
          f"steps={steps} steps/s={steps / dt:.0f} elapsed={dt:.1f}s")
    for game_id, msg in crashed:
        print(f"  crash game {game_id} (seed {args.seed}): {msg}", file=sys.stderr)
    return 0 if not crashed else 1


if __name__ == "__main__":
    sys.exit(main())
