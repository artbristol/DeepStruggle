# DeepStruggle (`ts_engine`) API notes for the cross-engine rules-validation harness

Repo: `/data/repos/DeepStruggle` at commit `7d3fd8928b95b288757ab6660be7297689f1c653` (main).
Everything here was verified against the built module, not just the docs. Module: `ts_engine`
(nanobind), at `build/release/ts_engine.cpython-314-x86_64-linux-gnu.so`; run everything with
`PYTHONPATH=/data/repos/DeepStruggle:/data/repos/DeepStruggle/build/release /data/venv/bin/python`.
Authoritative docs in-repo: `bindings/AGENTS.md`, `engine/AGENTS.md`, `CLAUDE.md`, `BUGS.md`.

The engine is a C++20 zero-allocation Twilight Struggle (Deluxe, 110 cards) simulation. A whole
`ts::GameState` is trivially copyable, ≤ 4 KB, and holds *everything* including the decision state
machine (`ctx_stack`) and the RNG, so a game is fully determined by `(seed, action sequence)`.

---

## 1. Starting a game with a deal seed

```python
import ts_engine as ts
state = ts.GameState()
ts.Engine.init_game(state, seed)      # uint64; seeds the game's SplitMix64 RNG
```

- `init_game` (`engine/src/state_machine.cpp:154 init_new_game`) zeroes the state, sets
  `state.rng_state = seed` (seed 0 becomes `0x123456789ABCDEF0`), writes the fixed 1985 setup
  influence (USSR: Syria 1, Iraq 1, North Korea 3, East Germany 3, Finland 1; US: Iran 1,
  Israel 1, Japan 1, Australia 4, Philippines 1, South Korea 1, Panama 1, South Africa 1,
  UK 5), deals 8 cards per side (USSR draws first, one card at a time — ENG-5), and opens on
  the **setup placement decisions**: `turn=1, action_round=0`, `Phase.SETUP`,
  `DecisionType.POINT_NODE`, USSR places first.
- All randomness (deals, reshuffles, dice, random discards like Terrorism) comes from
  `state.rng_state` through `ts::Prng` (§9). Same seed ⇒ bit-identical game.
- Mid-game injection: `ts.state_from_save_dict(d)` / `state_from_save_json(text)` rebuild any
  position from a `ts_save_v2` save (§8). Forced hands/dice can be injected programmatically (§7).

## 2. Stepping

```python
ts.Engine.step(state, MicroAction, auto_advance=False)        # raises RuntimeError if refused
ts.Engine.try_step(state, MicroAction, auto_advance=False)    # returns bool (fuzzers only)
ts.Engine.step_flat(state, flat_idx, auto_advance=False, merged_influence=False)   # raises
ts.Engine.try_step_flat(state, flat_idx, auto_advance=False, merged_influence=False)
ts.Engine.auto_advance_step(state, max_steps=128)             # advance free decisions manually
```

- `auto_advance=False` stops at **every** engine decision, including chance nodes — this is what
  the harness driver uses (one JSON line per exposed decision).
- `auto_advance=True` advances through decisions that have exactly one legal action. The
  vectorized runner (`ts.VectorizedBatchRunner`, used by `bindings/ts_env.py`) always settles
  chance internally and **never exposes a ROLL_DIE at all**.
- A refused `step` means the action was not in the mask you should have sampled (`step()` raises
  `RuntimeError` naming what was asked; `try_step*` is for legality probing only).
- `merged_influence=True` is the E4.1 composed-influence view (P23) — same 220 slots, NODE slots
  at op-choice nodes mean "influence, first point here". Default everywhere is the E4 view
  (`False`), which is what the driver uses.
- Terminal test: `ts.Engine.is_terminal(state)` (`Phase.GAME_OVER` or `|vp| ≥ 20`).
  `ts.Engine.get_terminal_utility(state)` returns **+1.0 = US win, −1.0 = USSR win, 0.0 = draw**
  (it reads only the sign of `victory_points`, so mid-game it means "who is ahead"; only trust it
  when `is_terminal`). Ending reasons: `ts.game_ending_reason(state)`.

