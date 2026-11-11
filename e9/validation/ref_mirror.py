#!/usr/bin/env python3
"""ref_mirror.py -- reference-engine (twilight-struggle-py @ a30ad14) adapter for the
interleaved mirror driver.

Implements the refdriver reproducibility contract (REF-API.md §5) with one deviation:
dice prompts are fed from the SHARED dice stream (passed in by the orchestrator) instead
of drawn from the seeded RNG, and player decisions take the orchestrator's canonical
token. Chance prompts that are not dice (deck shuffles) still use the seeded RNG exactly
like refdriver.

Decision pairing aliases (canonical kind):
    DS SELECT_PLAY_MODE / SELECT_OP_MODE  <->  REF SELECT_CARD_ACTION
    DS POINT_NODE                         <->  REF SELECT_COUNTRY
    DS CHOOSE_BRANCH                      <->  REF SELECT_MULTIPLE
    DS SELECT_CARD                        <->  REF SELECT_CARD
    DS ROLL_DIE                           <->  REF ROLL_DICE

Option-string -> canonical-token mapping lives in canon.py; prompt-keyword
disambiguation for SELECT_COUNTRY (influence vs coup vs realignment vs war target) is
documented in CANON.md §4.
"""

from __future__ import annotations

import io
import random
import sys
import traceback
from contextlib import redirect_stdout
from typing import Any

ENGINE_DIR = '/data/repos/twilight-struggle-py-preAI'
sys.path.insert(0, ENGINE_DIR)

from game_mechanics import Game            # noqa: E402
from twilight_enums import Side, InputType, MapRegion  # noqa: E402

import canon

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

INPUT_TYPE_NAMES = {
    InputType.COMMIT: "COMMIT", InputType.ROLL_DICE: "ROLL_DICE",
    InputType.SELECT_CARD_ACTION: "SELECT_CARD_ACTION", InputType.SELECT_CARD: "SELECT_CARD",
    InputType.SELECT_COUNTRY: "SELECT_COUNTRY", InputType.SELECT_MULTIPLE: "SELECT_MULTIPLE",
}


class REFEnd(Exception):
    pass


