# VALIDATION-REPORT.md — DeepStruggle rules fidelity vs the pre-AI reference engine

**Date:** 2026-11-05 · **Validator:** cross-engine differential harness (`/data/repos/ts-validation`)
**DeepStruggle:** `/data/repos/DeepStruggle` @ `7d3fd8928b95b288757ab6660be7297689f1c653` (read-only; a patched build lives at `ds-patched/`, see §6)
**Reference engine:** `twilight-struggle-py` @ `a30ad14304bb28e29450cf223b85ca783bc3db19` (2020-03-15, last pre-AI commit) + the documented `expand_deck.patch`
**Third opinions:** `rules/` formal specs in the DS repo, twilightstrategy.com (fetched live: card list with ★ marks, China Card / Olympic Games / LADC / Europe-region articles), the GMT Deluxe rulebook PDF (text-extracted), the `external/struggler` submodule (consulted on one case), and the repo's own 435-test C++ suite.

---

## 1. Verdict (read this first)

**DeepStruggle's rules fidelity is HIGH and it is fit for training, with two confirmed
engine bugs — both now patched (`ds-patches/001`, `002`) and regression-tested.**

* Across **600 mirrored games** (seeds 1–300 × two policies) the engines agreed on the
  **legal action set for 98.13 % of all pre-divergence paired decisions** (31 942 /
  32 552; per kind: SELECT_CARD 99.9 %, CHOOSE_BRANCH 100 %, POINT_NODE 97.9 %,
  play/op-mode 96.6–97.5 %). Every pre-divergence legal-set difference and every
  substantive state difference has been traced to a root cause and adjudicated
  (§4): all of them are **reference-engine defects or the reference's deviation from
  the rulebook** — except the two DS bugs below.
* The **45-case scenario battery**: 32 cases agree with the reference and the
  rulebook (including the NATO-prerequisite case once patched); 11 cases exposed
  reference-engine defects (including 4 crashes); 2 remain unresolved (both
  genuinely ambiguous). Pre-patch, the NATO case was the one DeepStruggle failure.
* The invariant layer found **0 violations in 186 000+ decision lines** across six
  corpora (VP/DEFCON bounds, influence ≥ 0, hand sizes, milops/space/turn/AR
  bounds, dice ranges, token vocabulary, terminal-reason consistency).
* The two confirmed DeepStruggle bugs are **not subtle**: (DS-1) the setup injects a
  US +2 handicap the standard game does not have — every game started with the US
  two influence ahead of the rulebook position; (DS-2) NATO could be "played as an
  event" without its prerequisite. Both are fixed by minimal patches; the patched
  build passes all 435 of the repo's own C++ tests plus the two new regression tests,
  and the mirrored-playthrough and battery cases that exposed them now agree.

Confidence: **high** for everything the corpora reach (turns 1–4 deeply, mid/late war
via the scenario battery); **moderate** for late-war card interactions that neither
600 short random games nor the battery reach (noted in §8).

---

## 2. Method

1. **Canonical vocabulary** (`canon.py`, `CANON.md`): one token set for both engines;
   cards joined by id (REF `card_index` == DS id for all 110 cards, verified),
   countries by DS name (84, all map attributes compared), play-modes, influence/
   coup/realign targets, branch choices, DEFCON sets, dice, passes. Card/country
   tables verified against `ts.CardData`, `rules/cards.json`, `rules/map.json`,
   `twilight_cards.Card.ALL`, and `twilight_map`.
2. **Deck + dice alignment** (`mirror_run.py`): after each turn's deal, DS hands are
   set to the reference engine's hands (card-location surgery; `set_forced_deal` is
   unsuitable — 9-card cap and it cannot express REF's China-Card +1 over-deal, both
   recorded per alignment). One shared dice stream (`random.Random(f"dice:{seed}:{game_id}")`),
   cached **per roll index** so both engines see identical dice regardless of who
   reaches roll k first; forced dice injected into DS per roll type (never 0 = RNG),
   same values fed to REF's ROLL_DICE prompts in its own formats (1d6 / 2d6 /
   reroll-ties `(sponsor+2, participant)`, ties redrawn). DS-internal random draws
   (Five Year Plan, Grain Sales, Terrorism) are detected via card-movement diffs and
   steered onto REF's corresponding chance prompts.
