# REF-API.md — Pre-AI Twilight Struggle reference engine (validation reference)

Reference engine for independently validating the rules of the DeepStruggle engine
(`/data/repos/DeepStruggle`, commit `7d3fd8928b95b288757ab6660be7297689f1c653`).

## 1. Pinned engine and how to reproduce

| item | value |
|---|---|
| repo | https://github.com/glowsplint/twilight-struggle-py |
| clone | `/data/repos/twilight-struggle-py-preAI` |
| pinned SHA | `a30ad14304bb28e29450cf223b85ca783bc3db19` |
| commit date | 2020-03-15T15:58:58Z ("Merge pull request #17 from glowsplint/update") |
| first AI commit (excluded) | `5927f479226925e629ca4be80ec696e8f0ac1b5f`, 2026-02-11T15:28:38Z, "Fix 10 card bugs and add 201 unit tests" (Co-Authored-By: Claude Opus 4.6) |

Reproduce the pin:

```bash
git clone https://github.com/glowsplint/twilight-struggle-py.git /data/repos/twilight-struggle-py-preAI
git -C /data/repos/twilight-struggle-py-preAI checkout a30ad14304bb28e29450cf223b85ca783bc3db19
git -C /data/repos/twilight-struggle-py-preAI apply /data/repos/ts-validation/patches/expand_deck.patch
```

The GitHub commits API lists commits newest-first; commit dates go
2020-03-15T15:58:58Z → 2026-02-11T15:28:38Z with nothing in between, so
`a30ad143` is provably the last pre-AI commit. `REF-PIN.txt` records the same.

Pure stdlib, Python 3.13 (system python3), no packages installed; `/data/venv` untouched.
The only working-tree modification is `patches/expand_deck.patch` (see §7).

## 2. Game / Input API (exact names)

Modules (repo root): `game_mechanics.py`, `twilight_cards.py`, `twilight_map.py`,
`twilight_enums.py`, `twilight_input_output.py`, `twilight_playerview.py`, `twilight_ui.py`.

```python
from game_mechanics import Game
from twilight_enums import Side, InputType, CardAction, MapRegion

g = Game()
g.start(handicap=0)          # driver uses handicap=0 = standard game.
                             # Engine default is -2 (gives US 2 extra starting
                             # influence via put_start_extra) — non-standard.
```

* `Side` (`twilight_enums.py`): `IntEnum`, `USSR=0, US=1, NEUTRAL=2`; `.opp`, `.toStr()`,
  `.fromStr(s)`, `.vp_mult` (+1 USSR, −1 US, 0 NEUTRAL).
* `InputType`: `COMMIT=0, ROLL_DICE=1, SELECT_CARD_ACTION=3, SELECT_CARD=4, SELECT_COUNTRY=5, SELECT_MULTIPLE=6`.
* `CardAction`: `PLAY_EVENT=0, RESOLVE_EVENT_FIRST=1, INFLUENCE=2, REALIGNMENT=3, COUP=4, SPACE=5, SKIP_OPTIONAL_AR=6`.
* `Game.start()` builds `stage_list` (reversed) = `[expand_deck, deal, put_start_USSR,
  put_start_US, put_start_extra, process_headline]`; stages pop from the end.
* Driving loop (same pattern as `twilight_ui.UI.game_state_changed`):

```python
while True:
    if game.input_state is None:
        game.stage_complete(); continue      # stage_list.pop()() — runs next stage
    ist = game.input_state                   # an Input, or None between stages
    if ist.complete:
        game.stage_complete(); continue
    # ... ist.side / ist.state / ist.available_options / ist.recv(option) ...
```

* `Input` (`twilight_input_output.py:5`): fields `side`, `state`, `callback`,
  `prompt`, `reps`, `reps_unit`, `max_per_option`, `option_stop_early`, `selection`
  (dict option→count), `discarded_options` (set).
  * `available_options` — **generator** (yield each option once); materialize with
    `list(...)`. Yields options not in `discarded_options` and with count < `max_per_option`.
  * `recv(option)` → bool. Calls `callback(option)`; on True increments
    `selection[option]`. Returns False if option not currently available or the
    callback rejects it (e.g. `ops_influence_callback` refuses to place the last
    op into an opponent-controlled country) — **the driver must retry other options**.
  * `complete` → `not reps or len(selection) == len(discarded_options)`.
  * `option_stop_early` (e.g. `'Stop realignments.'`, `'Do not discard.'`) is
    selectable via `recv` but is NOT in `available_options`; the reference UI adds
    it explicitly (`twilight_ui.py:129-130`). The driver mirrors this.
