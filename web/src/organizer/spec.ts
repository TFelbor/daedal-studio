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

import type {
  DimensionCheck,
  JobStatusResponse,
  RawCardStack,
  RawContents,
  RawSpec,
  ResolvedGameBox,
} from '../api/client';

export type { RawSpec };

/**
 * Whether a compartment holds cards rather than a pocket.
 *
 * The same narrowing the schema does — `count` against `width_mm`/`depth_mm`/
 * `height_mm`, with no `kind` discriminator, because adding one would have moved the
 * `spec_hash` of every spec ever stored (`Compartment` in
 * `pythonsrc/organizer/spec.py`). One function rather than an inline `'count' in c` at
 * each site, so the two halves cannot come apart.
 */
export function isCardStack(contents: RawContents): contents is RawCardStack {
  return 'count' in contents;
}

/**
 * The archetypes the composer offers — exactly the ones the engine can compile.
 *
 * This list is `spec.ARCHETYPES` in `pythonsrc/organizer/spec.py`, and
 * `tests/test_archetype_registry.py` reads this file to hold the two to the same set.
 * It offered `dice_tray`, `box_insert` and `dividers` until the divider landed, none
 * of which existed: a strip cell for a shape the engine would refuse is the same class
 * of fabrication as a fits badge with no measurement behind it — the person picks it,
 * types a prompt, and the product silently gives them something else. The token tray
 * joined the day its compiler did (issue #84), and the box insert the day its compiler
 * did (issue #152) — which is the rule those three dead cells were removed to establish,
 * honoured twice now rather than merely stated.
 *
 * Ordered as the strip presents them.
 */
export const ARCHETYPES = [
  { id: 'deck_box', label: 'Deck box' },
  { id: 'card_divider', label: 'Card divider' },
  { id: 'token_tray', label: 'Token tray' },
  { id: 'box_insert', label: 'Box insert' },
] as const;

export type ArchetypeId = (typeof ARCHETYPES)[number]['id'];

/**
 * The other five closed vocabularies the composer offers, for the strip's reason.
 *
 * Each is a literal in `pythonsrc/organizer/spec.py` or
 * `pythonsrc/organizer/dimensions.py`, and `tests/test_composer_options.py` holds
 * every one of them to its counterpart the way `test_archetype_registry.py` holds
 * `ARCHETYPES`. An option a form offers and the schema refuses is the same class of
 * fabrication as a fits badge with no measurement behind it — the person picks it,
 * submits, and is told by a 422 that the thing they were shown does not exist.
 *
 * They are lists rather than a call to the server on mount because a select that
 * cannot render until a fetch returns is a select that renders empty when it fails.
 * The binding is a test, not a round trip.
 */

/** `dimensions.CARD_KINDS`. One entry: the Japanese size has no sourced sleeve
 *  envelope, and a footprint invented to fill that gap is a fabricated number. */
export const CARD_KINDS = ['standard'] as const;

/** `dimensions.SLEEVINGS`. */
export const SLEEVINGS = ['none', 'single', 'double'] as const;

/** `spec.LID_KINDS`. Slide, hinged and magnetic lids are later archetype variants. */
export const LID_KINDS = ['lift_off'] as const;

/** `spec.FIT_INTENTS`, in the order they widen the cavity. A word rather than a
 *  number because it is what a person actually decides; the millimetres are the KB's
 *  and arrive on the resolved spec. */
export const FIT_INTENTS = ['snug', 'easy'] as const;

/** `spec.TAB_POSITIONS`. */
export const TAB_POSITIONS = ['left', 'centre', 'right'] as const;

/** `spec.EMBOSS_FACES` — every face any archetype can letter. Which of them a given
 *  archetype honours is `EMBOSS_FACES_BY_ARCHETYPE` below; this is the union. */
export const EMBOSS_FACES = ['lid_top', 'front', 'back', 'left', 'right', 'tab'] as const;

/** `spec.EMBOSS_MODES`. */
export const EMBOSS_MODES = ['raised', 'recessed'] as const;