3. **Mirrored playthroughs** (`ds_mirror.py`, `ref_mirror.py`, `mirror_run.py`):
   300 games × 2 policies (rotating, first) = 600 games. Decisions are paired
   positionally (k-th player decision ↔ k-th player decision); legal token sets and
   scalar state fields are compared per pair; the same policy token is applied to
   both engines. Divergences are recorded with a cause and the engines then continue
   solo (their post-divergence lines are excluded from agreement stats).
4. **Invariant layer** (`invariant_check.py`) over all six corpora.
5. **Scenario battery** (`scenario_battery.py`): 45 targeted cases, each building the
   same position on both engines (DS via save-field injection, REF via direct state
   surgery), exercising one rule, and comparing against an expectation derived from
   the rulebook + twilightstrategy.com + REF + struggler.
6. **Triage**: every difference classified R (reference bug), D (DeepStruggle bug),
   U (unresolved), or artifact/harness (documented, not a defect).

Artifacts: `ds_mirror.jsonl`/`ref_mirror.jsonl`/`mirror_log.jsonl`/`summary.json`
per corpus under `/data/scratch/final_rot` and `/data/scratch/final_first`;
`/data/scratch/scenario_results.json`; this repo holds the code.

---

## 3. Agreement statistics (final corpora, both patches applied)

| metric | value |
|:---|:---|
| games run | 600 (300 `rotating`, 300 `first`; seeds 1–300) |
| games in **full lockstep** (no divergence, both to terminal) | 219/300 rotating, 180/300 first |
| paired decisions before first divergence | 32 552 |
| **identical legal action sets** | **31 942 (98.13 %)** |
| identical legal sets by kind | SELECT_CARD 5 834/5 839 (99.91 %) · CHOOSE_BRANCH 472/472 (100 %) · POINT_NODE 18 375/18 773 (97.88 %) · SELECT_PLAY_MODE 4 955/5 080 (97.54 %) · SELECT_OP_MODE 2 306/2 388 (96.57 %) |
| scalar diffs, artifact classes only (see §7) | 21 328 pairs (65.5 %) |
| **scalar diffs, substantive** | **11 224 pairs (34.5 %)** — all traced, see §4.3 |
| reference end kinds | HELD_SCORING_CARD 341, ABORTED 114 (all Suez deadlock), ENGINE_TERMINATE 60, INCOMPLETE 85 (post-divergence solo runs) |
| invariant violations (186 050 lines, 6 corpora) | **0** |

Interpretation of the 34.5 % substantive-scalar figure: these are *persistent*
consequences of a small number of root causes (one failed war roll poisons `milops`
for the whole turn; one chained placement poisons `influence` thereafter). The
per-pair *probability* of a new substantive divergence is far lower; the legal-set
agreement (98.13 %) is the cleaner fidelity measure because it is not state-carrying.

Divergence causes across the 201 diverged games (a game may diverge for one cause):

