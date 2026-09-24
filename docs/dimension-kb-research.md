# Dimension KB — research base for PRD F4 (sleeves, cards, dice, magnets, fits)

**Researched:** 2026-08-31 · **Feeds:** the M2 "Sleeve / card / dice / game-box KB v1"
task in `docs/ds-mvp-roadmap.md` §4A. Every number names its source; disagreements are
kept, not averaged away. Confidence vocabulary: **spec** (manufacturer), **measured**
(community caliper), **derived** (computed from spec), **folk** (rule of thumb).

**The headline correction:** the folk figure of *0,72–0,80 mm per double-sleeved card*
(and the 72–80 mm stack heights derived from it) is **not supported by any measured
stack**. Two independent caliper measurements put a 100-card double-sleeved Commander
stack at **66–67 mm** ([MTG Salvation thread 572115](https://www.mtgsalvation.com/forums/the-game/commander-edh/572115-dimensions-of-a-double-sleeved-deck):
KMC Hyper Matte + Perfect Fit = 66 mm; Dragon Shield + Perfect Fits = 66,7 mm), and
nominal math agrees (100 × 0,665). The 72–76 mm numbers found in the wild are *internal
box depths designers chose* — stack plus 4–10 mm slack. **Design pitch: 0,70 mm/card
double-sleeved** (measured stack + air margin); footprint envelope **67 × 92 mm**.

## 1. Cards

| Item | Value (mm) | Confidence | Source |
|---|---|---|---|
| MTG card W×H | 63,5 × 88,9 | spec | [Draftsim](https://draftsim.com/mtg-card-size/) |
| MTG thickness (non-foil) | 0,305 | spec | [Draftsim](https://draftsim.com/mtg-card-size/) |
| MTG corner radius | ~3 | spec | same |
| Pokémon | 63 × 88 (some sources 63,5 × 88) ⚠ | spec | [folio.fyi](https://folio.fyi/blog/pokemon-card-dimensions) |
| Lorcana / FaB / One Piece | 63 × 88 (standard TCG footprint) | spec | [Card Fit Lab](https://cardfitlab.com/guides/lorcana-card-size), [CardShellz](https://www.cardshellz.com/blogs/the-bunker/sleeve-size-guide) |
| Yu-Gi-Oh (Japanese size) | 59 × 86 | spec | [CardShellz](https://www.cardshellz.com/blogs/the-bunker/sleeve-size-guide) |

Design against **63,5 × 88,9** raw. Pokémon, Lorcana, FaB and One Piece cards are the
same size or up to about 1 mm smaller: the rows above give 63 × 88, which is 0,5 mm
narrower and 0,9 mm shorter than MTG. A box sized for MTG therefore fits them too, and
that is the design choice: size for the largest card, not an average. (Corrected
2026-09-24: this line used to say the games share one footprint "within ±0,5 mm", which
the 88 vs 88,9 mm heights in the same table contradict.) Pokémon single-card thickness
is not independently documented, so treat it as ≈0,30 like MTG.

## 2. Sleeves (per layer, µm)

| Brand / line | Type | µm | Source |
|---|---|---|---|
| Dragon Shield Classic | outer | 120 | [vintageisthenewold](https://www.vintageisthenewold.com/faq/what-thickness-are-dragon-shield-sleeves), [SleeveYourGames](https://www.sleeveyourgames.com/guide) |
| Dragon Shield Matte | outer | **120 maker spec vs 130 per Double Sleeved** ⚠ | [dragonshield.com](https://www.dragonshield.com/products/clear-matte-sleeves) (Clear Matte, AT-11001) vs [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/dragon-shield-dual-matte-sleeves) (review of 2023-05-19) |
| Dragon Shield Perfect Fit, toploading (Clear, Smoke) and Clear sideloading | inner | 60 | dragonshield.com: [Clear toploading](https://www.dragonshield.com/products/clear-toploading-perfect-fit-sleeves) AT-13001, [Smoke toploading](https://www.dragonshield.com/products/smoke-toploading-perfect-fit-sleeves) AT-13023, [Clear sideloading](https://www.dragonshield.com/products/clear-sideloading-perfect-fit-sleeves) AT-13101 |
| Dragon Shield Perfect Fit, sealable (Clear, Smoke) and Smoke sideloading | inner | **50 maker spec** ⚠ a retailer lists Smoke sealable as 60 | dragonshield.com: [Clear sealable](https://www.dragonshield.com/products/clear-sealable-perfect-fit-sleeves) AT-13201, [Smoke sealable](https://www.dragonshield.com/products/smoke-sealable-perfect-fit-sleeves) AT-13223, [Smoke sideloading](https://www.dragonshield.com/products/smoke-sideloading-perfect-fit-sleeves-standard-size) AT-13123; vs [Card Kingdom](https://www.cardkingdom.com/mtg-supplies/dragon-shield-perfect-fit-sealable-100-standard-size) |
| Dragon Shield Perfect Fit Thick (Clear, Black) | inner | 100 | dragonshield.com: [Clear](https://www.dragonshield.com/products/perfect-fit-thick-inner-sleeves-clear) AT-13004, [Black](https://www.dragonshield.com/products/perfect-fit-thick-inner-sleeves-black) AT-13005 |
| KMC Perfect Fit | inner | **50 maker spec vs 40 per Double Sleeved** ⚠ → store 45 ±5 | [kmcsleeves.com](https://www.kmcsleeves.com/products/perfect-fit), [Walmart/KMC](https://www.walmart.com/ip/KMC-Sleeves-USA-Pack-Clear-Perfect-Fit-100-Count/599549526) vs [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/kmc-perfect-size-sleeves) |
| KMC Perfect Hard | inner | 100 | [kmcsleeves.com](https://www.kmcsleeves.com/products/perfect-hard), [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/kmc-perfect-hard-inner-sleeve) |
| KMC Hyper Mat | outer | 120 | [kmcsleeves.com](https://www.kmcsleeves.com/products/hyper-mat-100ct-clear) |
| Ultra Pro Eclipse / Pro-Matte | outer | 90 front / 120 back (asymmetric) | [Ultra Pro support](https://support.ultrapro.com/en-US/how-thick-are-the-materials-used-to-make-sleeves-380650) |
| Ultra Pro Pro-Fit | inner | 50 | same |
| Gamegenic Prime Board Game Sleeves, Gray (66×91) | outer | 100 | [gamegenic.com](https://www.gamegenic.com/product/prime-board-game-sleeves/) |
| Gamegenic Prime / Matte Prime | outer | **unsourced** | [Prime](https://www.gamegenic.com/product/prime-sleeves/) and [Matte Prime](https://www.gamegenic.com/product/matte-prime-sleeves/) state no thickness |
| Gamegenic inner | inner | 50 | [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/gamegenic-inner-sleeves) |
| Sleeve Kings | outer | 60 standard / 100 premium | [sleevekings.com](https://sleevekings.com/pages/the-sleeve-kings-difference) |
| Ultimate Guard Supreme / Premium | outer | 115 / 50 | [SleeveYourGames](https://www.sleeveyourgames.com/guide) |

**Re-checked against the live pages on 2026-09-24**, when the landing page's deck box
calculator was re-sourced to the makers' own spec pages. What changed, and why:

- **Dragon Shield** states thickness in the "Quality" row of each product page's
  specifications. The earlier Perfect Fit row (50 Clear, 60 Smoke sealable, 100 Thick)
  matched none of them. It had come from Card Kingdom's listing, which still gives the
  sealable line as 60 µm Smoke and 50 µm Clear. Dragon Shield gives 50 µm for both
  sealable colours and 60 µm for the regular Clear toploader. Smoke is 60 µm as a
  toploader but 50 µm as a sideloader, so colour alone does not tell you the thickness.
- **Dragon Shield Matte.** The 130 µm is Double Sleeved's figure. Its review says the
  Matte sleeves measure 130 µm front and back, but does not say what they were measured
  with. The "120 in aggregate DBs" this row used to cite was SleeveYourGames, whose guide
  lists 120 µm for AT-10001, not for the Matte line (AT-11001). The disagreement is
  therefore Dragon Shield's own 120 µm against Double Sleeved's 130 µm.
- **Gamegenic.** The only page that states 100 µm is Prime *Board Game* Sleeves, which
  gives a reinforced thickness of 100 microns and whose Gray size is the 66 × 91
  standard card-game sleeve. The Prime and Matte Prime pages, which this row used to
  cite, give the size (66 × 91, for cards up to 64 × 89), the pack count (100) and the
  material (polypropylene), but no thickness. The board-game figure is not assumed to
  apply to them.
- **KMC Perfect Fit.** The kmcsleeves.com product page gives the thickness as 0,05 mm.
  The 40 µm is Double Sleeved's figure, from their review (2023-08-17) of KMC's
  *Perfect Size* inner, which they say is made from 40-micron plastic. The review does
  not say what it was measured with. Perfect Size is very likely the same sleeve under
  another name, for three reasons:
  - KMC's US store sells no product called Perfect Size.
  - Both are 64 × 89 mm.
  - The review says the sleeve's packaging variants are the same product.

  The review never names Perfect Fit, though, so this stays "very likely", not
  confirmed. Either way the disagreement is small. 10 µm per film is 0,02 mm per card,
  or 2 mm per 100 cards, and both 0,625 and 0,645 mm/card are under the 0,70 design
  pitch.

**Per-card pitch** (nominal = card + 2×inner + 2×outer):

| Configuration | Pitch mm | Basis |
|---|---|---|
| Unsleeved | 0,305 | card only |
| Single-sleeved, thin (UP Premium) | 0,41 | derived |
| Single-sleeved, DS Matte | 0,55–0,57 | derived (120 maker spec to 130 Double Sleeved) |
| Double-sleeved, KMC PF + Hyper Mat | 0,645 at maker spec (50 + 120); 0,625 at Double Sleeved's 40; 0,635 at the stored 45 | derived |
| Double-sleeved, DS PF + DS Matte | 0,645–0,665 at maker spec (50 sealable or 60 toploading + 120); 0,665–0,685 at Double Sleeved's 130 | derived |
| **Design rule, double-sleeved** | **0,70** | measured stacks + air margin |
| **Design rule, single-sleeved** | **0,60** | derived + air margin |
| **Design rule, double-sleeved, thick (100 µm) inners** | **0,80** | derived + air margin; no measured stack |

**What the makers' own figures give.** Using maker spec pages only, inner sleeves are
50–60 µm (Dragon Shield Perfect Fit 50 or 60, KMC Perfect Fit 50, Ultra Pro Pro-Fit 50)
and premium outer sleeves are 90–120 µm (Ultra Pro Eclipse / Pro-Matte 90 front and 120
back, Dragon Shield Matte 120, KMC Hyper Mat 120). A same-brand pair comes to
0,645 mm/card for KMC and 0,645–0,665 mm/card for Dragon Shield. That is about
0,65–0,67 mm per card, or 64,5–66,5 mm for 100 cards. The two measured 100-card stacks
(66 and 66,7 mm) sit at the top of that range and just above it. These are the figures
the landing page's deck box calculator quotes (`ds-landing-page`,
`src/calculator/DeckBoxCalculator.tsx`, "Where the numbers come from").

Two pairs fall outside that range. They are kept here, not dropped:

- An Ultra Pro pair (Pro-Fit inside Eclipse) works out to 0,615 mm/card, because
  Eclipse's front film is 90 µm.
- Dragon Shield's Thick Perfect Fit (100 µm) inside Matte works out to 0,745 mm/card,
  and KMC Perfect Hard (100 µm) inside Hyper Mat gives the same. That is **above the
  0,70 design pitch**: 100 such cards come to 74,5 mm nominal, against the 70 mm that
  `double` allows. A separate sleeving, **`double_thick`, covers these (0,80 mm/card,
  added 2026-09-24)**. Its worst nominal is 0,765 mm/card, with Double Sleeved's
  130 µm Matte. 0,80 keeps the same 3,3 mm per 100 cards of air margin over that
  figure that `double` keeps over its measured stack. It is a separate option, and
  `double` is not raised, because at 0,80 a regular 100-card double-sleeved deck
  (66,7 mm measured) would sit in an 81 mm cavity with about 13 mm of play. No
  thick-inner stack has been measured. The first measured one should replace this
  derivation.

**The air margin is load-bearing — do not tune it out.** Practitioner accounts of insert
design report that freshly sleeved cards trap air, and that the displacement is enough to
stop the last **5–6 cards** of a deck fitting a tray sized to the nominal stack; the remedy
named is "compression room" that lets the air expel over time. Our numbers already provide
it, by arithmetic nobody had written down: 0,70 mm/card sits **3,3 mm** above the measured
66,7 mm stack over 100 cards, and `Process.stack_slack_mm` adds **1,0 mm** — together
≈4,3 mm, or about six cards. That is compliance by coincidence of two independently chosen
values, so it is recorded here: **anyone tightening either number is removing the air
margin, and the symptom appears only after a deck is sleeved.** Audited 2026-09-05 (roadmap
§0.5) against a practitioner source; the 5–6 card figure is that source's, uncited, and is
corroboration rather than a measurement of ours.

## 3. Sleeved footprint and box clearances

| Item | Value (mm) | Source |
|---|---|---|
| DS / UP Eclipse / Gamegenic outer, outside | 66 × 91 | [Amazon DS](https://www.amazon.com/Dragon-Shield-Protective-Standard-Gathering/dp/B01HLQLXCY), [Gamegenic](https://www.gamegenic.com/product/prime-board-game-sleeves/) |
| KMC Perfect Fit outside | 64 × 89 | [Ventura Games](https://venturacardgames.com/products/kmc-perfect-size-card-sleeves-standard-64x89mm-100ct-ultra-clear) |
| Double-sleeved measured width | 67 | [MTG Salvation 572115](https://www.mtgsalvation.com/forums/the-game/commander-edh/572115-dimensions-of-a-double-sleeved-deck) |
| Ultimate Guard Boulder 100+ internal (commercial ref) | ≈68,5 × 67,5 × 93 | [Ultimate Guard](https://ultimateguard.com/en/Card-Cases/Boulder-100-Solid-Black/UGD-011422-006-00/) |
| Printables 245516 Commander box internal ⚠ unverified (Cloudflare-gated; from search snippets) | 71 × 76 × 97 | [printables.com/model/245516](https://www.printables.com/model/245516-commander-deck-box-magic-the-gathering) |
| DeckSmith commander box internal | 76 × 68 × 98 | [decksmith.shop](https://www.decksmith.shop/en/commander-deck-box) |

**Working convention:** +1,5–2 mm over the sleeve envelope for a snug commercial-style
fit; +4–6 mm for easy-in/out printed boxes. **In the code** (issue #71) this is
`Process.fit_intent`, `snug` | `easy`, and `FIT_INTENT_CLEARANCE_MM` in
`pythonsrc/organizer/spec.py` is the only place either number lives — the low end of
each band, 1,5 and 4,0 mm. Both are total per axis, not per side.

## 4. Dice

| Item | Value | Source |
|---|---|---|
| Standard d6 | 16 mm face-to-face (variants 12, 10, 19) | [Dice Game Depot](https://www.dicegamedepot.com/dice-sizes/) |
| d20 | ~20–22 mm (22 typical) | [Victory Dice](https://www.victorydice.com/blogs/dnd-dice-guides/how-big-are-d-d-dice) |
| Pocket rule | wells for d20/d12 sized vertex-to-vertex: +10–15 % over face-to-face | derived from [Dice Game Depot](https://www.dicegamedepot.com/dice-sizes/) |

**What is missing, and why the token tray ships with no presets** (issue #84,
2026-09-13). The table above sources die *sizes*. It does not source:

- **a punchboard token footprint** — the commonest thing a tray holds. No standard
  exists; publishers cut tokens to whatever the sheet allows, and community
  measurements are per-game the way box internals are (§7);
- **a d6 pocket clearance.** The +10–15 % rule above is explicitly for d20 and d12,
  where the well has to take the *vertex-to-vertex* dimension of a shape that does not
  sit flat. It says nothing about how much room a 16 mm d6 wants in a 16 mm-nominal
  square pocket, and a die in a pocket its own size is not in a pocket.

A `token_tray` preset would therefore be one sourced number plus one invented one, which
is the failure `dimensions.py` avoids by carrying no token sizes at all. So `Pocket` in
`pythonsrc/organizer/spec.py` takes explicit millimetres and a free-text `source`, the
view prints that provenance (or says "user-given mm" when there is none), and presets
join when this file can source both halves — the M2 KB.

## 5. What existing parametric generators default to (prior art for our tolerances)

| Generator | Parameter | Default | Source |
|---|---|---|---|
| Boardgame Insert Toolkit v4 | `$g_tolerance` | **0,1** | [lib source](https://github.com/dppdppd/The-Boardgame-Insert-Toolkit/blob/master/release/lib/boardgame_insert_toolkit_lib.4.12.0.scad) (verified by grep, line ~406) |
| BIT README | insert-to-box margin | 3 mm depth/length, 2 mm height | [BIT README](https://github.com/dppdppd/The-Boardgame-Insert-Toolkit) |
| pinkfish boardgame toolkit | `m_piece_wiggle_room` | **0,2** | [base_bgtk.scad:37](https://github.com/pinkfish/openscad_boardgame_toolkit/blob/main/base_bgtk.scad) — also ships `card_library.scad` with a `MakeCardSize(w, l, single_card_thickness, sleeve_wall_thickness)` signature, the same schema shape F4 needs |
| The Card Case (MakerWorld) | lid fit | exposed `Lid slide gap` / `Lid side gap` / `Lid top gap`; presets for DS Matte, 60/100 single/double | [makerworld 1960991](https://makerworld.com/en/models/1960991-the-card-case-the-ultimate-parametric-deck-box) — comments confirm lid tightness is the #1 field issue |
| Commander Case (same author) | magnet pockets | 10×5×2 block → pocket 10,2 × 5,2 × 2,15 (+0,2/+0,2/+0,15, glue-in) | [makerworld 1949365](https://makerworld.com/en/models/1949365-commander-case-parametric-mtg-commander-deckbox) |
| Maker convention | 6×3 disc magnet | press-fit ⌀6,0–6,1 × 3,0; glue-in ⌀6,2–6,4 × 3,1; ≥1,5–2 mm wall around/behind; N35+, N48–N52 for slide lids | [Meshra](https://meshra.ai/blog/magnet-pockets-3d-printing) |
| Deck-box lid friction lip | 0,2–0,4 mm engagement | [GreatLight guide](https://metal-3dprinting.com/3d-printed-deck-box-guide/) |

## 6. FDM tolerance reality (what the fit-tolerance profile fields must absorb)

| Item | Value | Source |
|---|---|---|
| Desktop FDM dimensional accuracy | ±0,5 % (floor ±0,5 mm) | [Hubs knowledge base](https://www.hubs.com/knowledge-base/dimensional-accuracy-3d-printed-parts/) |
| Industrial FDM | ±0,15 % (floor ±0,2 mm) | same |
| Bambu-class, tuned + shrink-compensated | ±0,1 mm typical; ±0,2 mm uncalibrated; 0,3 mm errors observed | [Bambu forum](https://forum.bambulab.com/t/dimensional-accuracy-calibration/112292) |
| Sliding fit | 0,2–0,3 mm per side (some guides 0,3–0,4 total ⚠) | [Sovol](https://www.sovol3d.com/blogs/news/fdm-3d-printing-tolerances-clearances-how-to-design-parts-that-fit), [3dprintcalcs](https://3dprintcalcs.uk/reference/common-tolerances/) |
| Press fit | 0–0,1 mm total clearance; >0,3 mm interference cracks walls; 0,5 mm chamfer lead-in | same |

**Consequence for the PRD:** geometry can be exact to the micron and the *printed part*
still lands within ±0,1–0,2 mm of it. The fit guarantee is therefore geometry-exactness
**plus** per-printer/material offsets calibrated from printed test coupons — not a
printer-accuracy assumption. This is what `ProcessProfile`'s fit-tolerance fields and
the coupon → calibration loop exist to absorb.

## 7. Game-box internal dimensions — no public DB exists

- **BGG XML API2 carries *external* dims only**, inches, user-entered, patchy:
  `thing?id={id}&versions=1` → per-version `<width>/<length>/<depth>` ([BGG thread](https://boardgamegeek.com/thread/2347448/bgg-api-to-get-size-of-a-box)). Direct
  curl returns empty without a UA header; the API queues requests.
- Internal dims live in per-game community measurements (e.g. Wingspan internal
  286 × 286 × 72, [BGG thread](https://boardgamegeek.com/thread/2491522/wingspan-base-game-box-dimensions)); boxes flare and vary ±1–2 mm between copies.
- **KB consequence:** ship internal dims as *user input with a −2 mm safety default*
  (exactly BIT's leave-3/3/2 rule); curate popular games one at a time. This curation
  is moat work, not a scrape.

**Shipped 2026-09-21 (issue #154):** `pythonsrc/data/game_boxes.v1.json`, read by
`pythonsrc/organizer/box_kb.py`, with **three** entries — the Wingspan row above, and the
Ultimate Guard Boulder 100+ and DeckSmith rows of §3. Provenance is per *value* (basis,
source, capture date, units, one set per axis) and a value with no source is refused at
load. The −2 mm default is unchanged and applies to a curated interior exactly as to a
typed one: a curated number is still one copy of one box, and this section is why. See
§9 for what was refused, and `docs/SYSTEM-AS-BUILT.md` § Game-box dimension KB for the
reasoning.

## 8. KB seed schema (v1)

```jsonc
// pythonsrc/data/dimension_kb.v1.json — mm; µm for film layers.
{
  "schema": {
    "id": "string",
    "kind": "card | sleeve_inner | sleeve_outer | stack_rule | dice | magnet | fit | box_internal",
    "brand": "string?", "game": "string?",
    "w_mm": "number?", "h_mm": "number?",
    "t_um_per_layer": "number?",
    "card_t_mm": "number?",
    "pitch_mm_per_card": "number?",
    "pocket": {"w_mm": 0, "h_mm": 0, "d_mm": 0},
    "clearance_mm": "number?",
    "confidence": "spec|measured|derived|folk",
    "sources": ["url"], "notes": "string?"
  }
}
```

Seed entries (cards ×3, inners ×3, outers ×5, stack rules ×2, dice ×2, magnets ×2,
fits ×3) are in the tables above with per-row sources; transcribe them when
`pythonsrc/data/` gains the file (M2 task). The two genuine disputes — DS Matte 120 vs
130 µm, KMC PF 40 vs 50 µm — are absorbed by the 0,70 mm/card design pitch, which two
independent caliper measurements support. Re-verify the Printables row manually before
shipping it (Cloudflare-gated at research time).

## 9. What shipped as the game-box KB, and what was refused (2026-09-21, issue #154)

The launch set is **three entries**, because three is what this document can source.
"Small and defensible beats broad and unsourced" is the issue's own instruction, and the
alternative — a wider set with a wall thickness guessed for half of it — is exactly the
fabricated number `dimensions.py` carries no token sizes to avoid.

| Entry id | What it is | Interior W × D × H (mm) | Basis | From |
|---|---|---|---|---|
| `wingspan` | Wingspan base game box | 286 × 286 × 72 | measured | §7's BGG thread 2491522 |
| `ultimate-guard-boulder-100-plus` | Boulder 100+ card case | 68,5 × 67,5 × 93 | spec | §3's Ultimate Guard listing |
| `decksmith-commander-box` | DeckSmith Commander box | 76 × 68 × 98 | spec | §3's DeckSmith listing |

Width is the stack direction on both card cases, which is why their depth and height sit
0,5–6 mm over the 67 × 92 mm double-sleeved envelope of §3 — the two figures corroborate
each other, and a transcription error on either would show up as a card case narrower
than the cards it holds.

**Refused, with the reason, so they are not rediscovered as omissions:**

- **Printables 245516** (internal 71 × 76 × 97, §3). The row is marked ⚠ unverified — it
  came from search snippets because the page is Cloudflare-gated — and §8 says re-verify
  it manually before shipping. Nobody has. It joins when somebody opens the page.
- **Every BGG box-dimension row.** External only, user-entered, in inches, and behind a
  registration-gated commercial API licence (§7, and issue #154's §0.4). **There is no BGG
  client in the repository and there must not be one**; `tests/test_game_box_kb.py`
  asserts that against the whole tree. A BGG *forum thread* in which a person reports
  measuring their own copy is a citation like any other, and the Wingspan row is one.
- **Anything that would need a wall thickness guessed.** Deriving an interior from an
  exterior is supported by the schema — `basis: "derived"` plus a `note` naming the
  subtraction, which the loader requires — and no entry does it, because no source in
  this repository states the wall.

**The confidence vocabulary in §0 is the schema's**, minus one: `spec`, `measured` and
`derived` are accepted bases and **`folk` is not**. A rule of thumb about box walls is not
a measurement of a box, and an insert compiled against one is the named catastrophic
failure of the audited document (roadmap §0.5) — it presses outward, splits the cardboard
at the corners and lifts the lid.
