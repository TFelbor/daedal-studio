# Organizer spec schema + first archetype (deck box) through Phases 3–5

**Date:** 2026-09-03
**Status:** approved, ready for implementation
**Scope:** roadmap §0.3 Phase 1 tick-boxes 2 and 3 — "Spec schema" and "First archetype:
deck box, spec → mesh → Phases 3–5 via the `--skip… --mesh --no-scale` seam"
**Not in scope:** the repair-assertion path and `size_source="spec"` (tick-box 4), the
dimensional-CI sweep across the parameter envelope (tick-box 5), LLM extraction (M2),
the dimension KB (M2), any server or UI change.

## Problem

The pivot's governing rule is *the LLM interprets words; it never produces geometry*.
Nothing in the tree yet occupies the boundary that rule describes: there is no object
that says what an organizer *is* in numbers, and no code that turns such an object into
a mesh. Everything the PRD lists as Must — extraction (F2), the template engine (F5),
prompt iteration as a spec diff (F8), saved designs as specs (F11), the test-fit coupon
(F12), the annotated preview (F7) — is a function of that object. The UI already
declares the shape it expects (`web/src/organizer/spec.ts`) and renders an explicit
empty state until a producer exists.

The seam the geometry must enter through already exists and is already correct:
`--skip-visualizer --skip-sculptor --mesh box.stl --no-scale` hands Phase 3 a mesh
whose dimensions are final (PR #40). What is missing is the thing to put in front of it.

## Decisions

1. **Kernel: `manifold3d`.** Recorded in `ARCHITECTURE.md` and PRD §9.1. Every v1
   archetype is axis-aligned box CSG. Verified in the venv on 2026-09-03: a two-part
   lip-lid deck box compiles watertight, passes `Engineer.process(target_mm=None)`
   with zero faces dropped and every plane where it was designed, and exports a
   byte-identical STL on repeat.
2. **text-to-cad is a build-time authoring aid, not a runtime component, and not the
   kernel.** It drives build123d on OCCT; `cadgen` needs Python ≥ 3.11 and the images
   are 3.10. What is borrowed is the shape of its `measure`/`align` checkers: designed
   features are read back off the mesh and compared, never assumed.
3. **Schema: stdlib dataclasses, no pydantic.** pydantic is not in the pipeline image,
   and the roadmap asks for the `telemetry/schema.py` pattern. JSON Schema for M2's
   structured outputs is a server-layer concern later.
4. **No LLM call anywhere.** M0 validates the geometry engine with a hand-written spec,
   "without LLM noise in the loop".
5. **A spec run is a real run.** Its outputs land in `data/outputs/{job_id}`, never
   `dev-`; nothing in it is a fixture. It gets no invented blueprint.

## Package layout

```
pythonsrc/organizer/
  __init__.py            public surface: OrganizerSpec, load_spec, compile_spec, SpecError
  spec.py                schema, validation, JSON, canonical form, hash, diff, UI view
  dimensions.py          M0 seed constants with KB sources (replaced by the KB in M2)
  compiler.py            compile_spec() → CompileResult; archetype registry
  archetypes/
    __init__.py
    deck_box.py          v1: spec → parts → plate mesh, features, measure()
  __main__.py            `python -m pythonsrc.organizer compile|example|measure`
```

Imports inside the package are relative. `pipeline.py` imports it the way it imports
`printability`: `from organizer import …` with a `pythonsrc.organizer` fallback.

## Schema (`spec.py`)

All dataclasses are `frozen=True`. Every millimetre float is rounded to **1 µm** in
`__post_init__` (via `object.__setattr__`), so `from_dict(to_dict(s)) == s` holds
exactly and the canonical form does not carry float noise. Resolution is three orders
of magnitude below N1's ±0,05 mm.

| Class | Fields (defaults) | Validation |
|---|---|---|
| `CardStack` | `count: int`, `card: str = "standard"`, `sleeving: str = "double"` | `count ≥ 1`; `card ∈ CARD_KINDS`; `sleeving ∈ {none, single, double}` |
| `Compartment` | `contents: CardStack` | — |
| `Lid` | `kind: str = "lift_off"`, `magnets: bool = False`, `height_mm = 15.0`, `wall_mm = 1.2`, `clearance_mm = 0.2`, `top_mm = 2.0` | `kind ∈ {lift_off}`; all mm `> 0` |
| `Constraints` | `max_external_mm: tuple[float, float, float] \| None = None` | each `> 0` when present |
| `Process` | `wall_mm = 2.8`, `floor_mm = 2.0`, `cavity_clearance_mm = 1.5`, `stack_slack_mm = 1.0`, `min_feature_mm = 1.0` | all `> 0` except clearances `≥ 0` |
| `OrganizerSpec` | `archetype: str`, `compartments: tuple[Compartment, …]`, `lid: Lid \| None`, `constraints: Constraints`, `process: Process`, `schema_version: int = 1` | `archetype ∈ ARCHETYPES`; `≥ 1` compartment; `schema_version == 1` |

Field-level rules run in each `__post_init__`; cross-field rules that belong to a
shape (a lip too thin, a second compartment, magnets) run in the **archetype**, because
they are facts about deck boxes, not about specs. Both raise `SpecError(ValueError)`,
whose message lists every problem with its dotted field path, so a bad spec is refused
once with the whole list rather than one field per attempt.

Functions:

- `to_dict()` / `from_dict()` / `to_json()` / `from_json()` — the telemetry pattern.
  `from_dict` rejects unknown keys (a typo in a field name must not silently become
  the default).
- `canonical_json(spec)` — `sort_keys=True`, compact separators, `ensure_ascii=False`.
- `spec_hash(spec)` — sha256 hex of the canonical JSON. This is the `hash` the UI's
  `OrganizerSpec` carries and the value a future gate approval binds to.
- `spec_diff(a, b)` — `{dotted.path: (old, new)}` over the flattened canonical dicts.
  Added and removed paths appear with `None` on the missing side. This is F8's
  "make the lid deeper → spec diff → regenerate" made mechanical.
- `load_spec(path)` — reads and validates a JSON file.

## Seed dimensions (`dimensions.py`)

Constants with their `docs/dimension-kb-research.md` sources in comments, so every
resolved number in a spec can be traced:

| Constant | Value | Basis |
|---|---|---|
| `CARD_KINDS["standard"]` | 63,5 × 88,9 mm | MTG spec; four target games within ±0,5 mm |
| sleeved footprint `none` | card footprint | — |
| sleeved footprint `single` | 66 × 91 mm | DS / UP / Gamegenic outer |
| sleeved footprint `double` | 67 × 92 mm | measured double-sleeved width; outer height |
| pitch `none` | 0,305 mm/card | card thickness |
| pitch `single` | 0,60 mm/card | design rule (derived + air) |
| pitch `double` | 0,70 mm/card | design rule (two measured 100-stacks at 66–67 mm) |

`CARD_KINDS` is `{"standard"}` in v1. The KB research also lists the Japanese size
(59 × 86 mm) but no sourced sleeve envelope for it, and a footprint invented to fill the
gap is exactly the fabricated number this schema exists to refuse; it arrives with the
M2 KB. `card` stays a field so the JSON does not change shape when it does.

`resolve_stack(stack) → ResolvedStack(footprint_w, footprint_h, pitch, basis: str)`.
The `basis` string is what the UI's `fits.basis` shows: *"standard card 63,5 × 88,9 mm,
double-sleeved envelope 67 × 92 mm; 0,70 mm/card design pitch (measured stacks)"*.

## Deck box archetype (`archetypes/deck_box.py`, `ARCHETYPE_VERSION = "1"`)

Two parts on one plate, both flat on Z = 0, no overhangs anywhere:

- **Body** — open-top box with a floor. Its top `lid.height_mm` is a **lip**: the outer
  wall steps in by `lid.wall_mm + lid.clearance_mm` per side so the lid sits flush.
- **Lid** — an inverted tray, printed open side up, placed `PLATE_GAP_MM = 10` to the
  +X of the body.

Cards stand upright: width along X, stack along Y, height along Z. With
`n, pitch, (fw, fh)` from `resolve_stack`, `w, f, cc, ss` from `process`,
`lh, lw, lc, lt` from `lid`:

```
cavity_w   = fw + cc            cavity_d   = n·pitch + ss        cavity_h = fh + cc
external_w = cavity_w + 2w      external_d = cavity_d + 2w       body_h   = cavity_h + f
lip_inset  = lw + lc            lip_wall   = w − lip_inset
lip_outer_w = external_w − 2·lip_inset                lip_outer_d = external_d − 2·lip_inset
lid_cavity_w = external_w − 2·lw (= lip_outer_w + 2·lc)   lid_cavity_d likewise
lid_h = lh + lt                 external_h (assembled) = body_h + lt
```

CSG, all `Manifold.cube(..., center=False)` and translations:

```
body = cube(W, D, body_h) − cube(cavity).translate(w, w, f)
     − [cube(W, D, lh+1).translate(0, 0, body_h − lh) − cube(lip_outer).translate(lip_inset, lip_inset, body_h − lh − 1)]
lid  = cube(W, D, lid_h) − cube(lid_cavity_w, lid_cavity_d, lh + 1).translate(lw, lw, lt)
plate = body + lid.translate(W + PLATE_GAP_MM, 0, 0)
```

Archetype-level validation (raises `SpecError`): exactly one compartment; `lid`
present and `kind == "lift_off"`; `magnets is False` (*"deck_box v1 has no magnet
pockets; a magnetic lid is a later archetype variant"*); `lip_wall ≥ process.min_feature_mm`
with the remedy named (thicker body wall, thinner lid wall, or smaller clearance);
`lid.height_mm < cavity_h`.

`compile(spec) → CompileResult`:

- `mesh: trimesh.Trimesh` — the plate, `process=False` so the kernel's vertices are
  exported untouched.
- `parts: dict[str, trimesh.Trimesh]` — `{"body": …, "lid": …}` in plate position.
- `features: dict[str, float]` — every designed dimension above, plus `stack_height_mm`
  `= n·pitch`, `lid_clearance_mm`, `floor_mm`, `wall_mm`.
- `archetype`, `archetype_version`, `spec_hash`.

`measure(mesh) → dict[str, float]` — reads the same features back from the mesh's
axis-aligned coordinate planes: split into bodies, identify body (larger volume) and
lid, take the sorted unique X/Y/Z plane sets (rounded to 0,1 µm), and read the
differences. A plane set with the wrong count raises `MeasureError`: geometry that does
not have the planes the design says it has is itself the finding. This works on the
compiled mesh **and on Phase 3's output**, which is what makes the dimensional
assertion honest — it measures what the slicer receives.

`fits_check(spec, features) → FitsResult(fits, line, basis, remedy)` mirrors the TS
type. `line` is the arithmetic (*"100 × 0,70 mm = 70,0 mm stack · internal 71,0 mm ·
external 75,3 × 76,6 × 97,4 mm"*). Without constraints `fits` is true by construction
(the cavity is derived from the stack) and the sum is still shown — that sum *is* the
value. With `max_external_mm`, each axis is compared and the remedy names the axis, the
overshoot and the card count that would fit.

`to_view(spec, result) → dict` produces exactly `web/src/organizer/spec.ts`'s
`OrganizerSpec`: `archetype`, `archetypeVersion`, `hash`, `dimensions[]` (`key`,
`label`, `value`, `unit`, `editable`, `note`) and `fits`. Editable rows: card count,
wall, floor, cavity clearance, stack slack, lid clearance, lid engagement. Derived
rows: pitch (note = basis), stack height, internal W/D/H, external W/D/H. Not wired to
the server in this change; it exists so the wiring is one field.

## Pipeline entry (`pipeline.py --spec PATH`)

`_apply_spec_mode(args, parser)` runs after `parse_args`, is a plain function so tests
can call it with a `Namespace`:

- `--spec` **implies** `skip_visualizer`, `skip_sculptor`, `no_scale`. Logged.
- `--spec` **refuses** `--mesh` (two sources of geometry) and `--hollow` (already
  refused with `--no-scale`; refused earlier here with the reason). `parser.error`.
- A prompt is not required (Phase 1 does not run).

In `run()`:

- `raw_mesh_path = outputs_dir / "compiled_mesh.stl"` when `args.spec`.
- `_will_use_reference_assets` returns **False** when `args.spec` is set — a spec run
  compiles its own geometry and substitutes nothing — so `_job_outputs_dir` picks the
  plain namespace. `_should_install_reference_blueprint` returns False likewise, and
  the "no blueprint" warning becomes an INFO line saying Phase 1 does not apply to a
  compiled spec (an unexplained empty first stage reads as a broken pipeline).
- Phase 2 becomes a three-way branch: `if args.spec: <compile>` /
  `elif not args.skip_sculptor: <sculpt>` / `else: <reference mesh if missing>`.
- The compile runs inside the **real** `_phase_start(2)` / `_phase_pass(2)` /
  `_phase_fail(2)` emitters, so the banner contract is untouched and the UI's
  "Compiler" phase moves truthfully. A `SpecError` is a Phase 2 failure with the
  message.
- Written into the job directory: `compiled_mesh.stl`, `spec.json` (canonical form),
  `compile_features.json` (designed features + `parts` + archetype + version + hash).
- `_record_generation(model=f"organizer/{archetype}", model_version=ARCHETYPE_VERSION,
  backend="local", params={schema_version, archetype, archetype_version, spec_sha256,
  parts, features}, cost_eur=None, duration_s=compile_seconds)`. No new column: which
  engine made the mesh is exactly what `generation_model` records, and "local" is the
  truthful backend. `blueprint_*` stay NULL, which is correct — no image existed.
- `--stop-after-phase 2` works unchanged (raw mesh at `compiled_mesh.stl`).
- The printability call passes `expected_components=len(result.parts)`.

## Gate change (`printability.py`)

`evaluate_printability(…, expected_components: int | None = None)` and
`evaluate_mesh_file(…)` gain the parameter. In the `floating_components` check, when
`floating == 0 and components > 1 and components == expected_components`, the status is
`pass` with *"N separate parts as designed, all resting on the plate"*, and `value`
carries `expected`. Every other path is unchanged; a mismatch still warns. Rationale:
the probe scored 88,1 "risky" solely because two intended parts read as a possible
unintended split, and a risk badge on every deck box is the mirror image of the fits
badge with no measurement behind it. The `min_wall_thickness` warn is left alone: its
pitch grows with plate width and its stated tolerance is honest.

## Telemetry

No schema change, no `STAGES` change. `generation_*` columns carry the compiler's
provenance as above. `size_source` is not written as `"spec"` here — that is tick-box 4
and needs the request model.

## Tests

`tests/test_organizer_spec.py`
- round-trip `from_dict(to_dict(s)) == s`, `from_json(to_json(s)) == s`
- canonical JSON identical for two dicts with different key order
- `spec_hash` changes when any field changes; stable across processes (fixed vector)
- `spec_diff` reports a changed path, an added path and a removed path
- every validation rule refuses with the field path in the message; several errors are
  reported together
- unknown key in `from_dict` refused
- µm rounding: `2.80000004` stores as `2.8`
- `to_view` has the TS shape: keys, `editable` flags, `fits` line contains the sum

`tests/test_deck_box.py`
- parametrised over counts {40, 60, 100} × sleeving {none, single, double}: watertight, exactly two bodies, both on Z = 0, every designed
  feature measured within **0,05 mm** on the compiled mesh
- byte-identical STL on a second export of the same spec
- lid cavity minus lip outer equals `2·clearance` (the tolerance surface)
- magnets / second compartment / thin lip / tall lip refused with named reasons
- through `Engineer.process(target_mm=None)`: every feature still within 0,05 mm,
  `scale_applied` False, `faces_dropped` 0
- `evaluate_printability(expected_components=2)`: no `fail`, `floating_components` pass
- `fits_check` with a constraint that fails names the axis and a card count

`tests/test_pipeline_spec.py`
- `_apply_spec_mode`: implies the three flags; refuses `--mesh` and `--hollow`
- `_will_use_reference_assets` and `_should_install_reference_blueprint` return False
  with `spec` set even when nothing else exists
- `_job_outputs_dir` picks the plain directory for a spec run
- the compile step (extracted as `_compile_spec_phase(args, outputs_dir)`) writes the
  three files and returns the mesh path; a bad spec raises `SpecError`

`tests/test_printability.py`
- two grounded parts with `expected_components=2` pass; with `None` still warn; with
  `expected_components=3` still warn

Existing suites that must stay green: `test_phase_banners.py`, `test_pipeline_blueprint.py`,
`test_engineer_no_scale.py`, `test_module_integrity.py`, `test_licensing_guards.py`,
`test_licence_data.py`, `test_telemetry_trace.py`.

## Docs

- `CLAUDE.md`: new **Organizer — the parametric path** section (schema, seam, `--spec`,
  banners, what is recorded, what is deliberately not); the top note that the engine
  "does not exist yet" updated to say what exists after M0.
- `ARCHITECTURE.md`: a **Phase 2 — Compiler (parametric path)** entry beside the
  sculptor: kernel, version, no weights, no licence delta.
- `docs/ds-mvp-roadmap.md` §0.3 and the README mirror: tick boxes 2 and 3.
- `web/src/pipeline.ts` header comment: `pythonsrc/organizer/` exists; the server does
  not carry the spec yet, so `NO_SPEC_REASON` stays true.

## Verification

1. `pytest tests/` green, `test_licensing_guards.py` named separately.
2. `python -m pythonsrc.organizer example deck_box > /tmp/spec.json` then
   `python pythonsrc/pipeline.py --spec … --stop-after-phase 3` natively: Phase 3 runs,
   `compile_features.json` and the measured Phase 3 output agree within 0,05 mm.
3. With Docker up: `docker compose -f infra/docker-compose.yml run --rm pipeline-runner
   python pythonsrc/pipeline.py --spec /app/data/inputs/deck_box.spec.json --slice`
   through Phase 4, then with `--print --start-print` against the OctoPrint simulator
   for Phase 5. Report which phases actually ran.

## Out of scope, and why

- **Server / `POST /jobs` with a spec, `GET /jobs/{id}.spec`** — the tick-box is the CLI
  seam; wiring the request model is where `size_source="spec"` belongs (tick-box 4).
- **Repair-assertion path** — Phase 3 still repairs before it asserts nothing; the
  archetype tests measure Phase 3's output instead, which is the assertion the next
  tick-box will move into the pipeline.
- **Envelope sweep CI** — the parametrised archetype tests are its seed, not the sweep.
- **Slide, hinged, magnetic lids; token tray; dividers; coupon** — M1/M3.
- **Dimension KB** — `dimensions.py` is a seed the M2 KB replaces.
