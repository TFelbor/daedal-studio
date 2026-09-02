/**
 * The five phases, named once.
 *
 * Two places show this list — the composer's "what runs when you hit send" panel
 * and the running rail — and they used to carry separate copies, so renaming a
 * phase in one left the other describing the old machine. The names are also the
 * *only* labels the UI uses: the server sends a name alongside each phase update
 * and the client has never rendered it, keying off the phase number instead. That
 * is what makes this file the single source rather than a second opinion.
 *
 * ── A note the next person needs ──────────────────────────────────────────────
 * These names describe the parametric pipeline the product is pivoting to
 * (`docs/PRD_daedal_tcg_organizers.md`, roadmap §§0.1–7A), not, phase for phase,
 * what the backend runs today. Today phase 1 renders a blueprint image with
 * FLUX.2 and phase 2 reconstructs it with TRELLIS.2; `pythonsrc/organizer/`
 * does not exist yet. Phase 3 is the Engineer — watertight repair and scaling —
 * and the printability gate it is named for actually runs *between* phases 3 and
 * 4, deliberately unnumbered, because the `.status` protocol and every
 * historical status file key off phases 1–5.
 *
 * The names were adopted ahead of the engine on purpose, as the product's
 * vocabulary. When the parametric engine lands, phases 1–3 start meaning what
 * they say here and this comment comes out. Until then, do not read a label on
 * this list as a claim about which model ran — the telemetry columns
 * (`generation_model`, `blueprint_model`) are what record that, and they are
 * unaffected by anything in this file.
 */

export interface PipelinePhaseSpec {
  /** 1-indexed, matching the pipeline's own banners and `.status` records. */
  phase: number;
  name: string;
  /** One line on what the phase does, for the composer's pipeline panel. */
  blurb: string;
  /** The artifact or technique, set in mono as a right-hand tag. */
  tag: string;
}

export const PIPELINE: readonly PipelinePhaseSpec[] = [
  {
    phase: 1,
    name: 'Composer',
    blurb: 'Your words become a structured spec — counts, sleeves, millimetres',
    tag: 'LLM · SPEC',
  },
  {
    phase: 2,
    name: 'Compiler',
    blurb: "The archetype library builds exact geometry from the spec's numbers",
    tag: 'CSG · MESH',
  },
  {
    phase: 3,
    name: 'Printability',
    blurb: 'Watertight, wall thickness, fit tolerance — scored before slicing',
    tag: 'VERDICT',
  },
  {
    phase: 4,
    name: 'Slicer',
    blurb: "Sliced with your printer's real profile — time and grams are real numbers",
    tag: 'G-CODE',
  },
  {
    phase: 5,
    name: 'Operator',
    blurb: 'Dispatched only after you confirm the target machine',
    tag: 'JOB',
  },
] as const;

/** Just the names, in phase order — what the running rail lists. */
export const PHASE_NAMES: readonly string[] = PIPELINE.map((p) => p.name);

/** The name for a 1-indexed phase number, or a stable fallback for an unknown one. */
export function phaseName(phase: number): string {
  return PIPELINE[phase - 1]?.name ?? `Phase ${phase}`;
}