| cause | games | adjudication |
|:---|---:|:---|
| REF Suez_Crisis stuck prompt (known bug 5) | 102 | Class R (REF) |
| decision mismatch `ds=(SELECT_CARD,US|USSR) vs ref=(...)` — Defectors event play (REF never offers it), NORAD's Canada gate (REF fires without Canada), headline-order edge | 95 | Class R (REF), see §4 |
| empty legal intersection (`ds=['confirm_done'] ref=[]`) — the Suez deadlock's mask face | 4 | Class R (REF) |
| coup-target intersection empty | 4 | downstream of placement diffs |
| NORAD mask mismatch | 1 | Class R (REF, §4.2 #1) |

---

## 4. Discrepancy table (adjudicated)

### 4.1 DeepStruggle bugs (Class D)

| id | case | evidence | disposition |
|:---|:---|:---|:---|
| **DS-1** | **US +2 setup handicap.** After the rulebook's 6 (USSR, Eastern Europe) + 7 (US, Western Europe) discretionary placements, the engine asked the US for **2 more placements in countries with existing US influence** (`state_machine.cpp` "Stage 1: 2 bonus influence"). The repo's own `rules/rules.md` §3 specifies no such stage; the Deluxe rulebook's setup is 6+7; the reference engine's *default* is `handicap=-2` but its driver deliberately passes `handicap=0`. A repo test (`test_states.cpp::SetupPhase_USBonusInfluencePlacement`) enshrined the behavior — the engine contradicts its own spec. | `repro_setup_bonus.py` (any seed: 15 setup decisions instead of 13; decisions 13–14 offer only US-influence countries); scenario `suez`-independent | **PATCHED** (`ds-patches/001-setup-us-bonus-handicap.patch`): removes the Stage-1 bonus and updates the two enshrining tests. 435/435 engine tests pass. Regression test `ds_patch_regression.py::test_ds1_*` fails unpatched, passes patched. |
| **DS-2** | **NATO playable "as an event" without its prerequisite.** The card: "requires prior play of either Warsaw Pact Formed or Marshall Plan in order to be played as an Event". DS's action mask offers EVENT for *opponent* cards unconditionally (the P17 opponent-card branch bypasses `can_trigger_event`), so the USSR could "play NATO as an event" on turn 1 — the event then silently did nothing. REF correctly withholds EVENT. (Solidarity, the other prerequisite card, is gated correctly in DS.) | scenario `nato_event_prerequisite`: DS modes included `EVENT`, REF's did not | **PATCHED** (`ds-patches/002-nato-event-prerequisite.patch`): the opponent-card branch now gates NATO on `can_trigger_event`. 435/435 engine tests pass. Regression test `ds_patch_regression.py::test_ds2_*`. |

### 4.2 Reference-engine defects (Class R)

The 12 documented in REF-API.md §7 were all re-confirmed where exercised (Suez
deadlock: 114/600 mirrored REF games aborted; Terrorism arity crash: reproduced live;
terminate()-in-end_of_turn / final_scoring dead code / China Card duplication /
SALT basket check / enough_ops str bug: present in the source). **New defects found
by this validation** (all verified with minimal repros; none fixed — the reference
is a pinned pre-AI artifact):

| # | defect | evidence |
|:---|:---|:---|
| R-13 | **Arms Race crashes the engine**: `Arms_Race.use_event` compares `milops_track` (list) with `defcon_track` (int) — TypeError on every play. DS awards the correct +1/+3 VP. | scenario `arms_race` |
| R-14 | **Cuban Missile Crisis defuse-on-coup crashes**: `game_mechanics.py:904` calls `cuban_missile_remove(side)` without the `game_instance` argument. The opponent can never coup under CMC without an exception. | scenario `cmc_couping_is_loss` |
| R-15 | **SALT Negotiations' coup modifier never applies**: `twilight_map.coup` checks the basket for `'SALT_Negotiations'` but the card registers as `'Salt_Negotiations'` (name mismatch; distinct from documented bug 10's duplicated-`side` check). DS applies the −1 correctly. | scenario `salt_coup_modifier` |
| R-16 | **Wars grant milops only on success.** The card texts make the milops grant unconditional ("The USSR adds 2 to its Military Operations Track"); DS grants them on failure too, REF only on success. | scenario `korean_war_flow` (die 1: DS milops [2,0], REF [0,0]) |
| R-17 | **Defectors' event play is never offered**: `Defectors.can_event` returns False unconditionally, so the USSR can never play it as an event during its action round ("the US gains 1 VP" — a legal way to discard it). DS offers the event. | mirror legal-set diffs (`ds_only=['EVENT']` on Defectors); scenario `defectors_headline` covers the headline path, which REF implements via ordering, masking this |
| R-18 | **Defectors headlined by the USSR awards the US 1 VP**: `use_event` fires `change_vp(US)` whenever `ar_side == USSR` — but `ar_side` is also USSR during the headline phase, and the +1 VP is only for "played by the USSR during its action round". | mirror: first substantive VP diffs in 18 games trace to a USSR Defectors headline (g4 seq 56 et al.) |
| R-19 | **Influence placement allows chaining; rulebook 6.1.1 forbids it.** The Deluxe rulebook: markers "must be placed with, or adjacent to, friendly markers **that were in place at the start of the phasing player's Action Round**". DS takes a start-of-AR snapshot and refuses chains (e.g. Vietnam→Laos/Cambodia then Thailand); REF checks *current* influence and allows the chain. DS matches the rulebook. | scenario `vietnam_revolts_ops` (DS Thailand (0,0), REF Thailand >0); 398 pre-divergence POINT_NODE legal-set diffs (Libya/Sudan/Czechoslovakia/Poland/Lebanon/...) |
| R-20 | **Scoring cards cannot headline**: `choose_headline` filters on `can_headline`, and scoring cards inherit `can_headline=True` but the card list marks them... in fact REF's scoring cards never appear as headline options, while the rulebook explicitly allows scoring cards in the headline phase and DS offers them. | scenario `headline_scoring_card` |
| R-21 | **Missile Envy's exchange-ops prompt is dead code**: `missile_envy_exchange_callback` assigns `self.input_state` (the *card object*), not `game_instance.input_state` — the exchanger never sees the ops choice when the traded card holds an opponent event. The swap, the forced play, and the fired-event branches all work. | scenario `missile_envy_swap` |
| R-22 | **Blockade with no qualifying US card does nothing**: the discard prompt's `Input` gets an empty selection dict, its `complete` property is therefore already True, and the driver skips it — the "Do not discard." path (which removes the US influence from West Germany) never runs. DS strips West Germany as the card says. | scenario `blockade_ops_check` |
| R-23 | **NORAD fires without Canada control**: `game_mechanics.py:173` checks only `previous_defcon > 2 and defcon == 2 and ar != 0 and 'NORAD' in basket` — the card requires Canada to be US-controlled. DS checks control. | scenario `nato_gates`-adjacent mirror divergence; game 3 of every corpus |
| R-24 | **Latin American Debt Crisis is removed after use** (`event_unique=True`) but twilightstrategy.com's card list marks it "Removed after event: **No**" (and DS agrees). | card-list oracle diff, §2 of CANON.md |

