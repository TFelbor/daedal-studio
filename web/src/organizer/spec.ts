/**
 * The organizer spec — the shape the parametric engine hands the UI.
 *
 * `GET /jobs/{id}` carries four parametric values for a job compiled from a spec:
 * the canonical spec itself, the hash Phase 2 compiled, the archetype and its
 * version, and Phase 3's dimension check. `specFromJob` is the one seam that turns
 * them into the display shape below; everything else in the app reads that shape.
 *
 * Two rules the projection here obeys, and both are the same rule:
 *
 * **Every row is a number somebody wrote or a number a machine measured.** The
 * table shows the spec's *own* fields — the wall the requester asked for, the
 * clearance, the card count — and nothing derived. A stack height or an internal
 * depth is a function of the dimension KB and the archetype's `derive()`, and
 * re-implementing either in TypeScript would put a second, drifting copy of the
 * arithmetic on screen. The designed figures the compiler actually produced live in
 * `compile_features.json` and are served by `GET /jobs/{id}/spec`, which nothing
 * polls; the annotated preview is where they belong.
 *
 * **The fit verdict is the measured one or none at all.** `measuredFit` renders
 * Phase 3's `dimension_check` — the exported mesh read back against the spec at
 * ±0,05 mm — and there is deliberately no path from an uncompiled spec to a badge.
 * This product's entire pitch to a community that distrusts AI output is that the
 * numbers are real and checkable. A UI that displays "✓ Fits · 66.5 mm stack"
 * computed from nothing teaches exactly the habit the Fits Check exists to break,
 * and a screenshot of it outlives any caveat in a commit message.
 */

import type { DimensionCheck, JobStatusResponse, RawSpec } from '../api/client';

export type { RawSpec };

/**
 * The archetypes the composer offers — exactly the ones the engine can compile.
 *
 * This list is `spec.ARCHETYPES` in `pythonsrc/organizer/spec.py`, and
 * `tests/test_archetype_registry.py` reads this file to hold the two to the same set.
 * It offered `dice_tray`, `box_insert` and `dividers` until the divider landed, none
 * of which existed: a strip cell for a shape the engine would refuse is the same class
 * of fabrication as a fits badge with no measurement behind it — the person picks it,
 * types a prompt, and the product silently gives them something else. The token tray
 * and the box-insert grid are real roadmap items (§0.3 Phase 2 and Phase 3); a cell
 * appears here the day the compiler does.
 *
 * Ordered as the strip presents them.
 */
export const ARCHETYPES = [
  { id: 'deck_box', label: 'Deck box' },
  { id: 'card_divider', label: 'Card divider' },
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
  /**
   * The word beside the tick, when "Fits" is not what was checked. A dimension
   * check is a comparison of a mesh against its spec, not of a stack against a
   * cavity, and labelling it "Fits" would claim a measurement nobody made.
   */
  verdict?: { pass: string; fail: string };
}

export interface OrganizerSpec {
  archetype: ArchetypeId;
  /** The archetype library version that compiled it, e.g. "v3". Null until Phase 2
   *  has run: nothing has compiled this spec yet, so no version applies to it. */
  archetypeVersion: string | null;
  /** Content hash of the spec. The approval at the gate is bound to this. */
  hash: string;
  dimensions: SpecDimension[];
  fits: FitsResult | null;
}

/** How a card kind and a sleeving read in a sentence, under the card count. */
const SLEEVING_NOTE: Record<string, string> = {
  none: 'unsleeved',
  single: 'single sleeved',
  double: 'double sleeved',
};

function row(
  key: string,
  label: string,
  value: number,
  unit: string,
  editable: boolean,
  note?: string,
): SpecDimension {
  return note ? { key, label, value, unit, editable, note } : { key, label, value, unit, editable };
}

/**
 * Phase 3's dimension check as a fit verdict, or null when nothing measured one.
 *
 * The line is the measurement itself rather than its conclusion, for the same
 * reason the stack sum is: "19/19 designed features within ±0,05 mm" is something
 * a reader can hold against the report, and "✓" on its own is a claim.
 */
export function measuredFit(check: DimensionCheck | null | undefined): FitsResult | null {
  if (!check) return null;

  const within = `${check.features_within}/${check.features_checked} designed features within ±${check.tolerance_mm} mm of the spec`;
  const worst =
    check.max_abs_error_mm == null
      ? ''
      : ` · largest error ${check.max_abs_error_mm.toFixed(3)} mm`;

  const missed = [...(check.out_of_tolerance ?? []), ...(check.missing ?? [])];
  return {
    fits: check.within_tolerance,
    line: within + worst,
    basis: 'measured off the exported mesh, after Phase 3, with the archetype’s own measure()',
    remedy: missed.length ? `Out of tolerance: ${missed.join(', ')}.` : undefined,
    verdict: { pass: 'Dimensions verified', fail: 'Dimensions off spec' },
  };
}

/**
 * The spec for a job, or null when there is none.
 *
 * Reads the four fields `GET /jobs/{id}` carries and projects them onto the display
 * shape. A prompt job has no spec and gets null, which is what puts `NO_SPEC_REASON`
 * on screen.
 */
