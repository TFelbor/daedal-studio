/**
 * The organizer spec — the shape the parametric engine will hand the UI.
 *
 * Nothing produces one of these yet. `pythonsrc/organizer/` (spec schema,
 * archetype library, dimension KB) is roadmap §§0.1–7A and is not built; the
 * backend runs the generative pipeline, and `JobStatusResponse` carries no spec
 * field. This module exists so that the day it does, the wiring is one function
 * — `specFromJob` — rather than a hunt through four components.
 *
 * Every consumer of a spec in this app renders an explicit "not available yet"
 * state, never a plausible-looking placeholder. That is not fastidiousness: this
 * product's entire pitch to a community that distrusts AI output is that the
 * numbers are real and checkable. A UI that displays "✓ Fits · 66.5 mm stack"
 * computed from nothing teaches exactly the habit the Fits Check exists to
 * break, and a screenshot of it outlives any caveat in a commit message.
 */

import type { JobStatusResponse } from '../api/client';

/** The archetypes the composer offers. Ordered as the strip presents them. */
export const ARCHETYPES = [
  { id: 'deck_box', label: 'Deck box' },
  { id: 'dice_tray', label: 'Dice tray' },
  { id: 'box_insert', label: 'Box insert' },
  { id: 'dividers', label: 'Dividers' },
] as const;

export type ArchetypeId = (typeof ARCHETYPES)[number]['id'];

/** One editable line of the spec: a label, a number, and the unit it is in. */
export interface SpecDimension {
  key: string;
  label: string;
  value: number;
  unit: string;
  /** Whether a remix may change it. A derived figure (a stack height) may not. */
  editable: boolean;
  /** Shown under the row when the number needs explaining — tolerance does. */
  note?: string;
}

/** The verdict the mm math returns, with the arithmetic that produced it. */
export interface FitsResult {
  fits: boolean;
  /** The full sum, e.g. "100 × 0.665 mm = 66.5 mm stack · internal 70.5 mm". */
  line: string;
  /** Where the sleeve and card figures came from, so the sum can be audited. */
  basis?: string;
  /** What to change when it does not fit. Present only on a failure. */
  remedy?: string;
}

export interface OrganizerSpec {
  archetype: ArchetypeId;
  /** The archetype library version that compiled it, e.g. "v3". */
  archetypeVersion: string;
  /** Content hash of the spec. The approval at the gate is bound to this. */
  hash: string;
  dimensions: SpecDimension[];
  fits: FitsResult | null;
}

/**
 * The spec for a job, or null when there is none.
 *
 * Always null today, and deliberately written as a lookup rather than a
 * `return null`: the parameter is used, the type is real, and the call sites are
 * already correct. When the server grows the field this reads it.
 */
export function specFromJob(job: Partial<JobStatusResponse> | null): OrganizerSpec | null {
  if (!job) return null;
  const spec = (job as { spec?: OrganizerSpec | null }).spec;
  return spec ?? null;
}

/**
 * Why there is no spec, in one sentence, for the empty states to show.
 *
 * One string in one place so four components cannot explain the same absence
 * four different ways.
 */
export const NO_SPEC_REASON =
  'The parametric engine is not wired up yet — this job was built by the generative pipeline, which produces geometry without a dimensioned spec.';