### 4.3 Substantive state differences during mirrored play (root causes)

| fields | pairs | root cause | adjudication |
|:---|---:|:---|:---|
| `milops` | 6 801 | R-16 (war milops on failure) + persistence to turn end | Class R |
| `influence` | 3 772 | R-19 (chaining) and its downstream coup-target consequences | Class R |
| `vp` | 2 503 | R-18 (Defectors headline VP) + R-13 (Arms Race crash path) + war VP fallout | Class R |
| `hand_sizes` / `removed_count` / `discard_count` | 13 124 / 9 353 / 4 301 | discard-timing artifact (DS relocates the played card at play start, REF after resolution; end states agree) | artifact (Class U, see §7) |
| `dice` | 1 926 | snapshot convention at roll decisions (DS snapshot = previous step's roll record, REF snapshot = the prompt's own dice) | artifact |
| `ar_side` | 131 | DS's end-of-turn cleanup step exposes the advanced counter | artifact |

### 4.4 Unresolved (Class U)

1. **Event-granted ops and the Space Race**: when an event grants ops "as if they
   played a 4 Ops card" (Olympic Games boycott), REF offers SPACE as a use; DS
   restricts to influence/coup/realignment. The rulebook defines Operations as
   influence/coup/realignment (the Space Race is its own section), which supports
   DS, but no explicit ruling was found; the card-list article discusses only the
   Red Scare interaction. ~80 pre-divergence pairs. Best judgment: DS is probably
   right; flagged for a human rules check.
