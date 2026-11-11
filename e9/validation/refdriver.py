#!/usr/bin/env python3
'''
refdriver.py -- headless driver for the PRE-AI Twilight Struggle reference engine
(twilight-struggle-py @ a30ad14304bb28e29450cf223b85ca783bc3db19, with the minimal
expand_deck patch applied; see REF-API.md and patches/expand_deck.patch).

Emits one JSON line per decision plus one final GAME_END/ABORTED line per game,
following the schema agreed with the DeepStruggle adapter agent (see REF-API.md).

REPRODUCIBILITY CONTRACT
------------------------
* Engine randomness: the engine NEVER calls `random` itself (verified: no import of
  random in game_mechanics.py / twilight_cards.py / twilight_map.py). ALL chance
  flows through driver choices: (a) CHANCE prompts -- Side.NEUTRAL inputs, i.e.
  InputType.ROLL_DICE dice rolls and the deck-shuffle SELECT_CARD prompts -- and
  (b) US/USSR decision prompts under --policy random.
* Per game i (0-based), `random.seed(base_seed + i)` is called IMMEDIATELY BEFORE
  `Game()` is constructed and `start()` is run. No other RNG state is touched.
  All subsequent randomness is drawn from that one seeded generator in this exact
  order: for each prompt, options are materialized and SORTED lexicographically by
  canonical string, then `random.choice(<remaining sorted list>)` is used (one draw
  per attempt; an engine-rejected option consumes another draw). Therefore
  trajectories are bit-reproducible across processes despite the engine's
  hash-randomized set iteration (options are always sorted before use).
* CHANCE prompts are resolved with the seeded RNG even under --policy first
  (dice/deck must be random; --policy governs US/USSR decisions only).
* --policy first picks the lexicographically smallest canonical option string.

ENGINE-LEVEL GAME END (driver policy, documented in REF-API.md)
---------------------------------------------------------------
The pinned engine's terminate() only clears stage_list and is ineffective when
called inside end_of_turn (later code re-appends stages), and final_scoring() is
dead code (its turn-10 condition can never fire, yet it terminates unconditionally
on every end_of_turn -- which is neutralized by the same ineffectiveness). The
driver therefore enforces game end itself:
  1. turn_track >= 11  -> end of turn 10: driver applies final scoring using the
     engine's own score(region) for the six main regions plus the engine's
     China-Card-held bonus, then winner by VP sign.
  2. stage_list empty (with no unfinished engine business) -> engine terminate()
     (VP +/-20 mid-round, DEFCON 1) -> winner by VP sign.
  3. turn advanced to T<=10 and a scoring card is still in a hand -> held scoring
     card at end of turn T-1 -> holder loses (engine's check_for_scoring_cards
     detects this but its terminate() is ineffective; driver enforces it).

VP SIGN CONVENTION: engine vp_track is POSITIVE = USSR ahead (game_mechanics.py:67
"positive for ussr" and change_vp docstring). This driver normalizes and emits
vp = -vp_track so POSITIVE VP = US AHEAD, per the agreed schema.
'''

import argparse
import io
import json
import os
import random
import sys
import time
import traceback
from contextlib import redirect_stdout

ENGINE_DIR = '/data/repos/twilight-struggle-py-preAI'
sys.path.insert(0, ENGINE_DIR)

from game_mechanics import Game            # noqa: E402
from twilight_enums import Side, InputType, MapRegion  # noqa: E402

SCORING_CARDS = {
    'Asia_Scoring', 'Europe_Scoring', 'Middle_East_Scoring',
    'Central_America_Scoring', 'Southeast_Asia_Scoring',
    'Africa_Scoring', 'South_America_Scoring',
}
FINAL_SCORING_REGIONS = [
    MapRegion.ASIA, MapRegion.EUROPE, MapRegion.MIDDLE_EAST,
    MapRegion.CENTRAL_AMERICA, MapRegion.SOUTH_AMERICA, MapRegion.AFRICA,
]
MAX_LOOP_ITERATIONS = 2_000_000
MAX_DECISIONS = 200_000


def canonical_options(input_state):
    '''Materialize available_options once and return a sorted list of
    (canonical_string, raw_option) pairs. Raw options are str for every InputType
    except ROLL_DICE two-dice prompts, where they are (ussr_roll, us_roll) tuples
    (single-die prompts are str '1'..'6').'''
    pairs = []
    for opt in input_state.available_options:
        canon = ','.join(str(x) for x in opt) if isinstance(opt, tuple) else str(opt)
        pairs.append((canon, opt))
    # option_stop_early is selectable via recv() but not part of available_options
    # (the UI adds it explicitly, twilight_ui.py:129); mirror that so "legal" is
    # faithful and early-stop choices are reachable.
    if input_state.option_stop_early:
        canon = input_state.option_stop_early
        if canon not in [c for c, _ in pairs]:
            pairs.append((canon, input_state.option_stop_early))
    pairs.sort(key=lambda p: p[0])
    return pairs