## 3. Legal actions: two mask spaces (not interchangeable!)

| API | shape | meaning |
|:---|:---|:---|
| `ts.Engine.get_legal_action_mask(state)` | list ≤ 128 | **per-decision** mask; index meaning depends on the decision type (below) |
| `ts.Engine.get_legal_action_indices(state)` | list[int] | legal indices of the per-decision mask |
| `ts.Engine.get_flat_action_mask(state, merged_influence=False)` | 220 `uint8` | **flat action space**; what `step_flat` consumes |
| `ts.decode_flat_action(state, idx)` | `MicroAction` | decode a flat index (raises outside the space) |
| `ts.encode_micro_action(state, MicroAction)` | int | encode; −1 when no slot encodes it (never aliased to CONFIRM_DONE) |

Per-decision mask semantics (`bindings/state_json.cpp:690` labels them the same way):
`SELECT_CARD`: index = card id 1..110 (0 unused); `SELECT_PLAY_MODE`: 0..4 = `Resolution`;
`SELECT_OP_MODE`: 0..2 = `OpMode`; `POINT_NODE`: 0..83 = country id, 84 = Done/Pass;
`CHOOSE_BRANCH`: 0..7 = branch id; `ROLL_DIE`: 0..6 = die faces, 0 = "roll normally".
`bindings/action_encoder.py` is the Python codec; `ts.FLAT_*` exports the slot offsets (read
them, never copy the numbers — `tests/bindings/test_flat_layout_agrees.py` holds the two to
each other).

### Flat action space (220 wide; `flat_slots` in `engine/include/ts/action_mask.hpp`)

| slot range | width | meaning |
|:---|:---|:---|
| 0–109 | 110 | `SELECT_CARD`, index = card id − 1 |
| 110–114 | 5 | `SELECT_PLAY_MODE` → `Resolution`: 0 EVENT, 1 SPACE, 2 OPS_INFLUENCE, 3 OPS_COUP, 4 OPS_REALIGN |
| 112–114 | 3 | `SELECT_OP_MODE` → `OpMode`: 0 INFLUENCE, 1 COUP, 2 REALIGN (**same slots** as the OPS_* resolutions) |
| 115 | 1 | `ROLL_DIE` (the only legal flat action at a chance node; decodes to die 0 = "roll normally") |
| 116–199 | 84 | `POINT_NODE`, index − 116 = country id 0..83 |
| 200–207 | 8 | `CHOOSE_BRANCH`, index − 200 = branch id 0..7 |
| 208 | 1 | `CONFIRM_DONE` / PASS / early-stop Ops |
| 209–213 | 5 | set DEFCON to 1..5 (Summit, How I Learned to Stop Worrying) |
| 214–219 | 6 | region (Chernobyl), `Region` order: Europe, Asia, Middle East, Africa, Central America, South America |

`CHOOSE_TIMING_BRANCH` (DecisionType 3) is retired since P17: the resolution itself carries the
timing (EVENT on an opponent card = event-first; any OPS_* = ops-first).

## 4. `DecisionType` enum (`engine/include/ts/types.hpp`)

`NONE=0, SELECT_CARD=1, SELECT_PLAY_MODE=2, CHOOSE_TIMING_BRANCH=3 (retired), SELECT_OP_MODE=4,
POINT_NODE=5, CHOOSE_BRANCH=6, ROLL_DIE=7`.

Related: `Resolution {EVENT=0, SPACE=1, OPS_INFLUENCE=2, OPS_COUP=3, OPS_REALIGN=4}`,
`OpMode {INFLUENCE=0, COUP=1, REALIGN=2}`, `Phase {SETUP, HEADLINE, ACTION_ROUND, INTERRUPT,
DISCARD, END_TURN, GAME_OVER}`, `Player {USSR=-1, NONE=0, US=1}`,
`RollType {NONE=0, COUP=1, REALIGNMENT=2, SPACE_RACE=3, WAR_EVENT=4, OLYMPIC_GAMES=5, SUMMIT=6,
TRAP_ESCAPE=7, TURN_CLEANUP=8}` (TURN_CLEANUP is the end-of-turn cleanup parked on the chance
node — it rolls no die). The nanobind enums are `nb::is_arithmetic()`: they behave like ints and
have no `.name`; build your own value→name table (the driver does).