class Decision:
    __slots__ = ("kind", "actor", "tokens", "prompt", "reps", "side", "raw_kind", "raw_options")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class REFAdapter:
    def __init__(self, seed: int, game_id: int = 0):
        self.seed = seed
        self.game_id = game_id
        random.seed(seed)
        sink = io.StringIO()
        with redirect_stdout(sink):
            self.game = Game()
            self.game.start(handicap=0)
        self.ended: tuple[str, str | None] | None = None   # (kind, winner)
        self.abort_reason: str | None = None
        self._last_turn = 1
        self._last_ar = 0
        self._at_prompt = self._advance_to_prompt()
        self.unmapped_options: set[str] = set()

    # ---------------- stage loop ----------------

    def _check_turn_advance(self) -> None:
        g = self.game
        if g.turn_track != self._last_turn:
            prev, self._last_turn = self._last_turn, g.turn_track
            self._last_ar = g.ar_track
            if prev < 10:
                holder = None
                for s in (Side.US, Side.USSR):
                    if any(c in SCORING_CARDS for c in g.hand[s]):
                        holder = s
                        break
                if holder is not None:
                    self.ended = ('HELD_SCORING_CARD', holder.opp.toStr())
                    raise REFEnd()

    def _final_scoring(self) -> None:
        g = self.game
        for region in FINAL_SCORING_REGIONS:
            g.score(region)
        for s in (Side.USSR, Side.US):
            if 'The_China_Card' in g.hand[s]:
                g.change_vp(s.vp_mult)

    def _advance_to_prompt(self) -> bool:
        """Run stages until a decision prompt is open (or the game ends).
        Returns True if a prompt is open."""
        g = self.game
        try:
            for _ in range(MAX_LOOP_ITERATIONS):
                if self.ended:
                    return False
                if g.turn_track >= 11:
                    self._final_scoring()
                    self.ended = ('FINAL_SCORING_T10', self.winner_by_vp())
                    return False
                if not g.stage_list:
                    self.ended = ('ENGINE_TERMINATE', self.winner_by_vp())
                    return False
                self._check_turn_advance()
                if self.ended:
                    return False
                if g.input_state is None:
                    with redirect_stdout(io.StringIO()):
                        g.stage_complete()
                    continue
                ist = g.input_state
                if ist.complete:
                    with redirect_stdout(io.StringIO()):
                        g.stage_complete()
                    continue
                return True
        except REFEnd:
            return False
        except Exception as e:
            self.abort_reason = f'{type(e).__name__}: {e}'
            self.ended = ('ABORTED', None)
            if self.abort_reason.startswith('TypeError'):
                tb = traceback.format_exc()
                self.abort_reason += '\n' + tb
            return False
        self.abort_reason = 'loop limit exceeded'
        self.ended = ('ABORTED', None)
        return False

    def winner_by_vp(self) -> str:
        v = self.game.vp_track
        return 'USSR' if v > 0 else ('US' if v < 0 else 'DRAW')

    def alive(self) -> bool:
        return self.ended is None

    def turn(self) -> int:
        return int(self.game.turn_track)

    # ---------------- option -> token ----------------

    def _country_token(self, opt: str, prompt: str) -> str:
        ds = canon.ref_country_to_ds(opt)
        if ds is None:
            self.unmapped_options.add(f'COUNTRY:{opt}')
            return f'ref:{opt}'
        p = prompt.lower()
        if 'coup' in p:
            return f'coup {ds}'
        if 'realign' in p:
            return f'realign {ds}'
        return f'+1 {ds}'

    def _option_to_token(self, opt_raw: Any, ist) -> str:
        kind = ist.state
        prompt = ist.prompt or ''
        if kind == InputType.SELECT_CARD:
            if opt_raw == ist.option_stop_early:
                return canon.REF_STOP_EARLY_TO_TOKEN.get(opt_raw, 'confirm_done')
            tok = canon.ref_card_to_token(opt_raw)
            if tok is None:
                self.unmapped_options.add(f'CARD:{opt_raw}')
                return f'ref:{opt_raw}'
            return tok
        if kind == InputType.SELECT_CARD_ACTION:
            if opt_raw in canon.REF_CARD_ACTION_TO_TOKEN:
                return canon.REF_CARD_ACTION_TO_TOKEN[opt_raw]
            self.unmapped_options.add(f'ACTION:{opt_raw}')
            return f'ref:{opt_raw}'
        if kind == InputType.SELECT_COUNTRY:
            if opt_raw == ist.option_stop_early:
                return 'confirm_done'
            return self._country_token(opt_raw, prompt)
        if kind == InputType.SELECT_MULTIPLE:
            if opt_raw == ist.option_stop_early:
                return 'confirm_done'
            card_ctx = self._infer_multiple_card(ist)
            tok = canon.ref_multiple_token(opt_raw, card_ctx)
            if tok:
                return tok
            table = canon.BRANCH_TABLES.get(card_ctx, {}).get('ref_contains') if card_ctx else None
            if table:
                for frag, t in table:
                    if frag in str(opt_raw).lower():
                        return t
            if card_ctx == 'Summit':
                for frag, delta in canon.REF_SUMMIT_DEFCON:
                    if str(opt_raw) == frag:
                        return f'defcon {max(1, min(5, self.game.defcon_track + delta))}'
            self.unmapped_options.add(f'MULTIPLE:{card_ctx}:{opt_raw}')
            return f'ref:{opt_raw}'
        if kind == InputType.ROLL_DICE:
            return 'roll'
        self.unmapped_options.add(f'{kind}:{opt_raw}')
        return f'ref:{opt_raw}'

    @staticmethod
    def _infer_multiple_card(ist) -> str | None:
        opts = ' | '.join(str(o) for o, _ in canon_opts(ist)).lower()
        if 'remove all us influence' in opts or 'add 5 ussr' in opts:
            return 'Warsaw Pact Formed'
        if 'participate' in opts and 'boycott' in opts:
            return 'Olympic Games'
        if 'defcon -1' in opts:
            return 'Summit'
        if 'thermonuclear' in opts:
            return 'How I Learned to Stop Worrying'
        if 'free coup attempt' in opts:
            return 'Junta or Tear Down this Wall'
        if 'south africa' in opts and 'add 2 influence' in opts:
            return 'South African Unrest'
        if 'use the card selected' in opts:
            return 'Grain Sales to Soviets'
        for r in canon.DS_REGION_NAMES:
            if r.lower() in opts:
                return 'Chernobyl'
        return None

    # ---------------- decision ----------------

    def decision(self) -> Decision | None:
        if not self._at_prompt:
            return None
        ist = self.game.input_state
        pairs = canon_opts(ist)
        tokens = []
        for canon_s, raw in pairs:
            tokens.append(self._option_to_token(raw, ist))
        actor = 'CHANCE' if ist.side == Side.NEUTRAL else ist.side.toStr()
        return Decision(
            kind=INPUT_TYPE_NAMES.get(ist.state, str(ist.state)),
            actor=actor,
            tokens=canon.sort_tokens(tokens),
            prompt=ist.prompt or '',
            reps=int(ist.reps),
            side=ist.side,
            raw_kind=ist.state,
            raw_options=pairs,
        )

    # ---------------- applying ----------------

    def apply(self, token: str, dice: tuple[int, ...] = ()) -> None:
        """Apply one canonical token at the current prompt (one recv)."""
        ist = self.game.input_state
        assert ist is not None and not ist.complete
        if ist.state == InputType.ROLL_DICE:
            raw = self._dice_option(dice, ist)
            raw_by_canon = {c: r for c, r in canon_opts(ist)}
            if raw not in raw_by_canon.values():
                # The offered set doesn't contain our value pair (shouldn't happen).
                raise RuntimeError(f'dice option {raw!r} not offered: {sorted(map(str, raw_by_canon.values()))}')
            ok = ist.recv(raw)
            if not ok:
                raise RuntimeError(f'dice option {raw!r} rejected')
        else:
            # find raw option(s) for this token
            candidates = []
            for canon_s, raw in canon_opts(ist):
                if self._option_to_token(raw, ist) == token:
                    candidates.append(raw)
            if not candidates:
                raise RuntimeError(f'token {token!r} not legal in REF at prompt {ist.prompt!r}')
            chosen = None
            for raw in candidates:
                with redirect_stdout(io.StringIO()):
                    ok = ist.recv(raw)
                if ok:
                    chosen = raw
                    break
            if chosen is None:
                raise RuntimeError(f'token {token!r} rejected by REF callback')
        if ist.complete:
            self._at_prompt = self._advance_to_prompt()

    def _dice_option(self, dice: tuple[int, ...], ist) -> Any:
        """dice arrive already in the reference engine's own convention:
        1d6 -> (v,); 2d6 -> (ussr, us); reroll-ties -> (sponsor_total, participant)."""
        prompt = ist.prompt or ''
        if 'no ties' in prompt or '2d6' in prompt:
            return (dice[0], dice[1])
        return str(dice[0])

    # ---------------- chance (non-dice) resolution ----------------

    def resolve_chance(self, dec: Decision) -> None:
        """Resolve a non-dice CHANCE prompt (deck shuffle) with the seeded RNG,
        exactly like refdriver: random.choice over the sorted remaining options."""
        ist = self.game.input_state
        remaining = list(dec.raw_options)
        while remaining:
            chosen = random.choice(remaining)
            with redirect_stdout(io.StringIO()):
                ok = ist.recv(chosen[1])
            if ok:
                break
            remaining = [p for p in remaining if p[0] != chosen[0]]
        else:
            raise RuntimeError('chance prompt rejected every option')
        if ist.complete:
            self._at_prompt = self._advance_to_prompt()

    # ---------------- hands / deck ----------------

    def hand_ids(self, side: str) -> list[int]:
        s = Side.USSR if side == 'USSR' else Side.US
        out = []
        for name in self.game.hand[s]:
            cid = canon.REF_NAME_TO_DS_ID.get(name)
            if cid is None:
                out.append(f'?{name}')
            else:
                out.append(cid)
        return out

    def hand_names(self, side: str) -> list[str]:
        s = Side.USSR if side == 'USSR' else Side.US
        return list(self.game.hand[s])

    def set_hand(self, side: str, names: list[str]) -> None:
        s = Side.USSR if side == 'USSR' else Side.US
        self.game.hand[s] = list(names)

    def deck_order(self) -> list[str]:
        return list(self.game.draw_pile)

    # ---------------- snapshot (refdriver schema, pre-decision) ----------------

    def snapshot(self) -> dict[str, Any]:
        g = self.game
        inf = {}
        for name in sorted(g.map.ALL.keys()):
            if name in ('US', 'USSR'):
                continue  # superpowers are constant [999,0]/[0,999]; DS has no such entries
            c = g.map.ALL[name]
            u, s = c.influence[Side.USSR], c.influence[Side.US]
            if u or s:
                inf[canon.ref_country_to_ds(name) or name] = [u, s]
        return {
            'vp': -g.vp_track,
            'defcon': g.defcon_track,
            'turn': g.turn_track,
            'action_round': g.ar_track,
            'ar_side': g.ar_side.toStr() if g.ar_side in (Side.US, Side.USSR) else 'NONE',
            'milops': [g.milops_track[Side.USSR], g.milops_track[Side.US]],
            'space': [g.space_track[Side.USSR], g.space_track[Side.US]],
            'hand_sizes': {'US': len(g.hand[Side.US]), 'USSR': len(g.hand[Side.USSR])},
            'influence': inf,
            'discard_count': len(g.discard_pile),
            'draw_count': len(g.draw_pile),
            'removed_count': len(g.removed_pile),
            'dice': [],
        }

    def terminal_line(self) -> dict[str, Any]:
        kind, winner = self.ended if self.ended else ('ABORTED', None)
        return {'terminal': True, 'winner': winner, 'end_kind': kind,
                'abort_reason': self.abort_reason}


def canon_opts(ist):
    """Materialize available_options once (sorted); refdriver contract."""
    pairs = []
    for opt in ist.available_options:
        c = ','.join(str(x) for x in opt) if isinstance(opt, tuple) else str(opt)
        pairs.append((c, opt))
    if ist.option_stop_early:
        c = ist.option_stop_early
        if c not in [x for x, _ in pairs]:
            pairs.append((c, ist.option_stop_early))
    pairs.sort(key=lambda p: p[0])
    return pairs
