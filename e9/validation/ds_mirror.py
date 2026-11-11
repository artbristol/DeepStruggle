#!/usr/bin/env python3
"""ds_mirror.py -- DeepStruggle-side adapter for the interleaved mirror driver.

Wraps a ts.GameState and exposes the same decision interface as ref_mirror.py:

    decision()  -> Decision(kind, actor, tokens, extra)   # current decision, pre-action
    apply(tok, dice) -> None                               # apply a canonical token
    snapshot()  -> dict                                    # dsdriver-schema state fields
    align_hands(us_ids, ussr_ids) -> list[str]             # post-deal hand alignment
    location_diff() -> dict                                # card moves of the last step

Run under /data/venv/bin/python with PYTHONPATH=/data/repos/DeepStruggle:build/release.

Dice: DS chance nodes are real decisions (DecisionType.ROLL_DIE). The mirror injects
forced dice (MicroAction(ROLL_DIE, actor_die, opp_die, 0); 0 = RNG is NEVER used -- the
harness always injects concrete values) mapped per pending_roll_type:

    COUP / SPACE_RACE / TRAP_ESCAPE / WAR_EVENT   primary = roller's die
    REALIGNMENT                                   primary = actor's die, secondary = opponent's
    OLYMPIC_GAMES                                 primary = sponsor's die (+2 applied by engine),
                                                  secondary = participant's die
    SUMMIT                                        primary = US die, secondary = USSR die
    TURN_CLEANUP                                  consumes no die (end-of-turn cleanup step)

(Conventions verified against engine/src/state_machine.cpp:1502-1600 and
card_dispatcher.cpp / war_events.hpp; see CANON.md.)
"""

from __future__ import annotations

from typing import Any

import ts_engine as ts

import canon

FLAT_SIZE = int(ts.FLAT_ACTION_SPACE_SIZE)
FLAT_CARD = int(ts.FLAT_CARD)
FLAT_RESOLUTION = int(ts.FLAT_RESOLUTION)
FLAT_OP_MODE = int(ts.FLAT_OP_MODE)
FLAT_ROLL_DIE = int(ts.FLAT_ROLL_DIE)
FLAT_NODE = int(ts.FLAT_NODE)
FLAT_BRANCH = int(ts.FLAT_BRANCH)
FLAT_CONFIRM_DONE = int(ts.FLAT_CONFIRM_DONE)
FLAT_DEFCON_VALUE = int(ts.FLAT_DEFCON_VALUE)
FLAT_REGION = int(ts.FLAT_REGION)

DT = ts.DecisionType
DECISION_NAMES = {
    int(DT.NONE): "NONE", int(DT.SELECT_CARD): "SELECT_CARD",
    int(DT.SELECT_PLAY_MODE): "SELECT_PLAY_MODE",
    int(DT.CHOOSE_TIMING_BRANCH): "CHOOSE_TIMING_BRANCH",
    int(DT.SELECT_OP_MODE): "SELECT_OP_MODE", int(DT.POINT_NODE): "POINT_NODE",
    int(DT.CHOOSE_BRANCH): "CHOOSE_BRANCH", int(DT.ROLL_DIE): "ROLL_DIE",
}
ROLL_TYPE_NAMES = {
    int(v): n for n, v in (
        ("NONE", ts.RollType.NONE), ("COUP", ts.RollType.COUP),
        ("REALIGNMENT", ts.RollType.REALIGNMENT), ("SPACE_RACE", ts.RollType.SPACE_RACE),
        ("WAR_EVENT", ts.RollType.WAR_EVENT), ("OLYMPIC_GAMES", ts.RollType.OLYMPIC_GAMES),
        ("SUMMIT", ts.RollType.SUMMIT), ("TRAP_ESCAPE", ts.RollType.TRAP_ESCAPE),
        ("TURN_CLEANUP", ts.RollType.TURN_CLEANUP),
    )
}
SETUP_PHASE = int(ts.Phase.SETUP)
HEADLINE_PHASE = int(ts.Phase.HEADLINE)

CARD = canon.DS_ID_TO_NAME
COUNTRY = canon.DS_COUNTRY_NAMES
CHINA_CARD = 6