## 5. ROLL_DIE decisions and forced dice / die injection

A chance node is a real decision in the step stream: `ctx().decision_type == ROLL_DIE`,
`ctx().decision_player == NONE`, and the roll kind is `ctx().pending_roll_type` (a `RollType`);
`ctx().roll_target` / `ctx().roll_actor` name what/who the roll is for. The flat mask offers
exactly one action (slot 115); without forcing, the engine rolls `state.rng_state`'s die when the
action is applied.

**Forced dice are supported programmatically** — this is how the web workbench implements its
manual-die feature (`bindings/wasm/ts_engine_wasm.cpp:100 drain()`: it loops
`while ctx.decision_type == ROLL_DIE`, passing `MicroAction{ROLL_DIE, forced_die, 0, 0}`;
`ts_step(..., forced_die)` validates 0..6). From Python:

```python
ts.Engine.step(state, ts.MicroAction(ts.DecisionType.ROLL_DIE, face, 0, 0))
```

- `primary_id` = the **acting player's** die, `secondary_id` = the opponent's; **0 = roll from the
  RNG**, 1..6 = force that face. Realignment is the only roll that consumes both dice; the mapping
  to sides happens in `StateMachine::step` (`engine/src/state_machine.cpp:1502`), which is what
  `tests/engine_logic/test_forced_dice_are_absolute.py` pins (a forced die is absolute, belongs to
  the roller, and is never stored in the state — "forced dice deliberately do NOT live here",
  `game_state.hpp:174`).
- Range check: `primary_id > 6 || secondary_id > 6` is refused (`state_machine.cpp:914`), so the
  255 sentinel cannot be smuggled in.
- Forced dice are "a test and replayer affordance rather than game state" — exactly the hook a
  cross-engine harness needs to make both engines roll the same dice.

**Forced deals** (programmatic card injection for the next deal):
`state.set_forced_deal(us_cards, ussr_cards)` / `state.get_forced_deal_remaining()`
(`game_state.hpp:304`, `FORCED_DEAL_MAX = 9` per side; `tests/bindings/test_forced_deal.py`,
fixed in `dfadce5` precisely so replays can drive a deal). A deal tops a hand up from the forced
list before drawing.

Also injectable via field access (tests do this): `state.current_phase`, `state.turn`,
`state.action_round`, `state.phasing_player`, `state.ctx().decision_player/decision_type/...`,
`state.set_card_location(id, loc)`, `state.set_country(...)`, `state.set_flag/clear_flag`,
`state.set_space_turns_used`. `state.get_country(i)` returns a **copy** (writes do not stick).
`state.clone()` for copies; `state.raw_bytes()` for byte-exact equality.

## 6. Observations

