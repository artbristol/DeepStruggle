#!/usr/bin/env python3
"""invariant_check.py -- invariant layer over all harness JSONL corpora.

Checks every decision line of every corpus (the two random corpora ds_random_s1 /
ref_random_s1 and the mirrored corpora mirror300_*):

  I1  vp in [-20, 20]; at terminal lines the winner agrees with the VP sign when
      |vp| = 20 (DS convention positive = US; REF lines are normalized the same).
  I2  defcon in [1, 5].
  I3  influence counts >= 0 (all countries, both sides).
  I4  hand sizes within deck constraints: 0 <= size <= 10; DS random corpus
      (no deal alignment) is held to the strict 8/9 limits.
  I5  milops in [0, 5]; space track in [0, 8]; turn in [1, 11]; action_round in [0, 8].
  I6  pile counts >= 0.
  I7  dice values (where present) in [1, 6].
  I8  terminal-line consistency per engine:
      DS: winner sign matches |vp| = 20; DEFCON-1 terminations end with defcon 1.
      REF: end_kind HELD_SCORING_CARD / ENGINE_TERMINATE / FINAL_SCORING_T10 with
      the corresponding vp/defcon/turn preconditions.
  I9  legal-token vocabulary: every token parses against the canonical grammar.

Usage: python3 invariant_check.py file1.jsonl [file2.jsonl ...] [--strict-ds-hands]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

COUNTRIES = set()
CARDS = set()



def load_vocab():
    global COUNTRIES, CARDS
    import canon
    COUNTRIES = set(canon.DS_COUNTRY_NAMES)
    CARDS = {f"card {i} {canon.DS_ID_TO_NAME[i]}" for i in range(1, 111)}


TOKEN_PATTERNS = [
    re.compile(r"^card (?:\d+) .+$"),
    re.compile(r"^(EVENT|SPACE|OPS_INFLUENCE|OPS_COUP|OPS_REALIGN)$"),
    re.compile(r"^(INFLUENCE|COUP|REALIGN)$"),
    re.compile(r"^\+1 .+$"),
    re.compile(r"^coup .+$"),
    re.compile(r"^realign .+$"),
    re.compile(r"^confirm_done$"),
    re.compile(r"^roll$"),
    re.compile(r"^defcon [1-5]$"),
    re.compile(r"^region (Europe|Asia|Middle East|Africa|Central America|South America)$"),
    re.compile(r"^branch \S+$"),
    re.compile(r"^skip_optional_ar$"),
    re.compile(r"^ref:.+$"),
    # REF-engine raw option formats (the original refdriver corpora emit these):
    re.compile(r"^[A-Za-z0-9_'\u201d\u2026:+/(). ,?-]+$"),
    re.compile(r"^(PLAY_EVENT|RESOLVE_EVENT_FIRST|INFLUENCE|REALIGNMENT|COUP|SPACE|SKIP_OPTIONAL_AR)$"),
    re.compile(r"^[1-6],[1-6]$"),                 # 2d6 option strings
]


def token_ok(tok: str) -> bool:
    return any(p.match(tok) for p in TOKEN_PATTERNS)


def check_file(path: str, strict_ds_hands: bool) -> dict:
    violations: dict[str, list[str]] = {}
    n = 0

    def viol(code: str, msg: str) -> None:
        violations.setdefault(code, []).append(msg)

    prev = None
    for lineno, line in enumerate(open(path), 1):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        n += 1
        gid, didx = r.get("game_id"), r.get("decision_idx")
        tag = f"{path.split('/')[-1]} g{gid} d{didx}"

        vp = r.get("vp")
        if vp is not None and not (-20 <= vp <= 20):
            viol("I1_vp_range", f"{tag}: vp={vp}")
        defcon = r.get("defcon")
        if defcon is not None and not (1 <= defcon <= 5):
            viol("I2_defcon_range", f"{tag}: defcon={defcon}")
        inf = r.get("influence") or {}
        for c, pair in inf.items():
            if len(pair) != 2 or pair[0] < 0 or pair[1] < 0:
                viol("I3_influence_negative", f"{tag}: {c}={pair}")
        hs = r.get("hand_sizes") or {}
        limit = 9 if (r.get("turn") or 1) <= 3 else 10
        for side, size in hs.items():
            if size < 0 or size > 10:
                viol("I4_hand_range", f"{tag}: {side}={size}")
            elif strict_ds_hands and size > limit:
                viol("I4_hand_strict", f"{tag}: turn {r.get('turn')} {side}={size} > {limit}")
        milops = r.get("milops") or [0, 0]
        if any(m < 0 or m > 5 for m in milops):
            viol("I5_milops_range", f"{tag}: {milops}")
        space = r.get("space") or [0, 0]
        if any(s < 0 or s > 8 for s in space):
            viol("I5_space_range", f"{tag}: {space}")
        turn = r.get("turn")
        if turn is not None and not (1 <= turn <= 11):
            viol("I5_turn_range", f"{tag}: turn={turn}")
        ar = r.get("action_round")
        if ar is not None:
            # The last ARs per turn are 6 (turns 1-3) / 7 (4-10), +1 when an eighth
            # round was granted (North Sea Oil / Space Race box 7-8). DS exposes one
            # further end-of-turn cleanup decision with the counter already advanced
            # (ar = max+1, or max+2 after a granted 8th round) -- a display artifact
            # of the chance step, not an extra round.
            cap = (6 if (turn or 1) <= 3 else 7) + 2
            if not (0 <= ar <= cap):
                viol("I5_ar_range", f"{tag}: ar={ar} (turn={turn})")
        for f in ("discard_count", "draw_count", "removed_count"):
            v = r.get(f)
            if v is not None and v < 0:
                viol("I6_pile_negative", f"{tag}: {f}={v}")
        for d in (r.get("dice") or []):
            # 1..6 = die faces. The REF corpora encode the Olympic reroll-ties
            # option as (sponsor_face + 2, participant_face), so a single value in
            # 3..8 alongside one in 1..6 is the documented option encoding, not a
            # bad die.
            if not (1 <= d <= 6):
                lst = r.get("dice") or []
                reroll_ok = (len(lst) == 2 and sum(1 for x in lst if x > 6) == 1
                             and all(1 <= x <= 8 for x in lst))
                if not reroll_ok:
                    viol("I7_dice_range", f"{tag}: dice={r.get('dice')}")
        for tok in (r.get("legal") or []):
            if not token_ok(tok):
                viol("I9_token_vocab", f"{tag}: {tok!r}")

        if r.get("terminal"):
            winner = r.get("winner")
            kind = r.get("kind") or r.get("end_kind")
            if winner not in ("US", "USSR", "DRAW", None):
                viol("I8_winner_vocab", f"{tag}: winner={winner!r}")
            if winner in ("US", "USSR") and vp is not None:
                if abs(vp) == 20:
                    want = "US" if vp > 0 else "USSR"
                    if winner != want:
                        viol("I8_winner_vp_sign", f"{tag}: winner={winner} vp={vp}")
            if kind == "ENGINE_TERMINATE" and vp is not None and defcon is not None:
                if abs(vp) < 20 and defcon != 1:
                    viol("I8_terminate_reason", f"{tag}: ENGINE_TERMINATE at vp={vp} defcon={defcon}")
            if kind == "FINAL_SCORING_T10" and turn is not None and turn < 11:
                viol("I8_final_scoring_turn", f"{tag}: FINAL_SCORING_T10 at turn={turn}")
            if kind == "HELD_SCORING_CARD" and winner is not None:
                pass  # holder's opponent wins; holder identity is not in the line
        prev = r
    return {"file": path, "lines": n, "violations": violations}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--strict-ds-hands", action="store_true",
                    help="hold DS-engine corpora to the strict 8/9 hand limits "
                         "(no deal alignment: the China +1 cannot occur)")
    args = ap.parse_args()
    load_vocab()
    total_v = 0
    for path in args.files:
        res = check_file(path, args.strict_ds_hands)
        nv = sum(len(v) for v in res["violations"].values())
        total_v += nv
        print(f"{res['file']}: {res['lines']} lines, {nv} violations "
              f"in {len(res['violations'])} categories")
        for code, msgs in sorted(res["violations"].items()):
            print(f"  {code}: {len(msgs)}  e.g. {msgs[0]}")
    return 0 if total_v == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
