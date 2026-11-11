#!/usr/bin/env python3
"""Decision-by-decision differ for the cross-engine harness JSONL files.

Loads two files in the dsdriver schema (one JSON object per line) and compares them on
(game_id, decision_idx):

  * lines missing from either side;
  * actor/kind mismatches (pair is otherwise not comparable);
  * the sorted "legal" token sets, both directions;
  * every scalar state field (vp, defcon, turn, action_round, ar_side, milops, space,
    hand_sizes, discard_count, draw_count, removed_count, dice, terminal, winner);
  * the influence dict, as key-set differences and value differences.

Emits counts per discrepancy category plus the first N examples with the full lines.
Exit 0 when there are no discrepancies, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

SCALARS = ("vp", "defcon", "turn", "action_round", "ar_side", "milops", "space", "hand_sizes",
           "discard_count", "draw_count", "removed_count", "dice", "terminal", "winner")


def load(path: str) -> dict[tuple[int, int], dict[str, Any]]:
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec["game_id"], rec["decision_idx"])
            if key in rows:
                raise ValueError(f"{path}:{lineno}: duplicate (game_id, decision_idx) {key}")
            rows[key] = rec
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--max-examples", type=int, default=10)
    args = ap.parse_args()

    a, b = load(args.file_a), load(args.file_b)
    counts: dict[str, int] = {}
    examples: list[str] = []

    def note(category: str, detail: str) -> None:
        counts[category] = counts.get(category, 0) + 1
        if len(examples) < args.max_examples:
            examples.append(f"[{category}] {detail}")

    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        gid, didx = key
        if ra is None:
            note("line_missing_in_a", f"game {gid} decision {didx}: only in {args.file_b}: {json.dumps(rb)}")
            continue
        if rb is None:
            note("line_missing_in_b", f"game {gid} decision {didx}: only in {args.file_a}: {json.dumps(ra)}")
            continue
        if ra["actor"] != rb["actor"] or ra["kind"] != rb["kind"]:
            note("actor_or_kind_mismatch",
                 f"game {gid} decision {didx}: a=({ra['actor']},{ra['kind']}) b=({rb['actor']},{rb['kind']})")
            continue
        sa, sb = set(ra["legal"]), set(rb["legal"])
        if sa - sb:
            note("legal_only_in_a", f"game {gid} decision {didx} ({ra['kind']}): {sorted(sa - sb)}")
        if sb - sa:
            note("legal_only_in_b", f"game {gid} decision {didx} ({ra['kind']}): {sorted(sb - sa)}")
        for field in SCALARS:
            if ra[field] != rb[field]:
                note(f"field:{field}",
                     f"game {gid} decision {didx} ({ra['kind']}): a={ra[field]!r} b={rb[field]!r}")
        ia, ib = ra["influence"], rb["influence"]
        if set(ia) - set(ib):
            note("influence_only_in_a", f"game {gid} decision {didx}: {sorted(set(ia) - set(ib))}")
        if set(ib) - set(ia):
            note("influence_only_in_b", f"game {gid} decision {didx}: {sorted(set(ib) - set(ia))}")
        for c in sorted(set(ia) & set(ib)):
            if ia[c] != ib[c]:
                note("influence_value_diff",
                     f"game {gid} decision {didx} ({ra['kind']}): {c} a={ia[c]} b={ib[c]}")

    print(f"{args.file_a} vs {args.file_b}: "
          f"{len(a)} / {len(b)} lines, {sum(counts.values())} discrepancies "
          f"in {len(counts)} categories")
    for cat in sorted(counts):
        print(f"  {cat}: {counts[cat]}")
    if examples:
        print("first examples:")
        for ex in examples:
            print(f"  {ex}")
    return 0 if not counts else 1


if __name__ == "__main__":
    sys.exit(main())