- `ts.extract_observation(state, perspective)` → float32[3824]. **One layout, v2.3**:
  84×26 board + 110×14 cards + 100 global = 3824 (`ts.OBS_SIZE`, `ts.OBS_SIZE_V23`).
  Nothing takes a `layout` argument. `perspective` is `ts.Player.US`/`USSR`; card knowledge is
  canonicalized per observer (own hand vs opponent's known/unknown hand).
- `ts.extract_observation_features(state, perspective, features)` — base layout plus the feature
  blocks requested by `features` (an `ts.OBS_FEATURE_*` bitset; **no default**, unknown bits
  raise). Blocks so far: `OBS_FEATURE_OPS_BUDGET` (bit 1, +3 floats) and
  `OBS_FEATURE_HEADLINE_REVEAL` (bit 2, no width — changes card-row content only).
  `ts.obs_size_for(features)` gives the width; `ts.OBS_FEATURES_ALL` every bit.
- Golden pin: `tests/engine_logic/test_observation_golden.py` + `observation.golden.npz`
  (4,288 observations over 40 games, both perspectives, lowest-legal-action walk).

## 7. Reading state: `state_to_dict` / field access

`ts.state_to_dict(state)` (== `state.to_dict()`, the display state; `bindings/state_json.cpp`
`display_state`) keys: `victory_points, defcon, mil_ops{US,USSR}, space{US,USSR}, turn,
action_round, phasing_player, current_phase(_name), headline_us_card, headline_ussr_card,
headline_first_card, headline_second_card, headline_stage, forced_card_player, forced_card_id,
last_die_roll, last_opp_die_roll, die_roll{type,type_id,roller,card_id,card_name,country_id,
country_name,roll1,mod1,total1,roll2,mod2,total2,success,net_delta}, event_tracks[{card_id,
card_name,vp_delta,defcon_delta}], space_turns_used{US,USSR}, china_card{holder,playable},
flags[...], persistent_effects, countries{<name> → {id,name,stability,battleground,region,
us_influence,ussr_influence,controlled_by}}, hands{US:[ids],USSR:[ids],US_cards:[{id,name,ops}],
USSR_cards:[...]}, discard_pile[id...], removed_pile, unavailable_cards, draw_deck_count,
card_locations{"1".."110" → location name}, decision_context{...}, legal_actions{decision_type,
decision_type_name, decision_player, valid_ids, valid_action_labels, allow_early_stop},
is_terminal, terminal_utility`.

Cheap alternative for per-decision logging: `state.to_save_dict()` (58 µs measured) returns
everything the driver needs as arrays: `us_influence`/`ussr_influence` (84 each),
`card_locations` (111 ints), `last_roll{type,roller,card_id,country_id,roll1,mod1,roll2,mod2,
success,net_delta}`, `last_die_roll`/`last_opp_die_roll`, the tracks and scalars (§8). The full
display dict costs ~220 µs.

- **VP sign convention: the engine's `victory_points` is already US-positive** (+20 = US win,
  −20 = USSR win; `game_state.hpp:267`; `EventTrackRecord.vp_delta` "positive toward the US").
  The harness schema's "vp" is the engine value unchanged: positive = US ahead.
- `mil_ops` / `space`: per-side counters, `us_*` / `ussr_*`.
- **Hands**: 4-way locations (`HAND_{US,USSR}_{UNKNOWN,KNOWN}`); count via
  `ts.in_hand_of(loc, player)`. `hands.US` in the display dict lists card ids in the US hand.
- **Countries**: exactly 84, ids 0..83, canonical names from `ts.MapData.get_country_name(id)`
  (= the `countries` keys of the display dict, in id order):
  Canada, United Kingdom, Norway, Sweden, Denmark, Finland, Benelux, West Germany, France,
  Spain/Portugal, Italy, Greece, Turkey, Austria, East Germany, Poland, Czechoslovakia, Hungary,
  Yugoslavia, Romania, Bulgaria, Lebanon, Syria, Israel, Iraq, Iran, Jordan, Gulf States,
  Saudi Arabia, Egypt, Libya, Afghanistan, Pakistan, India, Burma, Laos/Cambodia, Thailand,
  Vietnam, Malaysia, Indonesia, Philippines, Australia, Taiwan, North Korea, South Korea, Japan,
  Morocco, Algeria, Tunisia, West African States, Saharan States, Sudan, Ivory Coast, Nigeria,
  Ethiopia, Somalia, Cameroon, Zaire, Kenya, Angola, Zimbabwe, SE African States, Botswana,
  South Africa, Mexico, Guatemala, El Salvador, Honduras, Costa Rica, Nicaragua, Panama, Cuba,
  Haiti, Dominican Rep, Colombia, Ecuador, Peru, Venezuela, Bolivia, Brazil, Paraguay, Chile,
  Argentina, Uruguay.
- **Cards**: ids 1..110, names from `ts.CardData.get_card_name(id)` (`rules/cards.json` is the
  same table). Note the exact Unicode: “We Will Bury You”, “Lone Gunman”, “Ask Not What Your
  Country Can Do For You…”, “One Small Step…”, “An Evil Empire” (curly quotes and ellipsis).

