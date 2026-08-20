# Telemetry capture scope + print-outcome feedback loop

**Date:** 2026-08-20
**Status:** approved, ready for implementation
**Scope:** two changes — PR1 (deterministic capture), PR2 (human outcome feedback)

## Problem

The telemetry system records that a print happened. It does not record enough to
learn anything from it.

An audit against the required signal list found 5 of 15 covered:

| Signal | State before this change |
|---|---|
| Prompt | Present — `PrintJob.prompt` |
| Conditioning inputs | Missing. `visualizer.py` appends a hidden "clay render" suffix to every prompt; the string actually fed to FLUX is never stored. Steps, guidance scale and resolution are not stored. |
| Seed | Missing. `visualizer.py:91` calls `manual_seed(int(time.time()))` — generated inline, discarded. Nothing in the system is reproducible. |
| Model version | Partial. `generation_model` / `_version` / `_backend` cover Phase 2 (sculptor) only. No field exists for the Phase 1 FLUX model. |
| Raw mesh before repair | File exists at `data/outputs/{job_id}/raw_mesh.obj`; no database record. `engineer.py:99` logs pre-repair watertightness and face count to stdout and discards them. |
| Mesh after repair | Same. `mesh_features` holds one snapshot, not a before/after pair, so repair's effect cannot be measured. |
| Slicer pass/fail | Implicit in phase failure. Not a column. |
| Support volume | Not extracted. |
| Print time estimate | Not extracted. |
| Filament estimate | Not extracted. |
| User downloaded | Missing. `app.py:682` streams the file and records nothing. |
| User regenerated | Missing. No lineage; every `POST /jobs` is an island. |
| Printer targeted | Present — `printer_id`, `printer_firmware`. |
| Process targeted | Partial. `profile_name` string only. `layer_height_mm` is read live from the profile file at response time, so editing a profile silently rewrites history. |
| Material targeted | Missing entirely. Profiles carry `material_print_temperature`, not a material identity. |
| Actual print outcome | Partial and misleading. `outcome` is set by the machine — "the job finished" is not "it came off the bed". `FailureButton` exists but is failure-only, unprompted, and buried in JobDetail. |

Two gaps are structural rather than incremental. Without a seed, no result can be
reproduced or A/B-compared. Without a human verdict, the outcome column records the
printer's opinion and the dataset has no ground truth to learn against.

## Constraint discovered during design

CuraEngine's CLI does not populate its own G-code header. A real artifact in the repo:

```
data/octoprint/octoprint/uploads/engineered_mesh.gcode
;FLAVOR:Marlin
;TIME:6666
;Filament used: 0m          <- wrong
;MINX:2.14748e+06           <- int32 sentinel, unpopulated
```

`;TIME:` is real; `;Filament used:` and the bounding box are not. Slicer metrics must
therefore be computed from the G-code E-axis, with the header used only as a fallback.
This is why a dedicated parsing module exists rather than a five-line header regex.

## PR1 — deterministic capture

### Schema

All new columns are nullable and added by the existing `_add_missing_columns` helper in
`db.init_schema()`, so pre-existing rows stay valid and older databases migrate in place.

**Blueprint / Phase 1** — kept under a `blueprint_` prefix rather than merged into
`generation_*`, which is documented as the sculptor's and whose contract other code reads:

- `blueprint_model`, `blueprint_model_version`
- `blueprint_seed` — integer, the seed actually used
- `blueprint_prompt_engineered` — the suffixed string fed to FLUX, not the user's prompt
- `blueprint_params` — JSON: steps, guidance_scale, width, height
- `blueprint_sha256` — hash of the PNG; also identifies user-supplied images under `--skip-visualizer`
- `blueprint_duration_s`

**Mesh lineage** — `mesh_features` keeps its documented meaning (the printed mesh):

- `raw_mesh_sha256`, `raw_mesh_features` (JSON)
- `repaired_mesh_sha256`, `repaired_mesh_features` (JSON)

**Slicing:**

- `slice_status` — `success` | `failed` | `skipped`
- `slice_error`, `slice_duration_s`
- `estimated_print_time_s`
- `filament_used_mm`, `filament_used_mm3`, `filament_used_g`
- `support_filament_mm3`
- `layer_count`
- `slice_stats` — JSON: per-`;TYPE:` extrusion breakdown plus the raw header

**Target:**

- `material_type`, `material_brand`, `material_colour`
- `nozzle_diameter_mm`
- `process_params` — JSON snapshot of the resolved profile, frozen at job creation

`process_params` fixes a live defect: `layer_height_mm` is currently read from the
profile file when a job is queried, so a profile edit retroactively changes what old
jobs claim to have printed with.

**Engagement:** `parent_job_id`, `download_count`.

### `job_event` table

```sql
CREATE TABLE IF NOT EXISTS job_event (
    event_id    TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    detail      TEXT,
    FOREIGN KEY (job_id) REFERENCES print_job(job_id)
);
```

`kind` is one of `download`, `regenerate`, `outcome_prompt_shown`,
`outcome_prompt_dismissed`, `outcome_reported`.

