# CANON.md — the canonical vocabulary of the cross-engine harness

This document specifies the single canonical token set that both engines' decision
encodings map onto, the mapping tables, and the alignment contracts (deck, dice,
deals) that make trajectories directly comparable. The executable form of everything
here is `canon.py` (pure data + converters, no engine imports), consumed by
`ds_mirror.py`, `ref_mirror.py`, `mirror_run.py`, and `scenario_battery.py`.

---

## 1. Canonical tokens

Every legal action of either engine is expressed as one of these tokens; a policy
('first' = lexicographically lowest, 'rotating' = deterministic cycle) selects among
the **sorted** token list, and the chosen token is applied to both engines.

| token | meaning | DS encoding | REF encoding |
|:---|:---|:---|:---|
| `card <id> <DS name>` | select/play a card | SELECT_CARD slot `id-1` (flat 0..109) | SELECT_CARD option = REF card name |
| `EVENT` | play as event | SELECT_PLAY_MODE 0 (also covers REF's `RESOLVE_EVENT_FIRST`: DS carries event-first in the mode itself since P17) | CardAction `PLAY_EVENT` / `RESOLVE_EVENT_FIRST` |
| `SPACE` | space race the card | SELECT_PLAY_MODE 1 | CardAction `SPACE` |
| `OPS_INFLUENCE` | ops → influence | SELECT_PLAY_MODE 2 (aliased onto SELECT_OP_MODE 0) | CardAction `INFLUENCE` |
| `OPS_COUP` | ops → coup | SELECT_PLAY_MODE 3 (aliased onto SELECT_OP_MODE 1) | CardAction `COUP` |
| `OPS_REALIGN` | ops → realignment | SELECT_PLAY_MODE 4 (aliased onto SELECT_OP_MODE 2) | CardAction `REALIGNMENT` |
| `+1 <Country>` | place one influence | POINT_NODE country id (flat 116..199); cost 1, or 2 into an enemy-controlled country | SELECT_COUNTRY option (prompt-keyword disambiguated, §4) |
| `coup <Country>` | coup attempt target | POINT_NODE with `ctx().op_mode == COUP` | SELECT_COUNTRY in a coup prompt |
| `realign <Country>` | realignment attempt target | POINT_NODE with `ctx().op_mode == REALIGN` | SELECT_COUNTRY in a realignment prompt |
| `confirm_done` | pass / done / early stop / decline | CONFIRM_DONE slot 208 (MicroAction primary 255 + 0x80) | the prompt's `option_stop_early` string ('Do not discard.', 'Do not take a card.', 'Stop realignments.') |
| `roll` | a die roll (values come from the shared stream) | ROLL_DIE slot 115 + forced dice | ROLL_DICE option |
| `defcon <1..5>` | set DEFCON to a level (Summit, How I Learned) | CHOOSE_BRANCH primary = level (flat 209..213) | SELECT_MULTIPLE 'DEFCON N' (Summit: relative ±1 resolved against the current level) |
| `region <Region>` | Chernobyl designated region | CHOOSE_BRANCH primary = region id (flat 214..219) | SELECT_MULTIPLE region name |
| `branch <name>` | Warsaw Pact Formed / Olympic Games / Wargames branches | CHOOSE_BRANCH 0..7 (`branch remove_us_influence`, `branch add_ussr_influence`, `branch participate`, `branch boycott`, `branch end_game`, `branch continue`) | SELECT_MULTIPLE option strings (matched by fragment, see `canon.BRANCH_TABLES`) |
| `skip_optional_ar` | REF-only CardAction `SKIP_OPTIONAL_AR` | **no DS counterpart — compare-scalar-only** | SELECT_CARD_ACTION |

Unknown REF option strings pass through as `ref:<verbatim>` so a mapping gap is
visible as a diff instead of being silently dropped.

## 2. Card identity

* **Join key: the card id.** The reference engine's `Card.card_index` equals the
  DeepStruggle card id (1..110) for all 110 real cards — verified programmatically
  (`canon.py` asserts it). The four REF `Blank_N_Op_Card` placeholders have no DS
  counterpart (they exist only as discarded-ops markers) and map to `None`.
* **Names differ by encoding**: REF uses underscore names (`Five_Year_Plan`), DS uses
  display names with exact Unicode (`Five Year Plan`, `“We Will Bury You”`,
  `“Ask Not What Your Country Can Do For You…”`, `“Lone Gunman”`,
  `“One Small Step…”`, `“An Evil Empire”`, `U-2 Incident`, `SALT Negotiations`,
  `US/Japan Mutual Defense Pact`, `Red Scare/Purge`, `Arab-Israeli War`,
  `Indo-Pakistani War`, `Iran-Contra Scandal`, `Iran-Iraq War`,
  `Soviets Shoot Down KAL-007`, `Tear Down this Wall`, `De-Stalinization`,
  `Comecon`, `The Voice of America`, `Our Man in Tehran`,
  `Nixon Plays the China Card`). The full mapping lives in `canon.py`
  (`REF_NAME_TO_DS_ID`, `DS_ID_TO_NAME`) and is verified against
  `ts.CardData` and `rules/cards.json` at import.
* **Deck composition**: both engines' decks are the same 110 cards
  (39 Early War + 48 Mid War + 23 Late War, The China Card included in the Early War
  list and never in the draw deck). The 7 optional cards (The Cambridge Five 104,
  Special Relationship 105, NORAD 106, Che 86, Our Man in Tehran 108,
  Yuri and Samantha 109, AWACS Sale to Saudis 110) are **included unconditionally in
  both engines** — neither implements the "optional cards" toggle. The mandate's
  "39+48+23+China Card vs 110" concern resolves to: identical sets, no structural
  mismatch, only the name-encoding difference above.
* **Removed-after-use (★) flags**: DS's `one_time` flags match twilightstrategy.com's
  card list exactly (70 starred cards). REF's `event_unique` flags match except
  **Latin American Debt Crisis**, which REF removes after use but the oracle says
  "Removed after event: No" → REF defect (Class R).

## 3. Country identity

* **Join key: the DS country name** (84 countries, ids 0..83 from
  `ts.MapData` / `rules/map.json`). REF's map has the same 84 countries plus the two
  superpower entries (`US`, `USSR` — constant `[0,999]`/`[999,0]`, stripped from
  snapshots). Name mapping: underscore → space, plus `UK → United Kingdom`,
  `Spain_Portugal → Spain/Portugal`, `Laos_Cambodia → Laos/Cambodia`,
  `Dominican_Republic → Dominican Rep` (DS abbreviates).
* The two engines' country **id orders differ** (e.g. DS id 1 = United Kingdom while
  REF's alphabetical map order differs) — never zip by position; always map by name.
* Region topology (Europe/Asia/Middle East/Africa/Central America/South America,
  sub-regions, battleground flags, stability, adjacency) was compared and matches on
  all 84 countries, including the subtle cases: UK non-battleground (stability 5),
  Canada non-battleground, Thailand battleground, Turkey/Libya/Egypt region
  assignments.

## 4. SELECT_COUNTRY disambiguation (REF side)

REF's SELECT_COUNTRY prompt covers influence placement, coups, realignments, war
targets, and event targeting. The canonical token is chosen from the prompt text:
`coup` in the prompt → `coup <C>`; `realign` → `realign <C>`; otherwise `+1 <C>`
(influence placement AND event targeting — DS renders event-target POINT_NODEs the
same way). War-target prompts (Brush War, Indo-Pakistani War, Iran-Iraq War) also
map to `+1 <C>` because DS exposes war targets as plain POINT_NODEs.

## 5. Decision-kind pairing

The mirror pairs the engines' decisions **positionally** (the k-th player decision of
DS is the k-th player decision of REF — true whenever the rules agree), with
canonical kind aliases:

| DS decision | REF decision | canonical kind |
|:---|:---|:---|
| SELECT_CARD | SELECT_CARD | SELECT_CARD |
| SELECT_PLAY_MODE / SELECT_OP_MODE | SELECT_CARD_ACTION | CARD_ACTION |
| POINT_NODE | SELECT_COUNTRY | COUNTRY |
| CHOOSE_BRANCH | SELECT_MULTIPLE | MULTIPLE |
| ROLL_DIE | ROLL_DICE | ROLL_DICE |

Chance decisions (dice, REF deck shuffles) do not occupy player positions. The only
place where the engines ask for the same decisions in a different ORDER is the
headline selection (DS asks the US first, REF asks the USSR first; space-race box 4
flips both the same way) — handled explicitly with a per-actor legal-set comparison
(`headline_pick_compare`).

Decision kinds that exist in one engine only:
* `SKIP_OPTIONAL_AR` (REF only — the China Card's optional action rounds): **compare-scalar-only**; never exercised under the harness policies.
* DS's retired `CHOOSE_TIMING_BRANCH` (P17): REF's `RESOLVE_EVENT_FIRST` maps onto DS's `EVENT` mode.

## 6. Deck, deal, and dice alignment

* **Deals**: after both engines complete a turn's deal, DS's hands are overwritten
  with the reference engine's hands via `card_locations` surgery
  (`DSMirror.align_hands`). `set_forced_deal` was NOT used: it caps at 9 cards/side
  and cannot express the reference engine's China-Card +1 hand bonus (see §7), while
  direct location injection aligns hands of any size. Each alignment is logged
  (`deal_align`), and REF's China +1 over-deal is recorded separately
  (`ref_china_hand_bonus`).
* **Dice**: one shared per-game stream (`canon.DiceStream`,
  `random.Random(f"dice:{seed}:{game_id}")`, one `randrange(6)+1` per die). Values
  are cached per **roll index** (the k-th roll of each engine is the same logical
  roll), so both engines see identical dice no matter who reaches roll k first.
  Injection formats:
  * DS: forced dice via `MicroAction(ROLL_DIE, actor_die, opp_die, 0)`; never 0 (= RNG).
    COUP/SPACE_RACE/TRAP_ESCAPE/WAR_EVENT: primary = roller's die. REALIGNMENT:
    primary = actor, secondary = opponent. OLYMPIC_GAMES: primary = sponsor
    (+2 applied by the engine), secondary = participant. SUMMIT: primary = US,
    secondary = USSR. TURN_CLEANUP consumes no die.
  * REF: 1d6 prompts take `str(v)`; 2d6 take the tuple `(USSR, US)` (mapped from the
    DS pair by roll type); Olympic reroll-ties take `(sponsor+2, participant)` — the
    stream redraws ties so both engines see the same final pair (REF's option set
    excludes ties; DS's re-roll loop only runs when not forced).
* **Internal chance draws** (Five Year Plan, Grain Sales to Soviets, Terrorism): DS
  draws internally from its PRNG; REF exposes a chance prompt. The mirror detects
  DS's draw via card-movement inspection and steers REF's prompt to the same card
  (`steer` / `steer_applied` notes). Non-steerable draws (Our Man in Tehran's peek
  order, mid-deal reshuffle ordering) are recorded as divergence causes rather than
  engine defects.
* **Non-dice chance prompts** on the REF side (deck shuffles) are resolved with the
  seeded RNG exactly per the refdriver contract (sorted options + `random.choice`).

## 7. Known, deliberate maskings (recorded, not hidden)

1. **REF's China Card +1 hand bonus** (`game_mechanics.deal`: handsize_target +1 for
   the holder): the mirror aligns hands after each deal and logs the over-deal. The
   rulebook has no such bonus — the holder's hand simply counts the China Card.
   Class R (REF).
2. **Discard timing**: DS relocates a played card out of the hand when the play
   starts (headlines commit to `HEADLINE_COMMITTED`, then to the final pile), REF
   discards after the event resolves. End-of-play states agree; the transient
   hand/removed/discard differences during an event's resolution are why the raw
   scalar-agreement percentage is lower than the legal-set percentage. Assessed
   Class U (no case found where it changes an outcome; nested hand-reads are the
   theoretical exposure).
3. **DS's end-of-turn cleanup step** exposes `action_round = max_ar + 1..2` (the
   counter already advanced past the last round). Cosmetic; the invariant layer's
   bound accounts for it.