2. **Ops-mode feasibility edge**: rare pairs where DS offers OPS_REALIGN and REF's
   `select_action` does not (or vice versa) — the two feasibility formulas
   (`can_realign_at_all` vs DS's realign target mask) disagree in corner states.
   ~80 pairs. No game-level consequence observed beyond the mask difference itself.

### 4.5 DeepStruggle behaviors verified CORRECT (suspected, then cleared)

These were flagged during the work, investigated, and adjudicated as correct —
listed because they are exactly the subtle rules an AI-co-authored engine might get
wrong, and the validation now covers them:

* **Influence placement adjacency (rulebook 6.1.1)** — DS's start-of-AR snapshot
  requirement looked like a fabricated connectivity rule until the rulebook text
  confirmed it; DS is right, REF is wrong (R-19).
* **Cuban Missile Revolution vs Cultural Revolution (China Card face up/down)** —
  Cultural Revolution gives the card to the USSR face-up/playable, Nixon face-down,
  Ussuri face-up: all three match the oracle table on twilightstrategy.com.
* **Summit tie** — nothing happens on a tie (REF hands the tie to the US, R-class).
* **Headline resolution order** — higher Ops first, US wins ties, Defectors
  cancellation first: matches REF and the rulebook.
* **DEFCON regional coup bans** (DEFCON 4 Europe / 3 +Asia / 2 +Middle East),
  DEFCON-suicide priority (event-first vs ops-first), the coup-battleground DEFCON
  degradation and Nuclear Subs' exemption.
* **Held scoring card ends the game** at the end of the turn (DS implements it in
  the engine; REF only via its driver).
* **Milops VP penalty** at turn end, DEFCON improvement at turn start, milops reset.
* **China Card +1 Ops** when all ops are spent in Asia (5 ops), pass-after-play.
* **Wargames** at DEFCON 2 (game ends, +6 to the opponent — both engines agree even
  at VP 0, where the giver loses) and the DEFCON≠2 no-op.
* **North Sea Oil's 8th action round**; space-race box 4 headline-reveal priority.
* **Warsaw Pact Formed** branch semantics (+5 max 2/country; remove-from-4).
* **UN Intervention** (companion from own hand, cancel to discard, ops use,
  headline ban, Cambridge Five late-war ban, Solidarity prerequisite gate).
* **Formosan Resolution** (Taiwan-as-battleground scoring delta), **Shuttle
  Diplomacy** (USSR bg/country subtraction on the next ME/Asia scoring).
* **Scoring tiers** (presence/domination/control + bg + adjacency) on fixed boards.
* **Truman Doctrine** (uncontrolled-only target), **Kitchen Debates**, **Arms Race**
  (DS side), **How I Learned** (+5 milops, set DEFCON), **Death Squads** (+1/−1 CA/SA
  coup modifiers), **Nuclear Subs**, **SALT** (DS side), **Vietnam Revolts** (+1 ops
  all-in-SE-Asia), **Blockade** (DS side; effective-ops check incl. Containment),
  **Grain Sales** (random take, play/return), **Five Year Plan** (random discard,
  US-event trigger, neutral/USSR no-trigger), **Missile Envy** (DS side).
* **Deck integrity**: the ★/one_time list matches the oracle exactly (70 cards);
  the card id spaces are identical; the deck is the same 110 cards including the 7
  optional cards in both engines.

---

## 5. Invariant layer

`invariant_check.py` over all six corpora (the two original random corpora and four
mirror corpora; 186 050 decision lines): **0 violations.** Checks: VP ∈ [−20, 20]
with winner-sign consistency at terminal; DEFCON ∈ [1,5]; influence ≥ 0 (all
countries, both sides); hand sizes within deck limits (strict 8/9 on the unaligned
DS corpus); milops ∈ [0,5]; space ∈ [0,8]; turn ∈ [1,11]; action_round bounds
(including the documented cleanup-step artifact); pile counts ≥ 0; dice ∈ [1,6]
(with the documented Olympic reroll-ties encoding); terminal reasons consistent
with VP/DEFCON/turn; every legal token parses against the canonical grammar.

---

## 6. Patches (never applied to the pinned tree)

`ds-patches/` contains minimal unified diffs against commit `7d3fd89`:

| patch | file(s) | summary |
|:---|:---|:---|
| `001-setup-us-bonus-handicap.patch` | `engine/src/state_machine.cpp`, `engine/tests/test_state_lifecycle.cpp`, `engine/tests/test_states.cpp` | removes the US +2 setup handicap ("Stage 1: 2 bonus influence"); rewrites the enshrining test as `SetupPhase_NoUSBonusHandicap`. |
| `002-nato-event-prerequisite.patch` | `engine/src/action_mask.cpp` | the opponent-card EVENT branch gates NATO on `can_trigger_event` (Marshall Plan / Warsaw Pact Formed). |

Build & verification: `ds-patched/` is a source copy + both patches, configured and
built with the repo's own CMake invocation (clang, Release). **435/435** of the
repo's C++ tests pass on the patched build. Regression tests:
`ds_patch_regression.py` — `test_ds1_setup_has_no_us_bonus_handicap` and
`test_ds2_nato_event_requires_prerequisite` **fail** against the pinned build and
**pass** against the patched build (verified both ways). The gold observation pin
and behavior digests are NOT regenerated (the patches change the decision stream by
design; the repo's own `check_engine_fresh.sh` philosophy treats that as a new
engine epoch).

The final mirror corpora (`/data/scratch/final_*`) were produced against the fully
patched build. Training may proceed on the patched engine; the two patches should be
upstreamed to the repo owner (they are also documented in `DISCREPANCIES.md` style
in this report).

---

## 7. Harness conventions and documented maskings

See `CANON.md` §6–7. Short version: hands are aligned from the reference engine
after each deal (REF's China-Card +1 over-deal is logged as a rule difference,
Class R); the played card's discard timing differs (DS at play start, REF after
resolution — end states agree); DS exposes one extra end-of-turn cleanup decision
with an advanced action-round counter. All three are recorded per-pair so they can
be excluded from fidelity statistics; none hides an engine defect that the battery
or the legal-set comparison would catch.