## 8. Save format `ts_save_v2`

`state.to_save_dict()` / `state.to_save_json()` (canonical JSON: sorted keys, compact; identical
bytes to the WebAssembly build). Loader: `ts.state_from_save_dict(d)` / `state_from_save_json(t)`.

Keys: `format="ts_save_v2"`, `victory_points, defcon, turn, action_round, us_mil_ops,
ussr_mil_ops, us_space_track, ussr_space_track, phasing_player, current_phase, headline_us_card,
headline_ussr_card, headline_first_card, headline_second_card, headline_stage, forced_card_player,
forced_card_id, defcon_dropped_to_2, china_card_holder, china_card_playable, persistent_effects,
rng_state, headline_first_owner, headline_second_owner, last_die_roll, last_opp_die_roll,
last_roll{type,roller,card_id,country_id,roll1,mod1,roll2,mod2,success,net_delta},
last_event_tracks[{card_id,vp_delta,defcon_delta}], ctx_stack[<full DecisionContext frames>,
incl. start_influence_nodes/visited_nodes/node_count_bits], ctx_stack_depth, card_locations[111],
us_influence[84], ussr_influence[84]`.

- The `ctx_stack` is what makes it **v2**: a saved mid-decision position restores at the *same*
  decision (v1 restored at a different one in 91/97 positions). Loaders reject out-of-range
  enums/DEFCON/VP/turn/tracks/locations and a supplied `ctx_stack_depth` outside the six-entry
  stack; unknown keys ignored, missing keys defaulted. `action_history`/`turn_aggregates` are
  deliberately not saved (no rule or observation reads them).

## 9. Determinize and the PRNG

- **PRNG**: `ts::Prng` (`engine/include/ts/prng.hpp`) is stateless SplitMix64 over
  `state.rng_state` (a single `uint64`): `next_u64`, `roll_d6 = 1 + (u64 % 6)` (bias < 1e-18),
  `random_index(state, size) = u64 % size`. Everything stochastic goes through it (invariant 4),
  so `(seed, actions)` replays are bit-exact and `state.rng_state` alone carries all future
  randomness. `ts.keyed_key(state, key, keyed2=False)` implements the keyed-chance rekeying used
  by the rollout batches.
- **Determinize**: `ts.determinize(state, me, seed, keep_hand=False, keep_revealed=False)` → a
  clone with the cards `me` cannot see (opponent's unknown hand + draw deck) reshuffled from
  SplitMix64 `seed`, counts and seen cards kept, an unrevealed opposing headline forgotten.
  `keep_hand=True` keeps the opponent's true hand (oracle world); `keep_revealed=True` keeps a
  Space-Race-box-4 revealed headline. (`bindings/rollout_batch.cpp`, the C++ port of
  `ai/search/dmcts.determinize`.)

## 10. Canonical action tokens (the harness contract, implemented by `dsdriver.py`)

`"legal"` is the sorted list of tokens for every legal **flat** index, decoded per decision:

| decision | token |
|:---|:---|
| `SELECT_CARD` | `card <id> <CardData name>` (e.g. `card 4 Duck and Cover`) |
| `SELECT_PLAY_MODE` | `EVENT` / `SPACE` / `OPS_INFLUENCE` / `OPS_COUP` / `OPS_REALIGN` |
| `SELECT_OP_MODE` | `INFLUENCE` / `COUP` / `REALIGN` |
| `POINT_NODE` (op_mode INFLUENCE) | `+1 <Country>` — one influence per point-decision (cost is 1 op, or 2 into an opponent-controlled country; `Operations::place_influence` always adds exactly 1) |
| `POINT_NODE` (op_mode COUP / REALIGN) | `coup <Country>` / `realign <Country>` (also the CMC payment node, which names the country the 2 influence is paid from) |
| `POINT_NODE` Done/Pass | `confirm_done` |
| `ROLL_DIE` | `roll` (including the no-roll TURN_CLEANUP chance step) |
| `CHOOSE_BRANCH` (Summit, How I Learned…) | `defcon <1..5>` |
| `CHOOSE_BRANCH` (Chernobyl) | `region <Region name>` |
| `CHOOSE_BRANCH` (Warsaw Pact Formed) | `branch remove_us_influence` / `branch add_ussr_influence` |
| `CHOOSE_BRANCH` (Olympic Games) | `branch participate` / `branch boycott` |
| `CHOOSE_BRANCH` (Wargames) | `branch end_game` / `branch continue` |
| `CHOOSE_BRANCH` (other/unknown) | `branch <id>` |
| any CONFIRM_DONE slot | `confirm_done` |

Branch semantics per `engine/src/events/*.cpp` and the workbench's `web/ui/src/game/branches.ts`
(the engine asks for a branch in exactly six events).

## 11. Driver conventions (`dsdriver.py`)

- `--seed N --games G --policy {first,random} --out FILE`; one JSON line per decision.
- Decisions are the engine's exposed decisions with `auto_advance=False` (so ROLL_DIE lines
  appear, `actor="CHANCE"`); each line records the state **before** the action.