* State access on `Game`: `vp_track`, `turn_track` (1..), `ar_track` (0 = headline
  phase), `ar_side` (Side or None), `defcon_track`, `milops_track` (list, `[USSR, US]`),
  `space_track` (list, `[USSR, US]`), `spaced_turns`, `hand` (list of 3 lists:
  `[USSR_hand, US_hand, neutral]` of card-name strings), `discard_pile`,
  `draw_pile`, `removed_pile`, `limbo`, `basket` (`[USSR_basket, US_basket]` list of
  effect-name strings), `headline_bin`, `map` (GameMap), `cards` (GameCards).
* `GameMap.ALL` : dict country-name → `Country`. `Country.influence` = **`[ussr, us]`**
  (`twilight_map.py:512`). `Country.control` property. Superpowers exist as map
  entries `USSR` (influence `[999, 0]`) and `US` (`[0, 999]`).
* `GameCards[name]` → `Card` instance; `GameCards.early_war/mid_war/late_war` are
  lists of card-name strings (39 Early War + China Card, 48 Mid War, 23 Late War;
  deck is a SUBSET of the real game's card list — card-by-card comparison needed).
* `g.score(MapRegion.X)` implements region scoring (also used by scoring cards).

## 3. Dice (player-supplied inputs)

All dice are prompts of `InputType.ROLL_DICE` with `side == Side.NEUTRAL`, created by
`Game.dice_stage(fn, two_dice=False, reroll_ties=False)` (`game_mechanics.py:827`):

* 1d6: options are the **strings** `'1'..'6'` (coup, wars, space race, Quagmire/Bear Trap).
* 2d6 (realignment only): options are **tuples** `(i, j)`, `i,j ∈ 1..6` —
  `(USSR roll, US roll)` per the prompt text; passed to
  `GameMap.realignment(name, side, ussr_roll, us_roll)`.
* reroll-ties variant (some cards, `twilight_cards.py:671`): tuples `(i+2, j)`,
  sponsor roll 3..8, `i+2 != j`.

The engine never rolls dice itself; the "player" feeds the value via
`input_state.recv(option)` where `option` is the string or tuple exactly as offered.
The driver draws uniformly over the offered options with the seeded RNG (see §5),
so e.g. a 2d6 roll is a uniform draw over the 36 tuples. There are no dice
modifiers baked into the option list — modifiers are applied inside the callbacks
(`war_dice_callback`, `coup_dice_callback`, etc.).

## 4. Deck order

* `expand_deck` (turns 1/4/8): puts the Early/Mid/Late War pile into `draw_pile`.
  Turn 1: `The_China_Card` is popped into the USSR hand first (this is the patched
  behavior; unpatched the entire deck was dealt into hands — see §7).
* `shuffle_draw_pile_stage`: a `Side.NEUTRAL` `SELECT_CARD` prompt, `reps=len(pile)`,
  `max_per_option=1` — a "player-driven shuffle": the shuffler picks remaining cards
  one at a time, each pick is appended to the fresh `draw_pile`.
* `deal()` (`game_mechanics.py:1167`) then deals alternating cards starting USSR via
  `draw_pile.pop()` — i.e. **the deck order is the REVERSE of the shuffle-pick order;
  the last pick is the first card dealt**. Hand size 8/8 (turns 1–3) or 9/9 (turns 4+),
  +1 for the China Card holder. If the draw pile empties mid-deal, the discard pile
  becomes the new shuffle prompt.
* Consequence: deck order is fully determined by the driver's seeded choices at
  shuffle prompts (actor `CHANCE`), not by any engine RNG (the engine contains no
  `random` usage at all — verified by grep).

## 5. VP sign convention + RNG/reproducibility contract

* **Engine**: `vp_track` is POSITIVE = USSR AHEAD (`game_mechanics.py:67` "positive
  for ussr"; `change_vp` docstring; `Side.vp_mult` +1/−1). Auto-terminate at
  `vp_track >= 20` or `<= -20` (`change_vp`, game_mechanics.py:154).
* **Driver/JSONL normalization**: emitted `vp = -vp_track`, so **POSITIVE VP = US AHEAD**
  in every JSON line. Winner inference: `vp_track > 0 → 'USSR'`, `< 0 → 'US'`,
  `== 0 → 'DRAW'` (note: the engine's `terminate()` print calls a 0-VP game a US win;
  the driver reports DRAW instead).
* Seeding: for game `i` (0-based), `random.seed(base_seed + i)` immediately before
  `Game()` construction; `game_id = i`, per-line `seed = base_seed + i`.
* All chance flows through the driver: CHANCE prompts (`side == NEUTRAL`: all
  ROLL_DICE prompts + deck-shuffle SELECT_CARD prompts) are resolved with
  `random.choice` over the sorted remaining options, **even under `--policy first`**
  (that policy governs US/USSR decisions only). Random policy also uses
  `random.choice` over sorted options for player decisions. Rejected options
  (recv → False) consume additional RNG draws deterministically.
* Options are always SORTED (lexicographic, by canonical string) before choosing,
  because the engine's option sets come from Python `set`s
  (`CountryInfo.REGION_ALL`) whose iteration order is hash-randomized per process.
  With sorting, trajectories are byte-identical across processes (verified: two
  runs → identical md5, without fixing PYTHONHASHSEED).

## 6. Option-string format per InputType ("legal" list; sorted lexicographically)

| InputType | canonical option string | raw value passed to `recv` |
|---|---|---|
| `SELECT_CARD` | card name, e.g. `Five_Year_Plan`; plus `option_stop_early` strings like `Do not discard.`, `Do not take a card.` | the string |
| `SELECT_CARD_ACTION` | `CardAction` name: `PLAY_EVENT`, `RESOLVE_EVENT_FIRST`, `INFLUENCE`, `REALIGNMENT`, `COUP`, `SPACE`, `SKIP_OPTIONAL_AR` | the string |
| `SELECT_COUNTRY` | country name, e.g. `West_Germany` (note `UK`, `US`, `USSR` are country names too); plus `Stop realignments.` | the string |
| `SELECT_MULTIPLE` | card-specific option strings (passed through verbatim) | the string |
| `ROLL_DICE` | 1d6: `'1'..'6'`; 2d6: `'i,j'` = `USSR_roll,US_roll` (e.g. `'3,5'`); reroll-ties: `'i+2,j'` with sponsor roll 3..8, no ties | 1d6: the string; 2d6: the tuple `(i, j)` |

`legal` in each JSON line = ALL options offered at that decision (including
`option_stop_early`), canonicalized as above, sorted lexicographically. The
`dice` field carries `[d6]` or `[ussr_d6, us_d6]` when the decision itself was a
ROLL_DICE prompt, else `[]`.

## 7. Known bugs in the pinned engine (found during this work)

Fixed (mandated minimal patch `patches/expand_deck.patch`):

1. **`expand_deck` test code** — `game_mechanics.py:1131-1157`: the turn-1 branch
   dealt the ENTIRE deck (39+48+23 cards) into both hands via a "TEST CODE" block,
   leaving `draw_pile` empty, the shuffle prompt at `reps=0`, `deal()` a no-op, and
   the turn-4/8 expansions no-ops; the real "deal China Card to USSR" lines were
   commented out. Patch comments out the test block and restores the two
   "WORKING CODE" lines. Nothing else changed.

Not fixed (documented; driver aborts or enforces around them):

2. **`terminate()` is ineffective inside `end_of_turn`** — `game_mechanics.py:99-114`:
   it only clears `stage_list` and prints; the remaining `end_of_turn` code
   (`game_mechanics.py:1277-1287`) re-appends stages, so a game that "ends" at a
   turn boundary (held scoring card, `final_scoring`) keeps playing into the next
   turn. VP±20/DEFCON-1 terminations mid-round DO leave `stage_list` empty; the
   driver detects that (`stage_list` empty with pending input) and ends the game.
3. **`final_scoring` is dead code + unconditional terminate** — `game_mechanics.py:1258-1270`:
   the turn-10 condition `turn_track == 10 and ar_track in [15,16,17]` can never be
   true (`ar_track` is per-turn, 0 after `advance_turn_marker`), and `terminate()`
   is called unconditionally on EVERY end of turn (printing "victory!" every turn,
   neutralized by bug 2). Also references nonexistent methods `Game._Asia_Scoring`
   etc. (would AttributeError if the condition ever fired). The driver enforces the
   end of turn 10 itself: after `turn_track` reaches 11 it calls `g.score(region)`
   for the six main regions (ASIA, EUROPE, MIDDLE_EAST, CENTRAL_AMERICA,
   SOUTH_AMERICA, AFRICA — engine's own scoring code), adds the engine's
   China-Card-held bonus (`change_vp(s.vp_mult)`), and ends the game by VP sign.
4. **Held scoring card ends the game only on paper** — `game_mechanics.py:1206-1214`:
   `check_for_scoring_cards` correctly detects a held scoring card at end of turn
   (`Card.__eq__` compares against the string name, `twilight_cards.py:73`) and
   calls `terminate`, but bug 2 makes it ineffective. The driver enforces it: when
   `turn_track` advances to T ≤ 10 and a scoring card is still in a hand, the
   holder loses immediately (engine checks US hand first; driver mirrors that
   priority). 37/50 games in the reference batch end this way — it is the dominant
   real end condition under random play.
5. **`Suez_Crisis` deadlock** — `twilight_cards.py:846-859`: prompt is created with
   fixed `reps=4` but options only cover countries with US influence; if total US
   influence in France/UK/Israel is < 4 (or options get exhausted via
   `max_per_option=2` + `remove_option`), `available_options` empties while
   `complete` stays False → the engine can never accept further input. Driver
   aborts the game (`ABORTED`, kind `GameAborted: stuck prompt`). Hit by seeds
   3, 8, 9, 12, 19, 44, 48 of the reference batch (7/50 games).
6. **`Star_Wars` callback arity crash** — `twilight_cards.py:2462-2477`:
   `use_event` builds `partial(self.callback, game_instance, side)` but
   `callback(self, game_instance, card_name)` takes no `side` → TypeError when the
   event fires (US ahead on space race + played from discard).
7. **`Terrorism` callback arity crash** — `twilight_cards.py:2611-2632`:
   `self.callback(self, game_instance, side, card_name)` is passed raw as the Input
   callback, which calls `callback(option)` → TypeError "missing 2 required
   positional arguments". (Present in the 2026 AI tree too — not among its 10 fixes.)
8. **Space race crash at track 5-7** — `game_mechanics.py:456-464`:
   `enough_ops` uses `card_name.info.ops` where `card_name` is a str (should be
   `self.cards[card_name].info.ops`) → AttributeError when spacing with
   `space_track[side]` in {5,6,7}. (Line 463 is the correct form.)
9. **China Card duplication** — `twilight_cards.py:235-246`: `move_china_card`
   appends the card to the recipient's hand but never removes it from the sender's
   hand (the 2026 AI commit fixes exactly this). The China Card therefore exists
   in both hands after being played.
10. **SALT_Negotiations coup modifier checks `side` twice** — `twilight_map.py:168`:
    `if 'SALT_Negotiations' in basket[side] or 'SALT_Negotiations' in basket[side]`
    (second should be `side.opp`); the −1 advantage applies to both sides when
    either holds it. (Fixed in the 2026 AI commit.)
11. Minor: `space_discard`'s Eagle/Bear-has-landed discard prompt
    (`game_mechanics.py:1217-1229`) is silently overwritten at turns 1/4/8 when
    `expand_deck` replaces `input_state` with the deck-shuffle prompt.
12. Scope: the deck has 39 Early War + 48 Mid War + 23 Late War cards (+ The China
    Card) — a SUBSET of the real game's card list; several real cards are missing
    or implemented as blanks (`Blank_1_Op_Card`..`Blank_4_Op_Card`). Validation must
    compare card-by-card, not deck-count-by-deck-count.

## 8. Reference driver + output artifacts

* Driver: `/data/repos/ts-validation/refdriver.py`
  (`--seed N --games G --policy {first,random} --out FILE [--show-engine-output]`).
* One JSON line per decision (post-decision state snapshot; `legal` = options
  offered pre-decision) + exactly one final line per game (`kind='GAME_END'` or
  `'ABORTED'`, `actor='CHANCE'`, `legal=[]`, `terminal=true`, `winner` set or null).

Line schema (field order preserved):

```json
{"game_id": int, "seed": int, "decision_idx": int,
 "actor": "US"|"USSR"|"CHANCE",
 "kind": "SELECT_CARD"|"SELECT_CARD_ACTION"|"SELECT_COUNTRY"|"SELECT_MULTIPLE"|"ROLL_DICE"|"GAME_END"|"ABORTED",
 "legal": ["<canonical option string>", ...],
 "vp": int,             // NORMALIZED: positive = US ahead (engine is positive=USSR)
 "defcon": int,         // 1..5
 "turn": int,           // 1..; 11 = end of turn 10 reached (final scoring)
 "action_round": int,   // 0 = headline phase
 "ar_side": "US"|"USSR"|"NONE",
 "milops": [ussr, us],
 "space": [ussr, us],
 "hand_sizes": {"US": int, "USSR": int},
 "influence": {"<country name>": [ussr_inf, us_inf], ...},  // non-zero countries only; superpowers appear as [999,0]/[0,999]
 "discard_count": int, "draw_count": int, "removed_count": int,
 "dice": [ints rolled at this decision if ROLL_DICE, else []],
 "terminal": bool,
 "winner": null|"US"|"USSR"|"DRAW"}
```

End kinds observed (summary files `*.summary.json` next to each output):
`HELD_SCORING_CARD` (bug-4 enforcement), `ENGINE_TERMINATE` (VP±20/DEFCON 1
mid-round), `FINAL_SCORING_T10` (driver-enforced turn-10 scoring), `ABORTED`
(engine deadlock/crash; `winner: null`).

## 9. Reference batch results

Command (step 5 of the mandate):

```
python3 /data/repos/ts-validation/refdriver.py --seed 1 --games 50 --policy random \
    --out /data/repos/ts-validation/ref_random_s1.jsonl
```

* **43 / 50 games completed** (7 aborted, all on the Suez_Crisis deadlock, seeds
  3, 8, 9, 12, 19, 44, 48). End kinds: 37 HELD_SCORING_CARD, 6 ENGINE_TERMINATE.
* 5,309 decisions in 0.48 s ≈ **11,100 decisions/s ≈ 105 games/s** (2 CPU cores,
  single-threaded; engine prints silenced).
* Byte-identical on re-run (md5 `9c506a3c245df3e682e37a684a79097d`), and
  `--policy first` is likewise deterministic (49/50 completed, 1 Suez abort).
* Max turn reached: 4 — under random play most games end at the end of turn 1 via
  the held-scoring-card rule, so mid/late-war coverage in the JSONL is thin.

## 10. Concerns about using this engine as the validation reference

1. **Game-end logic is broken at the engine level** (bugs 2–4): without the
   driver's enforcement the engine never reliably terminates and prints bogus
   "victory!" lines every turn. Validation of DeepStruggle's end-of-game handling
   against this reference rests on the DRIVER's enforcement, which is itself an
   interpretation (six-region final scoring, holder-loses priority US-first).
2. **Suez_Crisis makes ~14% of random games unplayable** (bug 5); any headless
   harness on this engine needs the same abort-and-skip strategy.
3. **Multiple event cards crash on trigger** (bugs 6, 7, 8) — mid/late-war coverage
   is further limited; Terrorism/Star_Wars games abort if those events fire.
4. **Card set is incomplete and the China Card duplicates** (bugs 9, 12) — good for
   validating core mechanics (influence, coups, realignment, DEFCON, milops,
   scoring, headline phase, deck recycling), weak for full-card-deck parity.
5. Reproducibility is a DRIVER property (sorted options + seeded choices), not an
   engine property; any adapter must replicate the contract in §5 exactly.
