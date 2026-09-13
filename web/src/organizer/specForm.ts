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
  | 'rows'
  | 'columns'
  | 'pocketWidthMm'
  | 'pocketDepthMm'
  | 'pocketHeightMm'
  | 'form';

/**
 * The millimetre fields that are *content* rather than process — the ones the schema
 * has no default for, so a blank one is a missing value and not "take yours".
 *
 * Every other `…Mm` field in this form opens blank on purpose: the archetype's wall,
 * the lid's engagement, the plate's thickness all have schema defaults, and a copy of
 * one here would be a second figure drifting from the one the geometry is built with.
 * A pocket has no such default and cannot have one — `dimensions.py` carries no token
 * or dice sizes, because an invented one is the fabricated number the schema exists to
 * refuse — so the three pocket dimensions are the typed *input*, exactly as `count` is
 * for a deck. They open on a value for the same reason `count` opens on 100: pick
 * `Token tray`, touch nothing, press send, and a part comes out.
 *
 * `tests/test_composer_options.py` reads this list and holds every name in it to that
 * claim by poking the schema — a field the schema *does* default cannot be added here
 * to escape the blank rule.
 */
export const REQUIRED_CONTENT_MM: SpecField[] = [
  'pocketWidthMm',
  'pocketDepthMm',
  'pocketHeightMm',
];

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
  /** Token tray only: the grid, and the pocket every cell of it holds. */
  rows: string;
  columns: string;
  pocketWidthMm: string;
  pocketDepthMm: string;
  pocketHeightMm: string;
}

/**
 * What the form opens on.
 *
 * The figures here that are *values* rather than vocabulary entries are the contents:
 * the card count, and the token tray's grid and pocket. 100 is the Commander deck the
 * dimension research is written around — the same stack `deck_box.example()` builds —
 * and the 2 × 3 grid of 20 × 20 × 15 mm pockets is what `token_tray.example()` builds,
 * a **design example and not a sourced token size**, which is what the pocket fields'
 * own note says on screen. Every *process* millimetre field opens blank, which means
 * "take the schema's", so the panel's first render shows the archetype's own wall
 * rather than a number this file made up. See `REQUIRED_CONTENT_MM`.
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
  rows: '2',
  columns: '3',
  pocketWidthMm: '20',
  pocketDepthMm: '20',
  pocketHeightMm: '15',
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

/** A positive whole number, which is the only thing either side of the grid may be. */
function wholeCount(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isInteger(value) && value >= 1 ? value : null;
}

/**
 * The refusals this form makes on its own, before anything is sent anywhere.
 *
 * There is exactly one, and it exists because the grid is the one input the schema
 * cannot answer for. **`rows` is never sent** — `Tray` carries `columns` only, and the
 * row count is `len(compartments) // columns`, which is the schema's own deliberate
 * choice so that a spec cannot state a grid its compartment list fails to fill. That
 * leaves the browser holding a control with no dotted path, and a control the server
 * cannot name is a control whose refusal has nowhere to come from: a blank, `0` or
 * `2.5` row count used to become *one* compartment, which with three columns is a spec
 * the schema accepts, `/organizer/resolve` reports clean, and `token_tray.validate`
 * refuses ten seconds into Phase 2 — and with one column is a 1 × 1 tray, built and
 * printed, for a grid nobody typed.
 *
 * `columns` is judged here too, though the schema does name it. The two are read
 * together — a bad either makes the same nonsense compartment list — and splitting the
 * judgement would mean a bad column count arriving as its own refusal *plus* an
 * `spec.compartments must hold at least one compartment` about the empty list it
 * caused, on the `form` panel, which is the catch-all for rules about the spec as a
 * whole. One sentence on the control that caused it is the whole contract of this file.
 *
 * A local problem borrows `SpecProblem`'s shape so it can travel with the server's,
 * and its path is `form.<control>` — not `spec.…` — so it can never collide with one
 * the schema emits. `LOCAL_FIELD_BY_PATH` routes it; `tests/test_composer_options.py`
 * holds both halves.
 */
export function localProblems(state: SpecFormState): SpecProblem[] {
  if (state.archetype !== 'token_tray') return [];
  const problems: SpecProblem[] = [];
  for (const [field, label, raw] of [
    ['rows', 'Rows', state.rows],
    ['columns', 'Columns', state.columns],
  ] as const) {
    if (wholeCount(raw) !== null) continue;
    const typed = raw.trim();
    problems.push({
      path: `form.${field}`,
      message: typed
        ? `${label} must be a whole number of 1 or more, got '${typed}'`
        : `${label} must be a whole number of 1 or more, and this is blank`,
    });
  }
  return problems;
}

/**
 * How many cells a grid of `rows × columns` has, for the compartment list.
 *
 * **Zero when either side is not a positive whole number**, so the spec that carries a
 * grid nobody typed is one nothing will build: `localProblems` has already refused it
 * on its own control and the composer neither resolves nor submits it, and if some
 * later path sends it anyway the schema refuses an empty compartment list rather than
 * silently making a one-pocket tray of it. It used to be one cell, which is a spec that
 * looks entirely valid and is not the one that was asked for.
 */