def ar_side_str(side):
    if side in (Side.US, Side.USSR):
        return side.toStr()
    return 'NONE'


def snapshot(game):
    '''State snapshot. vp is NORMALIZED: positive = US ahead (engine vp_track is
    positive = USSR ahead, hence the negation).'''
    inf = {}
    for name in sorted(game.map.ALL.keys()):
        c = game.map.ALL[name]
        u, s = c.influence[Side.USSR], c.influence[Side.US]
        if u or s:
            inf[name] = [u, s]
    return {
        'vp': -game.vp_track,  # NORMALIZED: engine positive=USSR -> emit positive=US
        'defcon': game.defcon_track,
        'turn': game.turn_track,
        'action_round': game.ar_track,
        'ar_side': ar_side_str(game.ar_side),
        'milops': [game.milops_track[Side.USSR], game.milops_track[Side.US]],
        'space': [game.space_track[Side.USSR], game.space_track[Side.US]],
        'hand_sizes': {'US': len(game.hand[Side.US]),
                       'USSR': len(game.hand[Side.USSR])},
        'influence': inf,
        'discard_count': len(game.discard_pile),
        'draw_count': len(game.draw_pile),
        'removed_count': len(game.removed_pile),
    }


def base_line(game, game_id, seed, decision_idx, actor, kind, legal,
              dice, terminal, winner):
    line = {
        'game_id': game_id,
        'seed': seed,
        'decision_idx': decision_idx,
        'actor': actor,
        'kind': kind,
        'legal': legal,
        'vp': None, 'defcon': None, 'turn': None, 'action_round': None,
        'ar_side': None, 'milops': None, 'space': None, 'hand_sizes': None,
        'influence': None,
        'discard_count': None, 'draw_count': None, 'removed_count': None,
        'dice': dice,
        'terminal': terminal,
        'winner': winner,
    }
    try:
        line.update(snapshot(game))
    except Exception:
        pass  # best-effort snapshot on abort
    return line


def winner_by_vp(game):
    if game.vp_track > 0:
        return 'USSR'
    if game.vp_track < 0:
        return 'US'
    return 'DRAW'


class GameAborted(Exception):
    pass


