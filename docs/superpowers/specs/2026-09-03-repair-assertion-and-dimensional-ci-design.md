# Repair-assertion path and dimensional-accuracy CI — design

**Date:** 2026-09-03 · **Scope:** roadmap §0.3 Phase 1, tick-boxes 4 and 5 · **Follows:**
`2026-09-03-organizer-spec-and-deck-box-design.md`, which built the spec, the deck box and
the `--spec` seam and left these two out.

**Not in scope:** the envelope sweep across *every* archetype (M1, there is one archetype),
`GET /jobs/{id}` carrying the spec back to the UI (`specFromJob` stays the seam), the
dimension KB, LLM extraction.

## The problem

Phase 3 treats every mesh as a reconstruction. `Engineer.process` runs `repair_mesh`
unconditionally: trimesh closes the surface, `manifold3d` validates it, and when the
kernel refuses, the surface is rebuilt volumetrically at a pitch that discards detail. For
a mesh reconstructed from an image that is the right service. For a mesh **compiled from a
spec** it is wrong in both directions:

- A compiled mesh that is *not* watertight is a compiler bug. Repairing it hides the bug
  and — through the voxel escalation — ships a part whose dimensions are no longer the
  spec's, with `scale_applied: false` in the report saying the dimensions were honoured.
- A compiled mesh that *is* watertight gains nothing from repair and passes through a
  float32 round trip for no reason.

The scaling half of this (N1) landed in PR #40: `--no-scale`. This is the repair half.
`tests/test_deck_box.py` already measures Phase 3's output against the spec, but only in
the test suite — the pipeline itself asserts nothing after Phase 3, so a spec run whose
geometry drifted would slice and print without a word.

And `size_source` cannot yet say `"spec"`: the request model has no spec field, so a spec
job's row reads `size_source="default"` — a claim that the 50 mm default applied to a part
whose every dimension the spec fixed.

## Design

### 1. `Engineer.process(repair_mode="assert")`

`repair_mode` is `"repair"` (default, every existing caller unchanged) or `"assert"`.
In assert mode `process` does not repair. It runs `Engineer.assert_manifold(mesh)`, which
checks what `repair_mesh` would otherwise fix — watertight, zero boundary edges, zero
non-manifold edges, consistent winding with positive volume, and acceptance by the
`manifold3d` kernel — and raises **`MeshAssertionError`** naming every failing finding.
Nothing is exported on failure. On success the mesh is oriented (translation only, as
before), never scaled, and exported.

`repair_mode="assert"` **requires `target_mm=None`**. Asserting that a mesh is exactly what
was authored and then resizing it is a contradiction, and refusing it here keeps
"assert" meaning one thing. `hollow` is already refused with `target_mm=None`.

`last_report["repair_method"]` is `"asserted"` — a fourth value beside `manifold`,
`trimesh_fallback` and `voxel_remesh`, so "which repair path ran" stays one query — and
`last_report["assertion"]` carries the findings (edge counts, kernel status, component
count) so a row can show *what* was asserted, not only that something was.

### 2. The pipeline asserts dimensions after Phase 3

For a spec run (`args.spec`), Phase 3 calls `process(..., repair_mode="assert")`, then
`_assert_spec_dimensions()`: reload the spec Phase 2 recorded (`spec.json` in the job
directory — what was recorded, not what was passed), measure the engineered mesh with the
archetype's own `measure()`, compare every feature in `MEASURED_FEATURES` against the
compiled features at `DEFAULT_TOLERANCE_MM` (0,05 mm, PRD N1), and:

- write `dimension_report.json` beside the mesh — **before** deciding pass or fail, so a
  failure is inspectable;
- print one `[DS] Dimensions: N/N features within ±0.05 mm (max error …)` line, and one
  `✗` line per feature out of tolerance;
- put the report under `last_report["dimension_check"]`, which `_record_mesh_lineage`
  already persists as `repair_report` — the `achieved_extent_mm` precedent: measured on
  the exported mesh, stored on the row, no new column;
- raise `MeasureError` when anything is missing or out of tolerance, which `_phase_fail(3)`
  turns into a failed Phase 3. A plane count that does not match the design (the
  archetype's `MeasureError`) fails the same way.

`compiler.check_dimensions()` returns a `DimensionReport` (tolerance, per-feature
designed/measured/error, missing, out-of-tolerance, max absolute error); the existing
`assert_features_within` becomes a thin wrapper over it. `archetypes.verify_spec_mesh()`
is the one-call form the pipeline, the CLI (`measure --report PATH`) and the tests share.

### 3. `size_source="spec"` through the request model

`JobRequest.spec: Optional[dict]`. Validated **on the model** with
`OrganizerSpec.from_dict` — `pythonsrc.organizer` is stdlib-only precisely so the
api-server image (no trimesh, no manifold3d) can import it — and a `SpecError`'s problem
list becomes the 422 detail. A spec with `target_mm`, `scale_axis` or `size_source` in the
same request is refused: the spec decides the size, and two deciders is the disagreement
`size_source` exists to prevent.

`POST /jobs` with a spec writes it canonically to `data/inputs/{job_id}/spec.json`, sets
`request.spec_path` to the container path (the `blueprint_path` precedent), records
`size_source="spec"` with `requested_size_mm` and `requested_scale_axis` NULL, and
`_pipeline_args` forwards `--spec`. A spec request implies `skip_viz` and `skip_sculpt` in
`_run_pipeline` — so no native Phase 1 runs and the blueprint gate does not arm — and
**does not** forward `--skip-visualizer --blueprint <shared path>`: a spec run has no
image, and handing it the shared blueprint would snapshot whichever job's render sits
there and stamp its hash as this job's Phase 1 provenance. `_apply_spec_mode` drops a
`--blueprint` it is given for the same reason, with a warning, because the mps_native
strategy used to hardcode one.

`VALID_SIZE_SOURCES` gains `"spec"`. The `created` stage stays the only writer of
`size_source`; `trace.py` learns the fourth value. No schema migration.

### 4. Dimensional-accuracy CI

`tests/test_organizer_dimensional_accuracy.py`, named in `.github/workflows/ci.yml` as its
own step (the licence-guard precedent: a claim about accuracy should be legible from the
job list). Two sweeps over the deck box's parameter envelope, both on the **exported and
reloaded** STL — float32, vertices merged, what a slicer would receive — never on the
in-memory kernel output:

- compile → export → reload → measure, across card counts × sleevings × wall × clearance
  × lid engagement, every measured feature within 0,05 mm;
- a corner set of that envelope through **Phase 3's assert path** (`Engineer.process`,
  `repair_mode="assert"`, `target_mm=None`) → measure, same bound.

Plus the tests that prove the assertion bites: a mesh scaled by 0,2 % fails the check
naming the feature; a mesh with a face removed fails `assert_manifold` naming the boundary
edges and exports nothing.

## Telemetry

No column, no `STAGES` change. `repair_report` gains `repair_method="asserted"`,
`assertion` and `dimension_check`. `size_source` gains a value. `generation_*` unchanged.

## Verification

1. `pytest tests/` green; the new file and `tests/test_deck_box.py` also green as their own
   step.
2. `python -m pythonsrc.organizer example deck_box > /tmp/spec.json`, then
   `python pythonsrc/pipeline.py --spec /tmp/spec.json --stop-after-phase 3` natively: the
   log shows `repair_method asserted`, the `[DS] Dimensions: 19/19` line, and
   `dimension_report.json` in the output directory.
3. Same run with the spec's mesh deliberately corrupted is not possible from the CLI (the
   compile is the source) — the unit tests carry that case.