function gridCells(rows: string, columns: string): number {
  const r = wholeCount(rows);
  const c = wholeCount(columns);
  return r === null || c === null ? 0 : r * c;
}

/**
 * The form as an organizer spec, ready for `/organizer/resolve` or `POST /jobs`.
 *
 * The archetype decides which optional section is present, and all three archetypes
 * *require* theirs: `deck_box.validate` refuses a spec with no `lid`,
 * `card_divider.validate` refuses one with no `divider` and one that carries a lid, and
 * `token_tray.validate` refuses one with no `tray` and one whose compartments hold card
 * stacks. None of those rules can run on the API server — every one of those modules
 * imports the geometry kernel — so a section left out here would not be a 422, it would
 * be a failed Phase 2 ten seconds into a run. The empty object is what carries the
 * schema's own defaults.
 *
 * The tray is also the one archetype whose *compartments* differ: it sends one pocket
 * per grid cell rather than one card stack, which is what `Compartment.contents` became
 * a union for. Identical pockets, because v1 is a regular grid — one width per column,
 * one depth per row, one height overall — and `token_tray.validate` refuses anything
 * else. Ragged layouts belong to the box-insert archetype.
 *
 * A grid that is not two positive whole numbers produces **no compartments at all**,
 * and `localProblems` is what says so on the control that caused it. See `gridCells`.
 */
export function specFromForm(state: SpecFormState): Record<string, unknown> {
  const spec: Record<string, unknown> = { archetype: state.archetype, schema_version: 1 };

  if (state.archetype === 'token_tray') {
    const columns = requiredNumber(state.columns);
    const pocket = {
      width_mm: requiredNumber(state.pocketWidthMm),
      depth_mm: requiredNumber(state.pocketDepthMm),
      height_mm: requiredNumber(state.pocketHeightMm),
    };
    spec.compartments = Array.from(
      { length: gridCells(state.rows, state.columns) },
      () => ({ contents: { ...pocket } }),
    );
    spec.tray = { columns };
    spec.process = present({ wall_mm: optionalMm(state.wallMm) });
    return spec;
  }

  spec.compartments = [
    {
      contents: {
        count: requiredNumber(state.count),
        card: state.card,
        sleeving: state.sleeving,
      },
    },
  ];

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
  'spec.tray.columns': 'columns',
  'spec.compartments[0].contents.width_mm': 'pocketWidthMm',
  'spec.compartments[0].contents.depth_mm': 'pocketDepthMm',
  'spec.compartments[0].contents.height_mm': 'pocketHeightMm',
};

/**
 * The paths only this file emits, and the control each belongs on.
 *
 * Separate from `FIELD_BY_PATH` rather than mixed into it, because the two carry
 * opposite promises: every key there is a path the *schema* really names, poked to
 * prove it, and a local key would quietly weaken that test into "one of these is
 * real". Every key here begins `form.` and no schema path ever does, so the two
 * namespaces cannot collide. See `localProblems`.
 */
export const LOCAL_FIELD_BY_PATH: Record<string, SpecField> = {
  'form.rows': 'rows',
  'form.columns': 'columns',
};

/**
 * A compartment path with its index flattened to `[0]`.
 *
 * A token tray sends one *identical* pocket per grid cell, so a blank pocket width is
 * six refusals rather than one — `spec.compartments[0].contents.width_mm` through
 * `[5]`, the same sentence six times with a different number in it. Six copies stacked
 * under one control is the sort of thing that makes people stop reading refusals, and
 * routing five of them to `form` instead would put them somewhere they are even less
 * use. So the index is dropped for both routing and de-duplication, and the six become
 * the one refusal they are.
 *
 * The card archetypes send a single compartment, so nothing about them changes.
 */
function flattenCompartment(path: string): string {
  return path.replace(/compartments\[\d+\]/, 'compartments[0]');
}

export function fieldForPath(path: string): SpecField {
  return FIELD_BY_PATH[path] ?? LOCAL_FIELD_BY_PATH[path]
    ?? FIELD_BY_PATH[flattenCompartment(path)] ?? 'form';
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

/**
 * Every problem, grouped by the control it belongs on. Nothing is discarded.
 *
 * The only thing collapsed is a repeat: a tray's identical pockets produce the same
 * sentence once per compartment, so the message is shown with its compartment index
 * flattened and the duplicates dropped. Every *distinct* refusal survives — including
 * two different ones about two different compartments, which flatten to different
 * sentences. See `flattenCompartment`.
 */
export function problemsByField(problems: SpecProblem[]): Partial<Record<SpecField, string[]>> {
  const grouped: Partial<Record<SpecField, string[]>> = {};
  const seen = new Set<string>();
  for (const problem of problems) {
    const field = fieldForPath(problem.path);
    // Every message this schema produces opens with the path it is about and nothing
    // else — `problem_path` in `pythonsrc/organizer/spec.py` is the one place that says
    // so — which is what makes replacing the prefix safe.
    const message = problem.message.replace(problem.path, flattenCompartment(problem.path));
    if (seen.has(`${field}·${message}`)) continue;
    seen.add(`${field}·${message}`);
    (grouped[field] ??= []).push(message);
  }
  return grouped;
}
