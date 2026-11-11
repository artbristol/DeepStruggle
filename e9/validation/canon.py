#!/usr/bin/env python3
"""canon.py -- canonical vocabulary shared by the DeepStruggle and reference-engine
mirror drivers.

One canonical token set, three encodings:

  1. DeepStruggle flat action indices (220-wide space, decoded per decision type;
     see DS-API.md §3/§10).
  2. Reference-engine option strings (InputType-keyed; see REF-API.md §6).
  3. Canonical tokens (this module) -- the join key and the policy space.

Canonical token grammar
-----------------------
  card <id> <DS card name>       SELECT_CARD (id = DS card id, 1..110; name byte-exact)
  EVENT | SPACE | OPS_INFLUENCE | OPS_COUP | OPS_REALIGN     play-mode / card-action
  INFLUENCE | COUP | REALIGN     op-mode choice
  +1 <Country>                   one influence placement (DS name, e.g. "+1 West Germany")
  coup <Country>                 coup attempt target
  realign <Country>              realignment attempt target
  confirm_done                   pass / done / early stop / decline
  roll                           a die roll (dice themselves are the shared stream's business)
  defcon <1..5>                  Summit / How I Learned to Stop Worrying DEFCON set
  region <Region name>           Chernobyl designated region
  branch <name>                  engine-branch choices (Warsaw Pact Formed, Olympic
                                 Games, Wargames; unknown branches fall back to "branch <id>")
  skip_optional_ar               REF-only CardAction SKIP_OPTIONAL_AR (compare-scalar-only:
                                 DS has no such decision kind)

Country names are the DeepStruggle map names (84, e.g. "United Kingdom", "Spain/Portugal",
"Dominican Rep"). Card names are the DeepStruggle card names (Unicode-exact curly quotes and
ellipses on four cards). The reference engine's names are derived mechanically.

DS-only decision kinds (no REF counterpart) and REF-only kinds are flagged in
DECISION_COVERAGE so the differ can mark them compare-scalar-only.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------

# REF card name -> DS card id / DS card name. Built from the pinned reference
# engine's Card.INDEX (card_index == DS id was verified for all 110 real cards)
# and DS rules/cards.json. The 4 REF "Blank_N_Op_Card" placeholders have no DS
# counterpart; they appear only as discarded-ops placeholders in REF and are
# mapped to None (compare-scalar-only).

# Authoritative DS tables, loaded from the pinned repo's rules JSON (pure data,
# no ts_engine import needed). rules/cards.json is documented as byte-identical to
# ts.CardData (DS-API.md §6); rules/map.json likewise for the 84 country names.
import json as _json
import os as _os

_DS_RULES_DIR = _os.environ.get("DS_RULES_DIR", "/data/repos/DeepStruggle/rules")

with open(_os.path.join(_DS_RULES_DIR, "cards.json")) as _f:
    _cards_json = _json.load(_f)
_DS_NAMES: dict[int, str] = {c["id"]: c["name"] for c in _cards_json}
assert len(_DS_NAMES) == 110 and set(_DS_NAMES) == set(range(1, 111))

with open(_os.path.join(_DS_RULES_DIR, "map.json")) as _f:
    _map_json = _json.load(_f)
DS_COUNTRY_NAMES = [c["name"] for c in sorted(_map_json["countries"], key=lambda c: c["id"])]
assert len(DS_COUNTRY_NAMES) == 84

# Mechanical REF-name normalizer plus the irregular cases. Order matters: the
# special-case table is applied to the whole underscored name first.
_REF_NAME_SPECIAL = {
    "COMECON": "Comecon",
    "De_Stalinization": "De-Stalinization",
    "Salt_Negotiations": "SALT Negotiations",
    "Nixon_Plays_The_China_Card": "Nixon Plays the China Card",
    "The_Voice_Of_America": "The Voice of America",
    "Our_Man_In_Tehran": "Our Man in Tehran",
    "U2_Incident": "U-2 Incident",
    "US_Japan_Mutual_Defense_Pact": "US/Japan Mutual Defense Pact",
    "Red_Scare_Purge": "Red Scare/Purge",
    "Arab_Israeli_War": "Arab-Israeli War",
    "Indo_Pakistani_War": "Indo-Pakistani War",
    "Iran_Contra_Scandal": "Iran-Contra Scandal",
    "Iran_Iraq_War": "Iran-Iraq War",
    "Soviets_Shoot_Down_KAL_007": "Soviets Shoot Down KAL-007",
    "Tear_Down_This_Wall": "Tear Down this Wall",
    "An_Evil_Empire": "“An Evil Empire”",
    "Ask_Not_What_Your_Country_Can_Do_For_You": "“Ask Not What Your Country Can Do For You…”",
    "Lone_Gunman": "“Lone Gunman”",
    "One_Small_Step": "“One Small Step…”",
    "We_Will_Bury_You": "“We Will Bury You”",
}

REF_NAME_TO_DS_ID: dict[str, int | None] = {}
for _id, _name in _DS_NAMES.items():
    _ref = {v: k for k, v in _REF_NAME_SPECIAL.items()}.get(_name)
    if _ref is None:
        _ref = _name.replace(" ", "_")
    REF_NAME_TO_DS_ID[_ref] = _id
REF_NAME_TO_DS_ID["The_China_Card"] = 6
# REF-only placeholders (discarded-ops markers); no DS counterpart.
for _b in ("Blank_1_Op_Card", "Blank_2_Op_Card", "Blank_3_Op_Card", "Blank_4_Op_Card"):
    REF_NAME_TO_DS_ID[_b] = None

DS_ID_TO_REF_NAME: dict[int, str] = {v: k for k, v in REF_NAME_TO_DS_ID.items() if v is not None}
DS_ID_TO_NAME: dict[int, str] = dict(_DS_NAMES)
NAME_TO_DS_ID: dict[str, int] = {v: k for k, v in _DS_NAMES.items()}


def ref_card_to_token(ref_name: str) -> str | None:
    """REF card-name option -> canonical card token (None for REF-only blanks)."""
    cid = REF_NAME_TO_DS_ID.get(ref_name)
    if cid is None:
        return None if ref_name.startswith("Blank_") else f"card? {ref_name}"
    return f"card {cid} {_DS_NAMES[cid]}"


# --------------------------------------------------------------------------
# Countries
# --------------------------------------------------------------------------

# DS country names, id order 0..83 (84 countries; ids are the join key for DS).


_REF_COUNTRY_SPECIAL = {
    "UK": "United Kingdom",
    "Spain_Portugal": "Spain/Portugal",
    "Laos_Cambodia": "Laos/Cambodia",
    "Dominican_Republic": "Dominican Rep",
}

REF_COUNTRY_TO_DS: dict[str, str] = {}
for _n in DS_COUNTRY_NAMES:
    _ref = {v: k for k, v in _REF_COUNTRY_SPECIAL.items()}.get(_n, _n.replace(" ", "_"))
    REF_COUNTRY_TO_DS[_ref] = _n
DS_COUNTRY_TO_REF: dict[str, str] = {v: k for k, v in REF_COUNTRY_TO_DS.items()}
REF_SUPERPOWERS = {"US": "US", "USSR": "USSR"}


def ref_country_to_ds(ref_name: str) -> str | None:
    """REF country option -> DS country name (superpowers pass through)."""
    if ref_name in REF_SUPERPOWERS:
        return ref_name
    return REF_COUNTRY_TO_DS.get(ref_name)


# --------------------------------------------------------------------------
# Play modes / card actions
# --------------------------------------------------------------------------

# REF CardAction name -> canonical token.
REF_CARD_ACTION_TO_TOKEN = {
    "PLAY_EVENT": "EVENT",
    "RESOLVE_EVENT_FIRST": "EVENT",   # DS encodes event-first as the EVENT mode itself
    "INFLUENCE": "OPS_INFLUENCE",
    "REALIGNMENT": "OPS_REALIGN",
    "COUP": "OPS_COUP",
    "SPACE": "SPACE",
    "SKIP_OPTIONAL_AR": "skip_optional_ar",   # compare-scalar-only (DS: no such decision)
}

# DS Resolution / OpMode token -> canonical.
DS_RESOLUTION_TO_TOKEN = ("EVENT", "SPACE", "OPS_INFLUENCE", "OPS_COUP", "OPS_REALIGN")
DS_OPMODE_TO_TOKEN = ("INFLUENCE", "COUP", "REALIGN")

# --------------------------------------------------------------------------
# Branch choices per resolving card (DS CHOOSE_BRANCH; REF SELECT_MULTIPLE strings)
# --------------------------------------------------------------------------

# Canonical branch token tables: DS branch id -> token, and REF option substring -> token.
BRANCH_TABLES: dict[str, dict] = {
    "Warsaw Pact Formed": {
        "ds": {0: "branch remove_us_influence", 1: "branch add_ussr_influence"},
        "ref_contains": [("remove all us influence", "branch remove_us_influence"),
                         ("add 5 ussr", "branch add_ussr_influence")],
    },
    "Olympic Games": {
        "ds": {0: "branch participate", 1: "branch boycott"},
        "ref_contains": [("participate", "branch participate"),
                         ("boycott", "branch boycott")],
    },
    "Wargames": {
        "ds": {0: "branch end_game", 1: "branch continue"},
        "ref_contains": [],  # REF Wargames has NO branch: it terminates unconditionally
    },
}

# REF SELECT_MULTIPLE option-string -> canonical token, for prompts whose DS
# counterpart is a different decision kind (documented per-card in CANON.md).
REF_MULTIPLE_TOKENS: list[tuple[str, str]] = [
    # (substring, token) -- matched case-insensitively, first hit wins
    ("free coup attempt", "OPS_COUP"),
    ("free realignment rolls", "OPS_REALIGN"),
    ("use card normally", "EVENT"),
    ("use card with un intervention", "EVENT"),   # UN-intervened event: same DS shape
    ("return card to ussr", "confirm_done"),
]

# How I Learned to Stop Worrying: 'DEFCON N: ...' absolute levels.
def ref_multiple_token(opt: str, card_ctx: str | None) -> str | None:
    s = str(opt).lower()
    if card_ctx == "How I Learned to Stop Worrying" and s.startswith("defcon "):
        try:
            return f"defcon {int(s.split()[1].strip(':'))}"
        except (ValueError, IndexError):
            return None
    for frag, tok in REF_MULTIPLE_TOKENS:
        if frag in s:
            return tok
    if card_ctx == "Chernobyl":
        for r in DS_REGION_NAMES:
            if s == r.lower():
                return f"region {r}"
    return None

# Summit / How I Learned DEFCON set: DS 'defcon <level>'. REF Summit offers
# 'DEFCON -1' / 'No change' / 'DEFCON +1' (relative); HILTSW offers absolute levels.
REF_SUMMIT_DEFCON = [("DEFCON -1", -1), ("No change", 0), ("DEFCON +1", +1)]

# Chernobyl: DS region tokens; REF option strings (checked against the live engine).
DS_REGION_NAMES = ("Europe", "Asia", "Middle East", "Africa", "Central America",
                   "South America")

# --------------------------------------------------------------------------
# REF stop-early / misc option strings -> canonical
# --------------------------------------------------------------------------

REF_STOP_EARLY_TO_TOKEN = {
    "Do not discard.": "confirm_done",
    "Do not take a card.": "confirm_done",
    "Stop realignments.": "confirm_done",
    "Do not place.": "confirm_done",
    "Do not coup.": "confirm_done",
    "Do not realign.": "confirm_done",
    "Do not discard": "confirm_done",
}

# --------------------------------------------------------------------------
# Decision-kind coverage (for compare-scalar-only marking)
# --------------------------------------------------------------------------

DECISION_COVERAGE = {
    # kind: (DS has it, REF has it, note)
    "SELECT_CARD": (True, True, "both; DS selects by id, REF by name"),
    "SELECT_PLAY_MODE": (True, True, "DS Resolution vs REF CardAction"),
    "SELECT_OP_MODE": (True, True, "DS OpMode vs REF CardAction ops modes"),
    "POINT_NODE": (True, True, "influence/coup/realign/war-target/event-target nodes"),
    "CHOOSE_BRANCH": (True, True, "six DS events; REF uses SELECT_MULTIPLE strings"),
    "ROLL_DIE": (True, True, "dice injected from the shared stream"),
    "SELECT_MULTIPLE": (True, True, "DS uses CHOOSE_BRANCH ids; REF uses strings"),
    "SELECT_COUNTRY": (True, True, "REF prompt kind; DS exposes POINT_NODE"),
    "SKIP_OPTIONAL_AR": (False, True, "REF-only optional-AR skip (China Card optional ARs)"),
    "CHOOSE_TIMING_BRANCH": (False, True, "retired in DS (P17); REF RESOLVE_EVENT_FIRST "
                                           "maps to DS EVENT mode"),
}


class DiceStream:
    """Shared deterministic per-game die stream.

    Both engines consume the SAME values in the SAME order. One draw = one d6
    (1..6). Draws happen only at roll decisions; multi-die decisions consume
    consecutive values. The stream is seeded from the game seed via a documented
    PRNG: random.Random(f"dice:{seed}:{game_id}") -- Python's Mersenne Twister,
    drawn with randrange(6) + 1.

    Olympic Games: the sponsor's die and participant's die must differ (REF's
    option set excludes ties; DS's reroll loop only runs when NOT forced). The
    stream therefore redraws the participant's die on a tie at Olympic rolls
    (documented exception; both engines see the same final pair).
    """

    def __init__(self, seed: int, game_id: int):
        import random as _random
        self._rng = _random.Random(f"dice:{seed}:{game_id}")
        self.draws = 0

    def d6(self) -> int:
        self.draws += 1
        return 1 + self._rng.randrange(6)

    def pair_no_ties(self) -> tuple[int, int]:
        a = self.d6()
        b = self.d6()
        while b == a:
            b = self.d6()
        return a, b


def sort_tokens(tokens) -> list[str]:
    """Canonical token sort: lexicographic (both adapters sort identically)."""
    return sorted(tokens)
