#!/usr/bin/env python3
"""Regression tests for the DeepStruggle patches in ds-patches/.

Each test FAILS against the pinned engine (commit 7d3fd89) and PASSES against the
patched build. Point PYTHONPATH at the build to test:

    # unpatched (both tests must FAIL):
    PYTHONPATH=/data/repos/DeepStruggle:/data/repos/DeepStruggle/build/release \\
        pytest ds_patch_regression.py -q
    # patched (both tests must PASS):
    PYTHONPATH=ds-patched:ds-patched/build/release \\
        pytest ds_patch_regression.py -q

DS-1 -- the engine's setup asked the US for 2 bonus placements in countries with
        existing US influence (the reference engine's default handicap=-2 baked in).
        The standard game (rules/rules.md §3, the Deluxe rulebook, and the reference
        engine driven at handicap=0) ends the setup after 6 (USSR, Eastern Europe) +
        7 (US, Western Europe) placements.

DS-2 -- the engine offered NATO's EVENT mode without its prerequisite ("requires
        prior play of either Warsaw Pact Formed or Marshall Plan in order to be
        played as an Event"). The mask's opponent-card branch bypassed
        can_trigger_event; the patched build gates NATO in both branches.
"""
from __future__ import annotations

import os
import sys

import pytest

import ts_engine as ts

FLAT = 220
DT = ts.DecisionType


def _lowest_legal(state: ts.GameState) -> int:
    mask = ts.Engine.get_flat_action_mask(state, False)
    legal = [i for i in range(FLAT) if mask[i]]
    if not legal:
        raise AssertionError("no legal action")
    return min(legal)


def test_ds1_setup_has_no_us_bonus_handicap():
    """The setup is exactly 6 + 7 placements, then the US headline (DS-1)."""
    state = ts.GameState()
    ts.Engine.init_game(state, 7)
    placements = 0
    for _ in range(30):
        if int(state.current_phase) != int(ts.Phase.SETUP):
            break
        assert int(state.ctx().decision_type) == int(DT.POINT_NODE)
        ts.Engine.step_flat(state, _lowest_legal(state), False)
        placements += 1
    assert placements == 13, (
        f"DS-1: setup used {placements} placements (expected 13 = 6 USSR + 7 US; "
        f"the unpatched engine asks the US for 2 bonus placements afterwards)")
    assert int(state.current_phase) == int(ts.Phase.HEADLINE)
    assert int(state.ctx().decision_type) == int(DT.SELECT_CARD)


def test_ds2_nato_event_requires_prerequisite():
    """Without Marshall Plan / Warsaw Pact Formed, NATO must not offer EVENT (DS-2)."""
    state = ts.GameState()
    ts.Engine.init_game(state, 27)
    # jump to a clean USSR action round at turn 1 with NATO in hand
    for _ in range(30):
        if int(state.current_phase) == int(ts.Phase.ACTION_ROUND):
            break
        ts.Engine.step_flat(state, _lowest_legal(state), False)
    state.current_phase = ts.Phase.ACTION_ROUND
    state.turn = 1
    state.action_round = 1
    state.phasing_player = ts.Player.USSR
    state.ctx_stack_depth = 0
    ctx = state.ctx()
    ctx.decision_player = ts.Player.USSR
    ctx.decision_type = DT.SELECT_CARD
    ctx.resolving_card = 0
    state.set_card_location(21, int(ts.hand_of(ts.Player.USSR)))  # NATO

    assert not (state.has_flag(int(ts.EffectBits.MARSHALL_PLAN_PLAYED))
                or state.has_flag(int(ts.EffectBits.WARSAW_PACT_PLAYED)))

    mask = ts.Engine.get_flat_action_mask(state, False)
    ts.Engine.step_flat(state, 20, False)  # select NATO (id 21 -> slot 20)
    mask = ts.Engine.get_flat_action_mask(state, False)
    event_offered = bool(mask[int(ts.FLAT_RESOLUTION)])  # Resolution.EVENT
    assert not event_offered, (
        "DS-2: NATO's EVENT mode is offered without its prerequisite "
        "(Marshall Plan / Warsaw Pact Formed not played); the card text and the "
        "pre-AI reference engine both forbid the event play here")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