LOCATION_HAND_US = (int(ts.CardLocation.HAND_US_UNKNOWN), int(ts.CardLocation.HAND_US_KNOWN))
LOCATION_HAND_USSR = (int(ts.CardLocation.HAND_USSR_UNKNOWN), int(ts.CardLocation.HAND_USSR_KNOWN))
LOC_DRAW = int(ts.CardLocation.DRAW_DECK)
LOC_DISCARD = int(ts.CardLocation.DISCARD_PILE)
LOC_REMOVED = int(ts.CardLocation.REMOVED_FROM_GAME)


def hand_loc(player: int) -> int:
    return int(ts.hand_of(ts.Player(player)))


def player_name(p: Any) -> str:
    p = int(p)
    return {int(ts.Player.US): "US", int(ts.Player.USSR): "USSR"}.get(p, "NONE")


class Decision:
    __slots__ = ("kind", "actor", "tokens", "roll_type", "roll_actor", "resolving_card",
                 "decision_player", "allow_early_stop", "raw_kind")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class DSMirror:
    def __init__(self, seed: int):
        self.seed = seed
        self.state = ts.GameState()
        ts.Engine.init_game(self.state, seed)
        self._locs_before = self._locations()
        self.aligned_log: list[str] = []

    # -------------------- state helpers --------------------

    def _locations(self) -> list[int]:
        return [int(x) for x in self.state.to_save_dict()["card_locations"]]

    def location_diff(self) -> dict[int, tuple[int, int]]:
        """{card_id: (loc_before, loc_after)} for cards that moved since the last call.
        to_save_dict()['card_locations'] is indexed BY CARD ID (0..110; slot 0 unused)."""
        after = self._locations()
        diff = {c: (b, a) for c, (b, a) in enumerate(zip(self._locs_before, after)) if b != a and c >= 1}
        self._locs_before = after
        return diff

    def turn(self) -> int:
        return int(self.state.turn)

    def is_terminal(self) -> bool:
        return bool(ts.Engine.is_terminal(self.state))

    def hand_ids(self, player: str) -> list[int]:
        locs = LOCATION_HAND_US if player == "US" else LOCATION_HAND_USSR
        return [c for c in range(1, 111) if int(self.state.get_card_location(c)) in locs]

    # -------------------- decisions --------------------

    def _decode_token(self, idx: int) -> str:
        if idx < FLAT_RESOLUTION:
            cid = idx + 1
            return f"card {cid} {CARD[cid]}"
        if idx < FLAT_ROLL_DIE:
            return canon.DS_RESOLUTION_TO_TOKEN[idx - FLAT_RESOLUTION]
        if idx == FLAT_ROLL_DIE:
            return "roll"
        if idx < FLAT_BRANCH:
            cid = idx - FLAT_NODE
            op = int(self.state.ctx().op_mode)
            if op == int(ts.OpMode.COUP):
                return f"coup {COUNTRY[cid]}"
            if op == int(ts.OpMode.REALIGN):
                return f"realign {COUNTRY[cid]}"
            return f"+1 {COUNTRY[cid]}"
        if idx == FLAT_CONFIRM_DONE:
            return "confirm_done"
        if FLAT_DEFCON_VALUE <= idx < FLAT_REGION:
            return f"defcon {idx - FLAT_DEFCON_VALUE + 1}"
        if idx >= FLAT_REGION:
            return f"region {canon.DS_REGION_NAMES[idx - FLAT_REGION]}"
        branch = idx - FLAT_BRANCH
        resolving = int(self.state.ctx().resolving_card)
        if 1 <= resolving <= 110:
            fixed = canon.BRANCH_TABLES.get(CARD[resolving], {}).get("ds")
            if fixed and branch in fixed:
                return fixed[branch]
        return f"branch {branch}"

    def decision(self) -> Decision:
        st = self.state
        ctx = st.ctx()
        dt = int(ctx.decision_type)
        mask = ts.Engine.get_flat_action_mask(st, False)
        tokens = canon.sort_tokens(self._decode_token(i) for i in range(FLAT_SIZE) if mask[i])
        actor = ("CHANCE" if dt == int(DT.ROLL_DIE)
                 else player_name(ctx.decision_player)
                 if int(ctx.decision_player) != int(ts.Player.NONE)
                 else player_name(st.phasing_player))
        return Decision(
            kind=DECISION_NAMES.get(dt, f"UNKNOWN_{dt}"),
            actor=actor,
            tokens=tokens,
            roll_type=ROLL_TYPE_NAMES.get(int(ctx.pending_roll_type), str(int(ctx.pending_roll_type))),
            roll_actor=player_name(ctx.roll_actor),
            resolving_card=int(ctx.resolving_card),
            decision_player=player_name(ctx.decision_player),
            allow_early_stop=bool(ctx.allow_early_stop),
            raw_kind=dt,
        )

    def dice_for(self, dec: Decision, stream: canon.DiceStream) -> tuple[int, ...]:
        """Dice values this decision consumes from the shared stream, in engine order
        (primary, secondary). TURN_CLEANUP consumes none."""
        rt = dec.roll_type
        if rt == "TURN_CLEANUP":
            return ()
        if rt == "REALIGNMENT":
            actor = dec.roll_actor if dec.roll_actor != "NONE" else None
            if actor is None:  # fall back: the phasing player rolls
                actor = player_name(self.state.phasing_player)
            a = stream.d6()
            b = stream.d6()
            return (a, b) if actor == "US" else (b, a)  # (primary=actor, secondary=opp)
        if rt == "OLYMPIC_GAMES":
            s, p = stream.pair_no_ties()
            return (s, p)  # primary = sponsor, secondary = participant
        if rt == "SUMMIT":
            us = stream.d6()
            ussr = stream.d6()
            return (us, ussr)  # primary = US, secondary = USSR
        return (stream.d6(),)

    # -------------------- applying actions --------------------

    def apply(self, token: str, dice: tuple[int, ...] = ()) -> None:
        st = self.state
        ctx = st.ctx()
        dt = int(ctx.decision_type)
        if dt == int(DT.ROLL_DIE):
            rt = ROLL_TYPE_NAMES.get(int(ctx.pending_roll_type), "")
            if rt != "TURN_CLEANUP":
                assert dice, "ROLL_DIE requires injected dice"
            primary = dice[0] if len(dice) > 0 else 0
            secondary = dice[1] if len(dice) > 1 else 0
            ts.Engine.step(st, ts.MicroAction(ts.DecisionType.ROLL_DIE, primary, secondary, 0))
            return
        idx = ts.encode_micro_action(st, self._token_to_micro(token))
        ts.Engine.step_flat(st, idx, False)

    def _token_to_micro(self, token: str) -> ts.MicroAction:
        st = self.state
        dt = int(st.ctx().decision_type)
        if token.startswith("card "):
            cid = int(token.split()[1])
            return ts.MicroAction(ts.DecisionType.SELECT_CARD, cid, 0, 0)
        if token in ("EVENT", "SPACE", "OPS_INFLUENCE", "OPS_COUP", "OPS_REALIGN"):
            rid = canon.DS_RESOLUTION_TO_TOKEN.index(token)
            return ts.MicroAction(ts.DecisionType.SELECT_PLAY_MODE, rid, 0, 0)
        if token in ("INFLUENCE", "COUP", "REALIGN"):
            rid = canon.DS_OPMODE_TO_TOKEN.index(token)
            return ts.MicroAction(ts.DecisionType.SELECT_OP_MODE, rid, 0, 0)
        if token == "confirm_done":
            return ts.MicroAction(dt, 255, 0, 0x80)
        if token == "roll":
            return ts.MicroAction(ts.DecisionType.ROLL_DIE, 0, 0, 0)
        if token.startswith("+1 "):
            cid = COUNTRY.index(token[3:])
            return ts.MicroAction(ts.DecisionType.POINT_NODE, cid, 0, 0)
        if token.startswith("coup "):
            cid = COUNTRY.index(token[5:])
            return ts.MicroAction(ts.DecisionType.POINT_NODE, cid, 0, 0)
        if token.startswith("realign "):
            cid = COUNTRY.index(token[8:])
            return ts.MicroAction(ts.DecisionType.POINT_NODE, cid, 0, 0)
        if token.startswith("defcon "):
            lvl = int(token.split()[1])
            return ts.MicroAction(ts.DecisionType.CHOOSE_BRANCH, lvl, 0, 0)
        if token.startswith("region "):
            rid = canon.DS_REGION_NAMES.index(token[7:])
            return ts.MicroAction(ts.DecisionType.CHOOSE_BRANCH, rid, 0, 0)
        if token.startswith("branch "):
            name = token[len("branch "):]
            resolving = int(st.ctx().resolving_card)
            fixed = canon.BRANCH_TABLES.get(CARD[resolving], {}).get("ds") if 1 <= resolving <= 110 else None
            for bid, tok in (fixed or {}).items():
                if tok == token:
                    return ts.MicroAction(ts.DecisionType.CHOOSE_BRANCH, bid, 0, 0)
            return ts.MicroAction(ts.DecisionType.CHOOSE_BRANCH, int(name), 0, 0)
        raise ValueError(f"cannot encode token {token!r}")

    # -------------------- deal alignment --------------------

    def align_hands(self, us_cards: list[int], ussr_cards: list[int]) -> list[str]:
        """Force DS hands to exactly the reference engine's hands (post-deal).

        Only cards that are currently in a DS hand or the draw deck are moved;
        discard/removal/unavailable locations are preserved. The China Card is
        aligned like any other. Returns human-readable notes.
        """
        notes: list[str] = []
        want: dict[int, int] = {}
        for c in us_cards:
            want[c] = hand_loc(int(ts.Player.US))
        for c in ussr_cards:
            want[c] = hand_loc(int(ts.Player.USSR))
        for c in range(1, 111):
            cur = int(self.state.get_card_location(c))
            is_hand = cur in LOCATION_HAND_US or cur in LOCATION_HAND_USSR
            is_deck = cur == LOC_DRAW
            target = want.get(c)
            if target is not None:
                if cur != target:
                    self.state.set_card_location(c, target)
                    notes.append(f"card {c} -> hand ({cur}->{target})")
            elif is_hand or is_deck:
                self.state.set_card_location(c, LOC_DRAW)
                if is_hand:
                    notes.append(f"card {c} hand -> deck")
        self._locs_before = self._locations()
        return notes

    # -------------------- snapshot (dsdriver schema) --------------------

    def snapshot(self) -> dict[str, Any]:
        s = self.state.to_save_dict()
        locs = [int(x) for x in s["card_locations"]]
        us_inf, ussr_inf = s["us_influence"], s["ussr_influence"]
        influence = {COUNTRY[i]: [int(ussr_inf[i]), int(us_inf[i])]
                     for i in range(84) if us_inf[i] or ussr_inf[i]}
        roll = s["last_roll"]
        if int(roll["type"]) != 0:
            dice = [int(roll["roll1"])] + ([int(roll["roll2"])] if int(roll["roll2"]) else [])
        else:
            dice = []
        return {
            "vp": int(s["victory_points"]),
            "defcon": int(s["defcon"]),
            "turn": int(s["turn"]),
            "action_round": int(s["action_round"]),
            "ar_side": player_name(s["phasing_player"]),
            "milops": [int(s["ussr_mil_ops"]), int(s["us_mil_ops"])],
            "space": [int(s["ussr_space_track"]), int(s["us_space_track"])],
            "hand_sizes": {"US": sum(1 for l in locs if l in LOCATION_HAND_US),
                           "USSR": sum(1 for l in locs if l in LOCATION_HAND_USSR)},
            "influence": influence,
            "discard_count": sum(1 for l in locs if l == LOC_DISCARD),
            "draw_count": sum(1 for l in locs if l == LOC_DRAW),
            "removed_count": sum(1 for l in locs if l == LOC_REMOVED),
            "dice": dice,
        }

    def terminal_line(self) -> dict[str, Any]:
        u = float(ts.Engine.get_terminal_utility(self.state))
        return {"terminal": True, "winner": "US" if u > 0 else ("USSR" if u < 0 else "DRAW")}