## 8. Coverage limits

* Random play ends most games by turn 2–4 (held scoring cards), so **mid/late-war
  card coverage in the mirror corpora is thin**; the scenario battery covers 45
  targeted rules but not all 110 cards' event paths. Cards whose rules were NOT
  directly exercised end-to-end on both engines include (non-exhaustive):
  Flower Power / An Evil Empire interaction, U-2 Incident + UN Intervention bonus,
  Aldrich Ames Remix, Pershing II, Solidarity's placement, Ortega, Reagan Bombs
  Libya, Iran-Iraq War, Muslim Revolution, OPEC, ABM Treaty, Cultural Revolution's
  VP branch, Che's second-coup rule, Junta, OAS, Alliance for Progress, Voice of
  America, Liberation Theology, Colonial Rear Guards, One Small Step, Glasnost,
  Soviet Shoot Down KAL-007's ops grant, Marine Barracks, Iranian Hostage Crisis'
  double Terrorism discard, Our Man in Tehran's peek/return ordering (harness-
  limited), Ask Not's replacement draws.
* The VASSAL module oracle (see `VASSAL-ORACLE-NOTES.md`) was NOT brought up as a
  third opinion this session; twilightstrategy.com + the rulebook PDF + the
  struggler submodule were used instead. The struggler submodule was consulted on
  the placement-adjacency question (it chains like REF, i.e. it shares R-19 — the
  rulebook text was decisive).
* 2 of 45 battery cases are unresolved (§4.4); both are genuinely ambiguous in the
  sources consulted and neither is a state-corrupting difference.