export function specFromJob(job: Partial<JobStatusResponse> | null): OrganizerSpec | null {
  if (!job) return null;
  const spec = job.spec;
  if (!spec) return null;

  const stack = spec.compartments?.[0]?.contents;
  const p = spec.process;
  const lid = spec.lid;
  const divider = spec.divider;
  const dimensions: SpecDimension[] = [];

  if (stack) {
    const sleeving = SLEEVING_NOTE[stack.sleeving] ?? `${stack.sleeving} sleeved`;
    dimensions.push(row('card_count', 'Cards', stack.count, 'cards', true, `${stack.card}, ${sleeving}`));
  }
  if (p) {
    dimensions.push(
      row('wall_mm', 'Wall', p.wall_mm, 'mm', true),
      row('floor_mm', 'Floor', p.floor_mm, 'mm', true),
      // `fit_intent` is a word and a row's value is a number, so — like the divider's
      // `tab_position` — it rides as the note of the row it decides. A spec stored
      // before issue #71 carries no intent and gets the plain sentence: no word chose
      // its clearance, and naming one would attribute the number to a decision nobody
      // made.
      row('cavity_clearance_mm', 'Cavity clearance', p.cavity_clearance_mm, 'mm', true,
        p.fit_intent
          ? `total per axis over the sleeve envelope; ${p.fit_intent} fit`
          : 'total per axis over the sleeve envelope'),
      row('stack_slack_mm', 'Stack slack', p.stack_slack_mm, 'mm', true),
      row('min_feature_mm', 'Minimum feature', p.min_feature_mm, 'mm', true,
        'the archetype refuses anything thinner'),
    );
  }
  if (lid) {
    dimensions.push(
      row('lid_height_mm', 'Lid engagement', lid.height_mm, 'mm', true,
        lid.magnets ? `${lid.kind}, magnets` : lid.kind),
      row('lid_wall_mm', 'Lid wall', lid.wall_mm, 'mm', true),
      row('lid_clearance_mm', 'Lid clearance', lid.clearance_mm, 'mm', true,
        'per side; the fit tolerance a test coupon prints first'),
      row('lid_top_mm', 'Lid top', lid.top_mm, 'mm', true),
    );
  }
  if (divider) {
    // `tab_position` is a word and `SpecDimension.value` is a number, so it rides as
    // the tab-width row's note. The tab offset the compiler derives from it is
    // `derive()`'s figure, not the spec's, and is deliberately not re-computed here.
    dimensions.push(
      row('thickness_mm', 'Plate thickness', divider.thickness_mm, 'mm', true,
        '1,2–1,6 mm insert band; one practitioner’s practice, not a standard'),
      row('tab_width_mm', 'Tab width', divider.tab_width_mm, 'mm', true,
        `${divider.tab_position}; design default, unsourced`),
      row('tab_height_mm', 'Tab height', divider.tab_height_mm, 'mm', true,
        'how far the tab stands proud of the cards'),
    );
  }
  const limit = spec.constraints?.max_external_mm;
  const margin = spec.constraints?.fit_margin_mm;
  if (limit) {
    const axes = ['width', 'depth', 'height'] as const;
    axes.forEach((axis, i) => {
      dimensions.push(row(`max_external_${axis}_mm`, `Max external ${axis}`, limit[i], 'mm', true,
        i === 0
          ? margin
            ? 'the finished part must fit inside this, less the fit margin below'
            : 'the finished part must fit inside this'
          : undefined));
    });
    // The effective limit — stated less margin — is deliberately *not* a row. It is
    // the archetype's arithmetic, and this table shows fields somebody wrote; the
    // subtraction is named where it decides something, in the fits remedy. A spec
    // stored before issue #70 carries no margin and gets no row, because none was
    // subtracted from it.
    if (margin !== undefined) {
      dimensions.push(row('fit_margin_mm', 'Fit margin', margin, 'mm', true,
        margin
          ? 'taken off every axis before the fit check; box internals vary ±1–2 mm between copies'
          : 'zero: the stated limit is used exactly as measured'));
    }
  }

  return {
    archetype: spec.archetype as ArchetypeId,
    archetypeVersion: job.archetype_version ?? null,
    hash: job.spec_hash ?? '',
    dimensions,
    fits: measuredFit(job.dimension_check),
  };
}

/**
 * Why there is no spec, in one sentence, for the empty states to show.
 *
 * Three absences, three sentences, one place each: four components must not explain
 * the same gap four different ways, and they must not explain three different gaps
 * with one word.
 */

/** A job that was not compiled from a spec. */
export const NO_SPEC_REASON =
  'This job was built by the generative pipeline, which produces geometry from an image — there are no dimensioned parameters behind it.';

/** The composer, before anything has been submitted. */
export const UNCOMPOSED_SPEC_REASON =
  'Nothing has been composed yet — the fit check needs a spec, and a spec exists once a design has been compiled.';

/** A spec job whose Phase 3 has not measured the mesh yet. */
export const UNMEASURED_FIT_REASON =
  'Not measured yet — the fit verdict is read off the exported mesh once Phase 3 has checked every designed dimension against the spec.';