One table rather than six columns. PR2 needs precisely this shape: the pilot's central
question — will people report outcomes — is `count(outcome_reported) /
count(outcome_prompt_shown)`, answerable from day one without a schema change.

### `pythonsrc/gcode_stats.py`

A single streaming pass over the G-code file returning a `SliceStats` dataclass.

- Tracks `M82` / `M83` (absolute vs relative extrusion) and `G92 E` resets.
- Sums positive E deltas, attributing each to the current `;TYPE:` section.
- Volume: `mm3 = mm * pi * (d/2)^2`, with `d` from the profile's `material_diameter`,
  defaulting to 1.75 mm.
- Support: the `SUPPORT` and `SUPPORT-INTERFACE` sections.
- `layer_count` from the highest `;LAYER:` index, falling back to distinct Z heights.
- Mass from a material density table (PLA 1.24, PETG 1.27, ABS 1.04, TPU 1.21,
  ASA 1.07 g/cm3); null when the material is unknown.
- The header's `;Filament used:` is consulted only when E-derivation yields zero.

Tested against synthetic G-code fixtures, so the test suite needs no CuraEngine.

### Seed

`Visualizer.generate_blueprint` takes `seed: int | None = None`. When None it draws from
`random.SystemRandom().randrange(2**32)` — not `time.time()`, which collides across jobs
started in the same second — and returns the value used.

The return type changes from `Path` to a `BlueprintResult` dataclass carrying path, seed,
engineered prompt, params and duration. This breaks one in-repo caller and the CLI at
`visualizer.py:126`; both are updated and a test guards the contract.

### Pipeline wiring

Three recorders alongside the existing `_record_generation`, each following its pattern —
a no-op without `--job-id`, wrapped in try/except so a telemetry failure never fails a
print:

- `_record_blueprint()` after Phase 1
- `_record_mesh_lineage()` after Phase 3
- `_record_slice()` after Phase 4, **including on failure**, writing `slice_status="failed"`
  and the error text

The features dict at `printability.py:743` is extracted into
`extract_features(mesh, *, thickness=False)` and reused for the raw and repaired meshes
with the expensive voxel wall-thickness pass disabled. `engineer.py:99` already computes
before/after watertightness and face counts; those values are passed through rather than
recomputed.

### Server

- `JobRequest` gains `material_type`, `material_brand`, `material_colour`,
  `parent_job_id`, `regeneration_reason`, `seed`.
- `POST /jobs` resolves and freezes the profile into `process_params`, deriving
  `nozzle_diameter_mm`.
- `GET /jobs/{id}/download` logs a `download` job_event and increments `download_count`.
- `GET /jobs/{id}/provenance` is new and returns the full capture record, keeping
  `JobStatusResponse` from ballooning.
- `layer_height_mm` in `JobStatusResponse` reads from frozen `process_params`, falling
  back to the live profile only for rows predating this change.

### UI

- Material select plus brand and colour inputs on the job submission form.
- A **Regenerate** button on JobDetail that posts a new job carrying `parent_job_id` and
  the same prompt, forming a lineage chain.

## PR2 — print-outcome feedback

### Model

`PrintJob` gains `outcome_source` (`machine` | `user`) and `outcome_reported_at`. A job
whose printer reports completion enters `awaiting_verdict` rather than being recorded as
a success, and an `outcome_prompt_shown` event is written.

### Delivery

In-app pending queue. A persistent app-shell banner reads "N prints awaiting verdict".
Each card shows the blueprint thumbnail and three controls: **Came off clean**,
**Failed**, **Skip**. Choosing Failed expands the existing `FailureButton` taxonomy
inline rather than opening a separate modal.

### Endpoint

`POST /jobs/{id}/outcome` with `{verdict, failure_type?, notes?, layer_pct?}` writes
`outcome`, `outcome_source="user"` and `outcome_reported_at`, and on a failure verdict
also inserts a `FailureEvent(source="manual")` so the existing detector-versus-human
comparison keeps working unchanged.

The endpoint accepts an optional signed token parameter from the outset, so adding email
or webhook delivery later is a configuration change rather than a refactor.

### Measuring the pilot

Skip is recorded as `outcome_prompt_dismissed`, not treated as silence. Whether people
will report at all is the thing being tested, so dismissal must be distinguishable from
never having been asked.

## Testing

- `tests/test_gcode_stats.py` — absolute and relative extrusion, `G92` resets, support
  sections, absent header, malformed lines.
- `tests/test_telemetry_capture.py` — each recorder writes the expected columns and
  swallows database errors without raising.
- `tests/test_db.py` — migration of a database file created before these columns existed.
- `tests/test_server.py` — a download logs an event; material fields round-trip; frozen
  `process_params` does not drift when the profile file changes afterwards.
- Seed determinism end-to-end is marked `slow` / `full_pipeline` since it needs FLUX; the
  unit-level test stubs the pipe and asserts the seed is returned and persisted.

## Non-goals

- No remote artifact storage. Hashes in the database, files on local disk.
- No push notification delivery in PR2.
- No backfill. Hashes could be computed for the thirteen existing job directories, but
  seed and conditioning cannot be recovered, and a partial backfill would be
  indistinguishable from genuinely captured data. Pre-existing rows stay NULL.
