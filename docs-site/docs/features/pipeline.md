# Pipeline Architecture

Daedal Studio turns a description of a tabletop organizer — a deck box, a token tray, a
box insert — into a physical print whose internal dimensions match the request. The
governing rule: **a language model interprets the words; deterministic code produces the
geometry.** No dimension is ever guessed by a generative model.

## The product path

1. **Extract** — an LLM parses the prompt into a structured spec: object type, card
   count, sleeve brand and type, compartments, lid style, magnets. A curated dimension
   knowledge base resolves "double-sleeved" into millimetres. If a required field is
   missing, you get at most three quick clarifying questions.
2. **Compile** — a parametric archetype (deck box, token tray, divider, insert grid)
   turns the spec into watertight geometry, with fit tolerances applied per printer
   profile. This is ordinary arithmetic on CPU: sub-second, exact by construction.
3. **Engineer** (Phase 3) — the mesh is validated and seated for printing. A
   spec-derived mesh carries its final dimensions, so it is **never rescaled**; its
   dimensions are asserted instead.
4. **Printability gate** — 11 deterministic checks and a weighted score, shown before
   anything is sliced. Nothing non-manifold ships.
5. **Slicer** (Phase 4) — a headless **CuraEngine** instance slices with your printer
   profile's real settings (layer height, temperatures, adhesion), producing G-code
   plus honest time and filament estimates. STL/3MF export is always available.
6. **Operator** (Phase 5) — after you confirm the target printer, a firmware-specific
   operator (OctoPrint, Klipper/Moonraker, Bambu) uploads and starts the job, and
   telemetry streams back with failure detection.

The Extract and Compile stages are being built now — see the roadmap
(the internal roadmap, not published). Phases 3–5 are the mature half of the
system and carry over unchanged.

## The generative branch (benched)

The original engine — text → blueprint image (**FLUX.2-klein-4B**) → image → 3D mesh
(**TRELLIS.2-4B**, shape-only O-Voxel path) — remains in the tree but is off the
critical path. Reconstruction from an image cannot promise ±0,15 mm internal accuracy,
which is the promise this product is built on. The branch returns as the engine behind
**decorative personalization** (embossed emblems, sculptural lids), where its output is
post-validated for manifoldness and mounted onto parametrically exact bodies. It needs
an NVIDIA GPU (~24 GB VRAM), a self-hosted GPU worker, or a paid hosted endpoint.