/**
 * Which faces each archetype actually letters, and the modes each of those takes.
 *
 * The archetype's own `EMBOSS_FACES` and `emboss_frame(...).modes`, mirrored here for
 * the archetype strip's reason verbatim: a form that offered a face the engine refuses
 * would let a person pick it, submit, and be told by a 422 that the thing they were
 * shown does not exist. `tests/test_composer_options.py` binds every entry to the
 * module that builds it.
 *
 * **The token tray and the box insert letter nothing**, so the composer shows no
 * lettering group for them at all: a tray's 1,6 mm wall cannot host a 0,6 mm recess
 * above the floor, and an insert's outer faces live inside a game box where nobody sees
 * them. An archetype with no entry is an archetype with no group.
 *
 * **Only the divider's tab takes `raised`.** It is the one face of any archetype here
 * that points up as it prints: a deck box lid is printed open side up, so the face a
 * person looks at is against the bed, and the box's walls are vertical, where a raised
 * letter would overhang at 90° along its whole underside.
 */
export const EMBOSS_FACES_BY_ARCHETYPE: Record<string, { face: string; modes: string[] }[]> = {
  deck_box: [
    { face: 'lid_top', modes: ['recessed'] },
    { face: 'front', modes: ['recessed'] },
    { face: 'back', modes: ['recessed'] },
    { face: 'left', modes: ['recessed'] },
    { face: 'right', modes: ['recessed'] },
  ],
  card_divider: [{ face: 'tab', modes: ['raised', 'recessed'] }],
};

/** `lettering.EMBOSS_TEXT_MAX_CHARS`, and the bound on `JobRequest.embossing_text`. */
export const EMBOSS_TEXT_MAX_CHARS = 64;

/** `spec.EMBOSS_CAP_HEIGHT_MM` — the cap height an emboss is set at by default. */
export const EMBOSS_CAP_HEIGHT_MM = 8.0;

/** `spec.EMBOSS_RELIEF_FLOOR_MM` — two 0,2 mm layers, the least relief that reads. */
export const EMBOSS_RELIEF_FLOOR_MM = 0.4;

/** What each face is called in the words somebody would use to pick it. */
export const EMBOSS_FACE_LABELS: Record<string, string> = {
  lid_top: 'Lid top',
  front: 'Front',
  back: 'Back',
  left: 'Left side',
  right: 'Right side',
  tab: 'Tab',
};

/** What each mode does, said as the thing it does to the part. */
export const EMBOSS_MODE_LABELS: Record<string, string> = {
  raised: 'Raised — stands proud of the face',
  recessed: 'Recessed — sunk into the face',
};

