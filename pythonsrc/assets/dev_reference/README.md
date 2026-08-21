# Dev reference assets

Real Phase 1 and Phase 2 outputs, kept in the repo so a debugging run that skips those
phases still hands Phases 3–5 something a printer would recognise.

| File | Phase it stands in for | Origin |
| --- | --- | --- |
| `blueprint.png` | 1 · Visualizer (FLUX.2) | job `ec076d7e-4bf5-49ca-a336-2ceb70a76252` |
| `raw_mesh.obj` | 2 · Sculptor (TRELLIS.2 via Pixazo) | the same job |

## Why real files and not primitives

The pipeline used to fabricate its own stand-ins: a flat blue 1024² rectangle and a
50 mm `trimesh.creation.box`. Both are useless as test inputs, and quietly so.

A cube is watertight, convex and closed, with no boundary edges, no non-manifold edges,
no thin walls and no overhangs. So `Engineer.repair_mesh` has nothing to repair, the
printability gate scores it near 100 on geometry no reconstruction ever produces, the
adhesion rule never fires, and the slicer sees six flat faces instead of a hundred
thousand. Every defect the phases downstream exist to handle was absent from the only
mesh most dev runs ever saw. The flat blueprint was worse: it is not an image of
anything, so nothing that reads it can be exercised at all.

`raw_mesh.obj` here is a 5,000-face O-Voxel reconstruction carrying **138 non-manifold
edges across 95 components** — exactly the defects `Engineer.repair_mesh`'s closing loop
and `_largest_component` were written for. It is roughly unit-scale (0.85 × 0.90 × 1.01),
like every TRELLIS.2 output, so Phase 3's scaling runs for real too.

## Rules

- **These are inputs, not provenance.** A job that used them records the reference file's
  own SHA-256, and its output directory is named `dev-{job_id}` — see
  `pipeline._will_use_reference_assets`. Never treat a `dev-` directory as evidence about
  a model.
- **`blueprint.png` must stay 1024×1024**, the shape `Visualizer.generate_blueprint`
  produces, or the artifact visibly changes size when a real render replaces it.
- **Replacing either file changes what the paid-backend guard recognises.**
  `_blueprint_is_stand_in` matches this file by hash, and that guard is the only thing
  stopping a hosted, per-generation backend from being billed to reconstruct a fixture.
