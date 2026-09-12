/**
 * The configurator's state, and the two translations it needs.
 *
 * This is the *form* half of the parametric path — roadmap §5A's cut #3 and the alpha
 * vehicle. It builds an organizer spec out of what somebody typed and routes the
 * server's refusals back onto the controls that caused them. LLM extraction is a
 * later issue and is deliberately not on this path: the rule the pivot turns on is
 * that the LLM interprets words and never produces geometry, and a form is what that
 * leaves once the words are taken away.
 *
 * Two rules, and they are the same rule as everywhere else in `organizer/`:
 *
 * **This file computes no millimetres.** It assembles fields and sends them; the
 * numbers on screen come back from `POST /organizer/resolve`, which runs the same
 * schema and the same dimension table the geometry is built from. A blank optional
 * field is *omitted* rather than filled with a default here — the schema's defaults
 * are the schema's, and a copy of them in TypeScript would drift the first time one
 * moved.
 *
 * **No problem is dropped.** Every refusal the server returns is routed to a control
 * by its dotted path, and anything this file does not recognise lands on `form`,
 * which the panel shows whole. A validation message that matches nothing and is
 * silently discarded is worse than an ugly one: the submit button just stops working.
 */

import type { SpecProblem } from '../api/client';
import { type ArchetypeId } from './spec';

/** Every control the configurator renders, plus `form` for anything unrouted. */
export type SpecField =
  | 'archetype'
  | 'count'
  | 'card'
  | 'sleeving'
  | 'fitIntent'
  | 'wallMm'
  | 'lidHeightMm'
  | 'thicknessMm'
  | 'tabWidthMm'
  | 'tabHeightMm'
  | 'tabPosition'
  | 'form';

/**
 * What the configurator holds. Numbers are kept as the strings that were typed and
 * converted once, at `specFromForm` — the `seed` and `customHeight` precedent in
 * `NewJob`. A half-typed "1." is a string, and turning it into a number on every
 * keystroke makes the field fight the person editing it.
 */
export interface SpecFormState {
  archetype: ArchetypeId;
  count: string;
  card: string;
  sleeving: string;
  /** Deck box only: the divider reads neither `fit_intent` nor `process.wall_mm`. */
  fitIntent: string;
  wallMm: string;
  lidHeightMm: string;
  /** Card divider only. */
  thicknessMm: string;
  tabWidthMm: string;
  tabHeightMm: string;
  tabPosition: string;
}

/**
 * What the form opens on.
 *
 * The only figure here that is a *value* rather than a vocabulary entry is the card
 * count, and 100 is the Commander deck the dimension research is written around —
 * the same stack `deck_box.example()` builds. Every millimetre field opens blank,
 * which means "take the schema's", so the panel's first render shows the archetype's
 * own wall rather than a number this file made up.
 */
export const DEFAULT_SPEC_FORM: SpecFormState = {
  archetype: 'deck_box',
  count: '100',
  card: 'standard',
  sleeving: 'double',
  fitIntent: 'snug',
  wallMm: '',
  lidHeightMm: '',
  thicknessMm: '',
  tabWidthMm: '',
  tabHeightMm: '',
  tabPosition: 'centre',
};

/**
 * An optional millimetre field: omitted when blank, sent as typed otherwise.
 *
 * `undefined` means "the key is absent", which the schema reads as "use my default".
 * Anything that is not a number is sent **as the text that was typed**, and `_mm`
 * answers it by name — `process.wall_mm must be a number in mm, got '2,4'` — on the
 * control that caused it.
 *
 * It used to be sent as `null`, and for one field that silently meant the opposite.
 * `Process.wall_mm` documents explicit null as *the same as omitted: take the
 * archetype default* (`pythonsrc/organizer/spec.py`), so "2,4" with a comma — which
 * is how a millimetre is written everywhere this product speaks — resolved clean,
 * showed 2,4 mm in the panel, put no problem on the wall field, and compiled the
 * archetype's default instead of the wall the person had asked for. The other mm
 * fields refused null by name, so the same keystroke behaved two ways.
 *
 * Sending the text rather than `null` also makes the refusal a better one: it names
 * the field *and* quotes what was typed, which is what tells someone the decimal
 * separator is the problem.
 */