- `decision_idx` counts lines from 0; the **last line of a game is its terminal state**, not a
  decision (`kind` from the leftover context, `legal: []`, `terminal: true`, `winner` set).
- `legal`: sorted canonical tokens (§10) of the 220-wide flat mask.
- `vp`: engine `victory_points` unchanged — **positive = US ahead** (§7).
- `ar_side`: `phasing_player` ("US"/"USSR"/"NONE"); `actor`: `ctx().decision_player`, or CHANCE
  for ROLL_DIE, falling back to `phasing_player` when the decider is NONE outside a roll.
- `dice`: the engine's `last_roll` record **at the decision** = the dice of the immediately
  preceding step: `[roll1]`, or `[roll1, roll2]` for realignment; `[]` when the previous step
  rolled nothing. (The engine keeps no dice history; per-step dice for forced-die harness runs
  should use the forced-die API, §5.)
- `random` policy: `random.Random(f"{seed}:{game_id}")`, uniform over legal flat indices.
- Per-game state fields: `milops=[USSR, US]`, `space=[USSR, US]`, `hand_sizes={"US","USSR"}`
  (cards in hand, either knowledge variant), `influence={name: [USSR, US]}` non-zero only,
  `discard_count`/`draw_count`/`removed_count` from card locations, `defcon`, `turn`,
  `action_round`.

## 12. Native validation entry points

```
./build/release/engine/ts_tests              # C++ suite: 435 tests
./build/release/engine/ts_fuzz --games 10000       # invariant fuzz, whole games
./build/release/engine/ts_fuzz_events --games 10000# event-biased fuzz
./build/release/engine/ts_benchmark
PYTHONPATH=.:build/release python -m pytest tests/engine_logic/test_observation_golden.py -x -q
```

pytest refuses to run against an engine without a `.engine_fingerprint` stamp — run
`TS_PYTHON=/data/venv/bin/python tools/scripts/check_engine_fresh.sh` once after building (it
hashes sources, rebuilds if stale, and stamps; exit 0 = fresh).

## 13. Suspicious things noticed (see also `DISCREPANCIES.md`)

From `BUGS.md` (all open, low severity): **TEST-1** — the repo's own differential suite
(`tests/differential/` vs `external/struggler`) fails at import and is excluded from collection,
so this harness is exactly the check the repo currently lacks; **BIND-1** — long scans can stop
on a nanobind instance collision (not reproduced; could in principle corrupt silently);
**CONV-3** — converted human-replay discard piles drift from turn 4 (0.15 unspent cards per
decision); Missile Envy is missing from the receiver's solved hand for a stretch of decisions.
Code reading: `get_terminal_utility` reports the VP-sign leader even mid-game (harmless if only
read at terminal); the flat `SELECT_OP_MODE` slots are aliased onto `OPS_*` resolution slots
(index 112..114 mean both — the decision type disambiguates); card names contain curly
quotes/ellipsis that must survive any cross-engine name mapping byte-exactly.
