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

Design against **63,5 × 88,9** raw; the four target games share one footprint within
±0,5 mm. Pokémon single-card thickness is not independently documented — treat as
≈0,30 like MTG.

## 2. Sleeves (per layer, µm)

| Brand / line | Type | µm | Source |
|---|---|---|---|
| Dragon Shield Classic | outer | 120 | [vintageisthenewold](https://www.vintageisthenewold.com/faq/what-thickness-are-dragon-shield-sleeves), [SleeveYourGames](https://www.sleeveyourgames.com/guide) |
| Dragon Shield Matte | outer | **130 measured vs 120 in aggregate DBs** ⚠ | [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/dragon-shield-dual-matte-sleeves) vs [SleeveYourGames](https://www.sleeveyourgames.com/guide) |
| Dragon Shield Perfect Fit | inner | 50 (Clear), 60 (Smoke sealable), 100 (Thick) | [Card Kingdom](https://www.cardkingdom.com/mtg-supplies/dragon-shield-perfect-fit-sealable-100-standard-size), [dragonshield.com](https://www.dragonshield.com/products/perfect-fit-thick-inner-sleeves-clear) |
| KMC Perfect Fit | inner | **50 retail spec vs 40 caliper** ⚠ → store 45 ±5 | [Walmart/KMC](https://www.walmart.com/ip/KMC-Sleeves-USA-Pack-Clear-Perfect-Fit-100-Count/599549526), [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/kmc-perfect-size-sleeves) |
| KMC Perfect Hard | inner | 100 | [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/kmc-perfect-hard-inner-sleeve) |
| KMC Hyper Mat | outer | 120 | [kmcsleeves.com](https://www.kmcsleeves.com/products/hyper-mat-100ct-clear) |
| Ultra Pro Eclipse / Pro-Matte | outer | 90 front / 120 back (asymmetric) | [Ultra Pro support](https://support.ultrapro.com/en-US/how-thick-are-the-materials-used-to-make-sleeves-380650) |
| Ultra Pro Pro-Fit | inner | 50 | same |
| Gamegenic Prime / Matte Prime | outer | 100 (66×91) | [gamegenic.com](https://www.gamegenic.com/product/matte-prime-sleeves/) |
| Gamegenic inner | inner | 50 | [Double Sleeved](https://www.doublesleeved.co.uk/blogs/reviews/gamegenic-inner-sleeves) |
| Sleeve Kings | outer | 60 standard / 100 premium | [sleevekings.com](https://sleevekings.com/pages/the-sleeve-kings-difference) |
| Ultimate Guard Supreme / Premium | outer | 115 / 50 | [SleeveYourGames](https://www.sleeveyourgames.com/guide) |

**Per-card pitch** (nominal = card + 2×inner + 2×outer):

| Configuration | Pitch mm | Basis |
|---|---|---|
| Unsleeved | 0,305 | card only |
| Single-sleeved, thin (UP Premium) | 0,41 | derived |
| Single-sleeved, DS Matte | 0,55–0,57 | derived |
| Double-sleeved, KMC PF + Hyper Mat | 0,63 | derived |
| Double-sleeved, DS PF + DS Matte | 0,67 | derived |
| **Design rule, double-sleeved** | **0,70** | measured stacks + air margin |
| **Design rule, single-sleeved** | **0,60** | derived + air margin |

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