function optionalMm(raw: string): number | string | undefined {
  if (!raw.trim()) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : raw.trim();
}

/**
 * A required number: blank is not "default", it is a missing value, so it is sent.
 *
 * `null` for blank, because that is the state the schema must refuse as *missing*;
 * unparseable text is sent as typed, for `optionalMm`'s reason.
 */
function requiredNumber(raw: string): number | string | null {
  if (!raw.trim()) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : raw.trim();
}

/** Drop the keys whose value is `undefined`, so an omitted field is truly omitted. */
function present(entries: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(entries).filter(([, v]) => v !== undefined));
}

/**
 * The form as an organizer spec, ready for `/organizer/resolve` or `POST /jobs`.
 *
 * The archetype decides which optional section is present, and both archetypes
 * *require* theirs: `deck_box.validate` refuses a spec with no `lid`, and
 * `card_divider.validate` refuses one with no `divider` and one that carries a lid.
 * Neither of those rules can run on the API server — they import the geometry kernel
 * — so a section left out here would not be a 422, it would be a failed Phase 2 ten
 * seconds into a run. The empty object is what carries the schema's own defaults.
 */
export function specFromForm(state: SpecFormState): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    archetype: state.archetype,
    compartments: [
      {
        contents: {
          count: requiredNumber(state.count),
          card: state.card,
          sleeving: state.sleeving,
        },
      },
    ],
    schema_version: 1,
  };

  if (state.archetype === 'deck_box') {
    spec.lid = present({ kind: 'lift_off', height_mm: optionalMm(state.lidHeightMm) });
    spec.process = present({ fit_intent: state.fitIntent, wall_mm: optionalMm(state.wallMm) });
  } else {
    spec.divider = present({
      tab_position: state.tabPosition,
      thickness_mm: optionalMm(state.thicknessMm),
      tab_width_mm: optionalMm(state.tabWidthMm),
      tab_height_mm: optionalMm(state.tabHeightMm),
    });
  }

  return spec;
}

/**
 * Which control a dotted problem path belongs to.
 *
 * The keys are exactly the paths `specFromForm` can produce a bad value at, and
 * `tests/test_composer_options.py` pokes each one to prove the schema really names
 * it that way. Anything else — a section this form does not edit, a rule about the
 * spec as a whole — is `form`, which is shown whole rather than swallowed.
 */
export const FIELD_BY_PATH: Record<string, SpecField> = {
  'spec.archetype': 'archetype',
  'spec.compartments[0].contents.count': 'count',
  'spec.compartments[0].contents.card': 'card',
  'spec.compartments[0].contents.sleeving': 'sleeving',
  'spec.process.fit_intent': 'fitIntent',
  'spec.process.wall_mm': 'wallMm',
  'spec.lid.height_mm': 'lidHeightMm',
  'spec.divider.thickness_mm': 'thicknessMm',
  'spec.divider.tab_width_mm': 'tabWidthMm',
  'spec.divider.tab_height_mm': 'tabHeightMm',
  'spec.divider.tab_position': 'tabPosition',
};

export function fieldForPath(path: string): SpecField {
  return FIELD_BY_PATH[path] ?? 'form';
}

/**
 * The live resolve's problems and a refused submit's, as one list without repeats.
 *
 * They come from the same schema and normally agree word for word, so the union is
 * deduplicated by message — but the submit's are kept rather than assumed redundant.
 * `POST /jobs` validates more than `/organizer/resolve` does (a spec beside a
 * requested size, for one), and a refusal only it can produce must still be shown.
 */
export function mergeProblems(live: SpecProblem[], submitted: SpecProblem[]): SpecProblem[] {
  const seen = new Set(live.map((p) => p.message));
  return [...live, ...submitted.filter((p) => !seen.has(p.message))];
}

/** Every problem, grouped by the control it belongs on. Nothing is discarded. */
export function problemsByField(problems: SpecProblem[]): Partial<Record<SpecField, string[]>> {
  const grouped: Partial<Record<SpecField, string[]>> = {};
  for (const problem of problems) {
    const field = fieldForPath(problem.path);
    (grouped[field] ??= []).push(problem.message);
  }
  return grouped;
}