/** What each fit intent means in the words somebody would use to choose it. */
export const FIT_INTENT_LABELS: Record<string, string> = {
  snug: 'Snug — a box you close',
  easy: 'Easy — a tray you lift cards out of',
};

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
export const SLEEVING_NOTE: Record<string, string> = {
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
 * What one interior row says about where its millimetre came from.
 *
 * The one place the KB/typed distinction is drawn, and it is drawn on **every** axis
 * rather than once at the top, because provenance in this project is per value: a box
 * whose width came off a caliper and whose height came off a product page is two
 * different claims, and `box_kb.Measurement` carries a basis, a source and a capture date
 * for each of the three. Flattening that into one sentence over the group would throw
 * away the thing the KB exists to give.
 *
 * Three states, and the difference between them is the whole of issue #154:
 *
 * - **A curated box, resolved** — the entry's own provenance sentence for this axis.
 *   A source and a date, checkable against the page it was transcribed from.
 * - **A curated box this build cannot resolve** — the spec names an entry or a KB
 *   version this build does not carry. The id and the version are said, and no source
 *   is claimed, because none can honestly be.
 * - **No box at all** — the degraded mode, and it is named as such rather than left
 *   blank. Three millimetres somebody typed are a perfectly good input and the reason
 *   `fit_margin_mm` exists; what they are not is a measurement anybody can check, and a
 *   row that stayed silent about that would let the two look identical.
 */
export function interiorNote(
  box: RawSpec['box'],
  resolved: ResolvedGameBox | null | undefined,
  axis: 'width' | 'depth' | 'height',
  first: boolean,
  margined: boolean,
): string {
  const fit = margined
    ? 'the finished part must fit inside this, less the fit margin below'
    : 'the finished part must fit inside this';
  if (!box) {
    return first
      ? `typed interior — no box in the dimension KB was named; ${fit}`
      : 'typed interior — no source behind this number';
  }
  const source = resolved?.resolved ? resolved.provenance?.[axis] : undefined;
  if (source) return first ? `${source}; ${fit}` : source;
  return first
    ? `dimension KB entry ‘${box.id}’, version ${box.kb_version} — this build cannot resolve it, so no source is shown; ${fit}`
    : `dimension KB entry ‘${box.id}’, version ${box.kb_version} — this build cannot resolve it, so no source is shown`;
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

  const contents = spec.compartments?.[0]?.contents;
  const p = spec.process;
  const lid = spec.lid;
  const divider = spec.divider;
  const tray = spec.tray;
  const insert = spec.insert;
  const dimensions: SpecDimension[] = [];

  if (insert) {
    // A box insert's compartments are **not** all the same shape, which is the one
    // assumption every other branch here is allowed to make. Reading `compartments[0]`
    // and describing the whole part with it — which is what this function did before
    // issue #152 — would show a deck's card count as though it were the part, with two
    // pockets silently missing from a table whose entire promise is that every row on
    // it is a number somebody wrote.
    //
    // So every compartment is listed, indexed as the spec indexes it, in the words of
    // whichever shape it is. The row grouping is listed too, because it is the layout:
    // nothing here computes a position, and `insert.rows` is what a remix would change
    // to move a compartment.
    dimensions.push(
      row('insert_rows', 'Rows', insert.rows.length, 'rows', true,
        `${insert.rows.join(' / ')} compartments per row, front to back`),
    );
    (spec.compartments ?? []).forEach((compartment, i) => {
      const held = compartment?.contents;
      if (!held) return;
      const label = `Compartment ${i + 1}`;
      if (isCardStack(held)) {
        const sleeving = SLEEVING_NOTE[held.sleeving] ?? `${held.sleeving} sleeved`;
        dimensions.push(
          row(`c${i}_count`, `${label} cards`, held.count, 'cards', true,
            `${held.card}, ${sleeving}; the well is the resolved footprint plus the clearance`),
        );
        return;
      }
      const provenance = held.source ?? 'user-given mm — no token or dice size is sourced';
      dimensions.push(
        row(`c${i}_width_mm`, `${label} width`, held.width_mm, 'mm', true, provenance),
        row(`c${i}_depth_mm`, `${label} depth`, held.depth_mm, 'mm', true, provenance),
        row(`c${i}_height_mm`, `${label} depth (Z)`, held.height_mm, 'mm', true, provenance),
      );
    });
  } else if (contents && isCardStack(contents)) {
    const sleeving = SLEEVING_NOTE[contents.sleeving] ?? `${contents.sleeving} sleeved`;
    dimensions.push(
      row('card_count', 'Cards', contents.count, 'cards', true, `${contents.card}, ${sleeving}`),
    );
  } else if (contents) {
    // A pocket. The grid is two of the spec's own fields — the compartment count and
    // `tray.columns` — and the division between them is the same one `token_tray.derive`
    // does; nothing else here is computed. The provenance note is `Pocket.source` when
    // somebody gave one, and says the millimetres were typed when they did not, because
    // no token or dice size is sourced anywhere and a row that implied otherwise would
    // be the fabrication this table exists to refuse.
    const columns = tray?.columns;
    const count = spec.compartments?.length ?? 0;
    const provenance = contents.source ?? 'user-given mm — no token or dice size is sourced';
    if (columns) {
      dimensions.push(
        row('columns', 'Columns', columns, 'pockets', true),
        row('rows', 'Rows', count / columns, 'pockets', false, 'compartments ÷ columns'),
      );
    }
    dimensions.push(
      row('pocket_width_mm', 'Pocket width', contents.width_mm, 'mm', true, provenance),
      row('pocket_depth_mm', 'Pocket depth', contents.depth_mm, 'mm', true, provenance),
      row('pocket_height_mm', 'Pocket depth (Z)', contents.height_mm, 'mm', true, provenance),
    );
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
    // The three edge treatments, each shown only when the spec carries it. A row
    // stored before issue #80 was built by an archetype that had no chamfer and no
    // corner round, so filling the gap with today's default would put a feature on
    // screen that is not on that mesh. Their notes say **design default, unsourced**
    // for the reason the divider's tab rows do: the audited insert document calls the
    // features mandatory and names no millimetre for any of them.
    if (p.base_chamfer_mm !== undefined) {
      dimensions.push(row('base_chamfer_mm', 'Base chamfer', p.base_chamfer_mm, 'mm', true,
        '45°, against warping; design default, unsourced'));
    }
    if (p.corner_radius_mm !== undefined) {
      dimensions.push(row('corner_radius_mm', 'Corner radius', p.corner_radius_mm, 'mm', true,
        'external vertical corners, against elephant-foot flare; design default, unsourced'));
    }
    if (p.cavity_corner_radius_mm !== undefined) {
      dimensions.push(row('cavity_corner_radius_mm', 'Cavity corner radius',
        p.cavity_corner_radius_mm, 'mm', true, 'internal vertical corners'));
    }
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
  const emboss = spec.emboss;
  if (emboss) {
    // The text, the face and the mode are all *words*, and a row's value is a number,
    // so they ride as the notes of the two rows they size — `tab_position` and
    // `fit_intent` before them. The ink's own millimetres are deliberately not here:
    // they are a function of the vendored font's metrics, and re-deriving them in a
    // browser is exactly the second drifting copy this table exists to refuse.
    // `POST /organizer/resolve` returns them, measured by the same code the compiler
    // sets the glyphs with.
    const face = EMBOSS_FACE_LABELS[emboss.face] ?? emboss.face;
    dimensions.push(
      row('emboss_height_mm', 'Lettering height', emboss.height_mm, 'mm', true,
        `cap height of “${emboss.text}”, ${emboss.mode} on the ${face.toLowerCase()}`),
      row('emboss_relief_mm', 'Lettering relief', emboss.relief_mm, 'mm', true,
        emboss.mode === 'raised'
          ? 'how far the glyphs stand proud; design default, unsourced'
          : 'how deep the glyphs are cut; design default, unsourced'),
    );
  }
  const limit = spec.constraints?.max_external_mm;
  const margin = spec.constraints?.fit_margin_mm;
  if (limit) {
    const axes = ['width', 'depth', 'height'] as const;
    axes.forEach((axis, i) => {
      dimensions.push(row(`max_external_${axis}_mm`, `Max external ${axis}`, limit[i], 'mm', true,
        interiorNote(spec.box, job.game_box, axis, i === 0, margin !== undefined && margin > 0)));
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
 * Four absences, four sentences, one place each: the components must not explain the
 * same gap four different ways, and they must not explain four different gaps with
 * one word. The composer gained the fourth — a spec that exists and has been
 * resolved, but that nothing has built geometry from yet — because reusing
 * `UNCOMPOSED_SPEC_REASON` there would have said "nothing has been composed" under a
 * table of the composed spec's own millimetres.
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

/**
 * The composer, with a spec the server has resolved but nothing has compiled.
 *
 * The composer cannot answer "does it fit" and does not try: the archetype's own
 * `fits_check` needs the geometry kernel, which the API server does not install, and
 * the verdict this product shows is a measurement of the exported mesh rather than a
 * prediction about it. What the composer *can* show — and does, above this line — is
 * the spec's own millimetres and the resolved stack, both computed by the server.
 */
export const UNCOMPILED_SPEC_FIT_REASON =
  'Nothing has been built from this spec yet — the fit verdict is a measurement of the exported mesh, taken in Phase 3 after the archetype compiles the numbers above.';