def play_game(game_id, seed, policy, out_f):
    '''Play one game. Returns (decisions, end_kind, winner, crash_str).'''
    # ---- REPRODUCIBILITY: seed immediately before construction/start ----
    random.seed(seed)
    game = Game()
    game.start(handicap=0)  # handicap 0 = standard game (engine default -2 gives US 2 free influence)

    decision_idx = 0
    lines = []
    end_kind = None
    crash_str = None
    last_turn_seen = 1

    def flush_emit(line):
        out_f.write(json.dumps(line, sort_keys=False) + '\n')

    def emit_end(kind, winner):
        flush_emit(base_line(game, game_id, seed, decision_idx, 'CHANCE',
                             kind, [], [], True, winner))

    try:
        iterations = 0
        while True:
            iterations += 1
            if iterations > MAX_LOOP_ITERATIONS or decision_idx > MAX_DECISIONS:
                raise GameAborted('loop/decision limit exceeded')

            # --- game-over checks, in priority order ---
            if game.turn_track >= 11:
                # End of turn 10: driver-side final scoring (engine final_scoring
                # is dead code). Uses the engine's own score() implementations.
                for region in FINAL_SCORING_REGIONS:
                    game.score(region)
                for s in (Side.USSR, Side.US):
                    if 'The_China_Card' in game.hand[s]:
                        game.change_vp(s.vp_mult)
                emit_end('GAME_END', winner_by_vp(game))
                end_kind, winner = 'FINAL_SCORING_T10', winner_by_vp(game)
                break
            if not game.stage_list:
                # terminate() with no pending stages -> engine-signaled end
                # (VP +/-20 via change_vp, or DEFCON<2 via change_defcon, mid-round).
                w = winner_by_vp(game)
                emit_end('GAME_END', w)
                end_kind, winner = 'ENGINE_TERMINATE', w
                break
            if game.turn_track != last_turn_seen:
                prev_turn, last_turn_seen = last_turn_seen, game.turn_track
                if prev_turn < 10:
                    # Held scoring card at end of prev_turn: holder loses.
                    # (Engine checks US first; mirror that priority.)
                    holder = None
                    for s in (Side.US, Side.USSR):
                        if any(c in SCORING_CARDS for c in game.hand[s]):
                            holder = s
                            break
                    if holder is not None:
                        w = holder.opp.toStr()
                        emit_end('GAME_END', w)
                        end_kind, winner = 'HELD_SCORING_CARD', w
                        break

            # --- stage advancement ---
            if game.input_state is None:
                game.stage_complete()
                continue
            ist = game.input_state
            if ist.complete:
                game.stage_complete()
                continue

            # --- a decision prompt ---
            pairs = canonical_options(ist)
            legal = [c for c, _ in pairs]
            if not pairs:
                raise GameAborted(
                    f'stuck prompt: state={ist.state.name} side={ist.side} '
                    f'reps={ist.reps} prompt={ist.prompt!r}')

            is_chance = (ist.side == Side.NEUTRAL)
            actor = 'CHANCE' if is_chance else ist.side.toStr()
            is_dice = (ist.state == InputType.ROLL_DICE)

            remaining = list(pairs)
            chosen = None
            while remaining:
                if is_chance or policy == 'random':
                    chosen = random.choice(remaining)
                else:  # policy == 'first' on a player decision
                    chosen = remaining[0]
                if ist.recv(chosen[1]):
                    break
                remaining = [p for p in remaining if p[0] != chosen[0]]
                chosen = None
            if chosen is None:
                raise GameAborted('engine rejected every available option')

            dice_vals = []
            if is_dice:
                raw = chosen[1]
                dice_vals = [int(x) for x in raw] if isinstance(raw, tuple) else [int(raw)]

            flush_emit(base_line(game, game_id, seed, decision_idx, actor,
                                 ist.state.name, legal, dice_vals, False, None))
            decision_idx += 1

    except GameAborted as e:
        emit_end('ABORTED', None)
        end_kind, crash_str, winner = 'ABORTED', f'GameAborted: {e}', None
        return decision_idx, end_kind, winner, crash_str
    except Exception as e:
        tb = traceback.format_exc()
        # last engine frame for bug reporting
        engine_frame = None
        for fr in traceback.extract_tb(sys.exc_info()[2]):
            if fr.filename.startswith(ENGINE_DIR):
                engine_frame = f'{os.path.basename(fr.filename)}:{fr.lineno} in {fr.name}'
        crash_str = f'{type(e).__name__}: {e} @ {engine_frame}'
        emit_end('ABORTED', None)
        end_kind, winner = 'ABORTED', None
        return decision_idx, end_kind, winner, crash_str + '\n' + tb

    return decision_idx, end_kind, winner, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, required=True, help='base seed N')
    ap.add_argument('--games', type=int, required=True, help='number of games G')
    ap.add_argument('--policy', choices=['first', 'random'], required=True)
    ap.add_argument('--out', required=True, help='output JSONL file')
    ap.add_argument('--show-engine-output', action='store_true',
                    help='do not silence engine print() spam')
    args = ap.parse_args()

    crashes = []
    completed = aborted = 0
    total_decisions = 0
    per_end = {}
    t0 = time.time()

    sink = None if args.show_engine_output else io.StringIO()
    with open(args.out, 'w') as out_f:
        for game_id in range(args.games):
            seed = args.seed + game_id
            if sink is not None:
                with redirect_stdout(sink):
                    res = play_game(game_id, seed, args.policy, out_f)
            else:
                res = play_game(game_id, seed, args.policy, out_f)
            decisions, end_kind, winner, crash = res
            out_f.flush()
            total_decisions += decisions
            per_end[end_kind] = per_end.get(end_kind, 0) + 1
            if end_kind == 'ABORTED':
                aborted += 1
                crashes.append({'game_id': game_id, 'seed': seed,
                                'error': (crash or '').split('\n')[0],
                                'traceback': crash})
                print(f'game {game_id} (seed {seed}): ABORTED: {crashes[-1]["error"]}',
                      file=sys.stderr)
            else:
                completed += 1
                print(f'game {game_id} (seed {seed}): {end_kind} winner={winner} '
                      f'after {decisions} decisions', file=sys.stderr)

    elapsed = time.time() - t0
    summary = {
        'engine': ENGINE_DIR,
        'base_seed': args.seed,
        'policy': args.policy,
        'games_attempted': args.games,
        'games_completed': completed,
        'games_aborted': aborted,
        'end_kinds': per_end,
        'total_decisions': total_decisions,
        'elapsed_seconds': round(elapsed, 2),
        'decisions_per_second': round(total_decisions / elapsed, 1) if elapsed else None,
        'games_per_second': round(args.games / elapsed, 3) if elapsed else None,
        'crashes': crashes,
    }
    with open(args.out + '.summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == '__main__':
    main()