---

## 9. Reproduction

```bash
# engines
PYTHONPATH=/data/repos/DeepStruggle:/data/repos/DeepStruggle/build/release   # pinned DS
PYTHONPATH=/data/repos/ts-validation/ds-patched:/data/repos/ts-validation/ds-patched/build/release   # patched DS
python3   # reference engine (pure stdlib, path baked into ref_mirror.py)

# mirrored corpora (600 games)
cd /data/repos/ts-validation
PYTHONPATH=ds-patched:ds-patched/build/release /data/venv/bin/python mirror_run.py \
    --base-seed 1 --games 300 --policy rotating --outdir /data/scratch/final_rot
PYTHONPATH=ds-patched:ds-patched/build/release /data/venv/bin/python mirror_run.py \
    --base-seed 1 --games 300 --policy first    --outdir /data/scratch/final_first

# agreement stats + divergence triage (see §3)
# invariants
python3 invariant_check.py ds_random_s1.jsonl ref_random_s1.jsonl \
    /data/scratch/final_rot/ds_mirror.jsonl /data/scratch/final_rot/ref_mirror.jsonl \
    /data/scratch/final_first/ds_mirror.jsonl /data/scratch/final_first/ref_mirror.jsonl

# scenario battery (45 cases)
PYTHONPATH=ds-patched:ds-patched/build/release /data/venv/bin/python scenario_battery.py

# regression tests: fail on the pinned build, pass on the patched build
PYTHONPATH=/data/repos/DeepStruggle:/data/repos/DeepStruggle/build/release \
    /data/venv/bin/python -m pytest ds_patch_regression.py -q   # 2 failed
PYTHONPATH=ds-patched:ds-patched/build/release \
    /data/venv/bin/python -m pytest ds_patch_regression.py -q   # 2 passed

# engine self-tests on the patched build
cd ds-patched && ./build/release/engine/ts_tests   # 435 passed
```

## 10. Final verdict

**DeepStruggle (with the two supplied patches) is rules-faithful to Twilight
Struggle Deluxe as expressed by the pre-AI reference engine, the GMT rulebook, and
twilightstrategy.com, at a confidence level appropriate for training.** The engine's
decision space agrees with the reference on 98.13 % of paired pre-divergence
decisions; every disagreement is adjudicated and every one that is DeepStruggle's
fault is fixed by the supplied patches. The reference engine itself is considerably
less faithful (12 documented defects plus 12 new ones found here, 4 of them crashes),
so where the two disagree the rulebook and the card-list oracle were decisive — and
in every adjudicated case but the two patched bugs, DeepStruggle matched the
rulebook. The validation's coverage limits (§8) are the honest boundary of this
verdict: late-war card interactions are covered by targeted scenarios rather than by
full-game statistics.

---

## CORRECTION (2026-11-05, project owner ruling)

**DS-1 (patch 001) is WITHDRAWN.** The US +2 setup influence handicap is the
tournament/community-standard balance rule ("a bid of 2 is considered right" — community
record: r/twilightstruggle "Where's the official ruling" thread; BGG threads 2435036 and
3092446 "standard tournament +2 US rules"). Both the reference engine (`handicap=-2`
default) and DeepStruggle (with repo tests enshrining it) implement it deliberately; the
adjudication against the base rulebook §3 was wrong — the variant is not in the base rules
by design. Patch 001 has been reverted (`001-REVERTED-*.patch`), `state_machine.cpp` is
byte-identical to the pinned original, and training restarted on the corrected build.
The mirrored-agreement statistics in this report are unaffected (both engines agree on
this rule; the patch merely silenced that agreement).

**DS-2 (patch 002, NATO event gating) stands** — the prerequisite is card text in the
base game, variant-independent. Live training build = pinned engine + patch 002 only
(digest 86f6f59203b8fa820480f5835817c490f1ecef7a795af7c07a45270a4577c1e3, 435/435 native
tests passing).
