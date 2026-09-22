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

import type { FitDefaults, SpecProblem } from '../api/client';
import { EMBOSS_FACES_BY_ARCHETYPE, type ArchetypeId } from './spec';

/**
 * One editable field of one of a box insert's compartments.
 *
 * A control key with an index in it, which nothing else here has, and it is the box
 * insert that forces it: every other archetype has a *fixed* set of controls, so a
 * refusal about "the pocket" has one place to land however many compartments the spec
 * carries. An insert's compartments are each their own shape and size, so
 * `spec.compartments[2].contents.height_mm` belongs under compartment 3's own field and
 * nowhere else — flattening it to `[0]`, which is right for a tray's identical pockets,
 * would put a refusal about the dice well under the card well.
 */
export type CompartmentField =
  `compartment.${number}.${'count' | 'card' | 'sleeving' | 'widthMm' | 'depthMm' | 'heightMm'}`;

/** Every control the configurator renders, plus `form` for anything unrouted. */
export type SpecField =
  | 'archetype'
  | 'count'
  | 'card'
  | 'sleeving'
  | 'fitIntent'
  | 'wallMm'
  | 'lidClearanceMm'
  | 'cavityClearanceMm'
  | 'stackSlackMm'
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
  | 'insertRows'
  | 'boxId'
  | 'boxWidthMm'
  | 'boxDepthMm'
  | 'boxHeightMm'
  | 'embossText'
  | 'embossFace'
  | 'embossMode'
  | 'embossHeightMm'
  | 'embossReliefMm'
  | CompartmentField
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
  /**
   * The three fit fields, and **the only ones here where blank does not mean "the
   * schema's default"** — it means *the configured printer's suggestion* (issue #89).
   *
   * `POST /organizer/resolve` answers with what the profile offers, `specFromForm` puts
   * that figure in the spec when the field is blank, and anything typed here wins. So a
   * person who never opens the group gets their machine's numbers, a person who types
   * one gets theirs, and either way the spec is posted carrying explicit millimetres —
   * which is what keeps the mesh from being a function of a printer under decision (b).
   *
   * Blank rather than seeded into this state on arrival, deliberately: seeding would
   * make the suggestion a value the person then has to notice and delete, and it would
   * have to be re-seeded every time `fitIntent` changed the cavity figure underneath it.
   * Blank has neither problem and needs no "has the user touched this" flag to work.
   *
   * `lidClearanceMm` is the deck box's alone; the other two are read by the deck box and
   * the box insert — a card well is what they are about, and the tray and the divider
   * have none. `SpecForm` shows each only where it is read.
   */
  lidClearanceMm: string;
  cavityClearanceMm: string;
  stackSlackMm: string;
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
  /** Box insert only: the compartment list, and how it is grouped into rows. */
  compartments: CompartmentFormState[];
  /** `insert.rows`, as the comma-separated list a person types. */
  insertRows: string;
  /**
   * The box the part has to fit inside, and the two ways of saying which.
   *
   * `boxId` is a `GET /organizer/boxes` entry — a curated interior, three numbers with a
   * caliper or a product page behind each. Empty means the box is one nobody has
   * measured, and then the three millimetres below are it: **that is the degraded mode,
   * and it is the mode this form shipped with.** `fit_margin_mm` comes off every axis
   * either way, which is the point — a curated interior is still one copy of one box.
   *
   * All four archetypes carry these, because `spec.box` is archetype-agnostic: a deck box
   * built to stand inside a commercial card case is the same claim as an insert built to
   * fill a publisher's box, and the schema draws no distinction between them.
   */
  boxId: string;
  boxWidthMm: string;
  boxDepthMm: string;
  boxHeightMm: string;
  /**
   * The decorative tier (F13): deck box and card divider only.
   *
   * **A blank `embossText` sends no `emboss` section at all**, which is what keeps the
   * hash of an undecorated spec exactly what it was before this existed. It is the
   * blank-means-omitted rule the millimetre fields already follow, applied to the
   * section rather than to a field: an empty `emboss` object would be a section the
   * schema then refuses for having no text, on a form nobody asked to decorate.
   *
   * The text is sent **inside the spec only** — never as a second `embossing_text`
   * beside it. `POST /jobs` copies it across itself and refuses a request whose two
   * copies disagree, so one string is screened and cut; sending both from here would
   * be the browser keeping them in step, which is exactly what the server validator
   * exists so it does not have to.
   */
  embossText: string;
  embossFace: string;
  embossMode: string;
  embossHeightMm: string;
  embossReliefMm: string;
}

/**
 * One compartment of a box insert, as the form holds it.
 *
 * Both shapes' fields live on the same object and the *kind* decides which are sent —
 * rather than a discriminated union — because switching a compartment from cards to a
 * pocket and back must not throw away what was typed in the other half. The schema's own
 * union has no `kind` discriminator (adding one would have moved every stored
 * `spec_hash`), so this is the browser's word and never travels: `specFromForm` sends
 * `count`/`card`/`sleeving` **or** the three millimetres, which is exactly the narrowing
 * `_union_class` does at the other end.
 */
export interface CompartmentFormState {
  kind: 'cards' | 'pocket';
  count: string;
  card: string;
  sleeving: string;
  widthMm: string;
  depthMm: string;
  heightMm: string;
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
/** A new compartment: a pocket with nothing typed in it yet, or a Commander deck. */
export function blankCompartment(kind: 'cards' | 'pocket' = 'pocket'): CompartmentFormState {
  return {
    kind,
    count: '100',
    card: 'standard',
    sleeving: 'double',
    widthMm: '',
    depthMm: '',
    heightMm: '',
  };
}

/**
 * What a box insert opens on: `box_insert.example()`, field for field.
 *
 * Its own constant rather than an inline literal inside `DEFAULT_SPEC_FORM`, so that the
 * *shape* of the opening form stays one flat object of strings — which is what
 * `tests/test_composer_options.py` reads to hold every millimetre field to the
 * blank-means-default rule. These millimetres are exempt from that rule for
 * `REQUIRED_CONTENT_MM`'s reason, and the test that says so reads this constant by name.
 *
 * The three compartments are the acceptance spec: a 60-card double-sleeved well across
 * the front, a 40 × 40 × 15 mm token pocket and a 20 × 20 × 18 mm dice well behind it.
 * Both pocket sizes are **design examples and not sourced sizes** — nothing in the
 * dimension research gives a punchboard footprint or a die clearance — which is what the
 * fields' own note says on screen.
 */
export const DEFAULT_INSERT_COMPARTMENTS: CompartmentFormState[] = [
  { ...blankCompartment(), kind: 'cards', count: '60' },
  { ...blankCompartment(), kind: 'pocket', widthMm: '40', depthMm: '40', heightMm: '15' },
  { ...blankCompartment(), kind: 'pocket', widthMm: '20', depthMm: '20', heightMm: '18' },
];

export const DEFAULT_SPEC_FORM: SpecFormState = {
  archetype: 'deck_box',
  count: '100',
  card: 'standard',
  sleeving: 'double',
  fitIntent: 'snug',
  wallMm: '',
  lidClearanceMm: '',
  cavityClearanceMm: '',
  stackSlackMm: '',
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
  compartments: DEFAULT_INSERT_COMPARTMENTS,
  insertRows: '1, 2',
  boxId: '',
  boxWidthMm: '',
  boxDepthMm: '',
  boxHeightMm: '',
  // Blank, so the composer's first render composes the spec it always composed and the
  // decoration is something a person opts into by typing a name. The face and mode open
  // on the first entry the chosen archetype honours (`embossDefaults`), and the two
  // millimetre fields open blank, which means "take the schema's" like every other
  // process millimetre here.
  embossText: '',
  embossFace: 'lid_top',
  embossMode: 'recessed',
  embossHeightMm: '',
  embossReliefMm: '',
};

/**
 * The face and mode an archetype's lettering group opens on, or null when it letters
 * nothing.
 *
 * Read off `EMBOSS_FACES_BY_ARCHETYPE`, which is the engine's own vocabulary, rather
 * than written out again: the composer switching archetypes must not leave `lid_top`
 * selected on a card divider, which would resolve clean here and be refused by name in
 * Phase 2 — the failure the archetype strip's binding exists to prevent, one level down.
 */
export function embossDefaults(
  archetype: ArchetypeId,
): { face: string; mode: string } | null {
  const faces = EMBOSS_FACES_BY_ARCHETYPE[archetype];
  if (!faces?.length) return null;
  return { face: faces[0].face, mode: faces[0].modes[0] };
}

/** The modes a given archetype's given face honours, or [] when it letters neither. */
export function embossModesFor(archetype: string, face: string): string[] {
  return EMBOSS_FACES_BY_ARCHETYPE[archetype]?.find((f) => f.face === face)?.modes ?? [];
}

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
  if (state.archetype === 'box_insert') return insertProblems(state);
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
 * `insert.rows` as the numbers it is, or the text that was typed when it is not.
 *
 * Sent as typed rather than dropped, for `optionalMm`'s reason: the schema refuses
 * `rows` that is not a list of positive whole numbers, it names the path when it does,
 * and quoting what was typed is what tells somebody a semicolon is the problem. So the
 * *parse* is the schema's refusal and not this file's — unlike the token tray's row
 * count, which is never sent at all and therefore has nowhere else to be refused.
 */
function parseRows(raw: string): number[] | string {
  const trimmed = raw.trim();
  const entries = trimmed.split(',');
  const counts = entries.map((entry) => wholeCount(entry));
  if (!trimmed || counts.some((n) => n === null)) return trimmed;
  return counts as number[];
}

/**
 * The one refusal a box insert's form has to make itself: the rows must account for
 * every compartment.
 *
 * `box_insert.validate` is where that rule lives and it needs the geometry kernel, which
 * the API server does not install — so, exactly like `token_tray`'s column count, a
 * mismatch resolves clean, submits, and fails ten seconds into Phase 2 on a run that has
 * already written a row. The difference from the tray is what is *not* here: a badly
 * typed row entry is a path the schema names (`spec.insert.rows[1]`), so it is left to
 * the schema and routed, rather than being refused twice in two different sentences.
 *
 * The message names both numbers, because "the rows do not match" is not something a
 * person can act on and "3 compartments in rows of 1 / 1 — that is 2" is.
 */
function insertProblems(state: SpecFormState): SpecProblem[] {
  const rows = parseRows(state.insertRows);
  if (!Array.isArray(rows)) return [];
  const total = rows.reduce((sum, n) => sum + n, 0);
  if (total === state.compartments.length) return [];
  return [{
    path: 'form.insertRows',
    message:
      `Rows of ${rows.join(' / ')} account for ${total} compartments and there ` +
      `${state.compartments.length === 1 ? 'is' : 'are'} ${state.compartments.length}; ` +
      'every compartment goes in exactly one row',
  }];
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
 * The box half of the spec: `box`, or `constraints`, or neither. Never both.
 *
 * The two ways of saying which box, and they are exclusive by construction rather than
 * by a rule somebody has to remember. A named KB entry sends **only** `box` and leaves
 * the interior to the schema, which fills `constraints.max_external_mm` from the entry on
 * construction — sending both would be this file computing millimetres, which is the one
 * thing it does not do, and the schema refuses a spec whose stated limit disagrees with
 * the entry it names anyway.
 *
 * An unnamed box sends the three typed millimetres and no `box`, which is the degraded
 * mode: `fit_margin_mm` comes off every axis exactly as it does off a curated interior,
 * because a curated interior is also one copy of one box. A partly typed interior is sent
 * as it stands — `requiredNumber` makes a blank axis `null` — so the schema refuses
 * `spec.constraints.max_external_mm[1]` by name on the control that is empty, rather than
 * this file quietly dropping a limit somebody was halfway through stating.
 *
 * Nothing at all when neither is given, which is the behaviour every spec this form has
 * ever composed had: no limit, and no fit comparison to fail.
 */
function boxFromForm(state: SpecFormState): Record<string, unknown> {
  const id = state.boxId.trim();
  if (id) return { box: { id } };
  const typed = [state.boxWidthMm, state.boxDepthMm, state.boxHeightMm];
  if (!typed.some((raw) => raw.trim())) return {};
  return { constraints: { max_external_mm: typed.map(requiredNumber) } };
}

/**
 * The form as an organizer spec, ready for `/organizer/resolve` or `POST /jobs`.
 *
 * The archetype decides which optional section is present, and all four archetypes
 * *require* theirs: `deck_box.validate` refuses a spec with no `lid`,
 * `card_divider.validate` refuses one with no `divider` and one that carries a lid,
 * `token_tray.validate` refuses one with no `tray` and one whose compartments hold card
 * stacks, and `box_insert.validate` refuses one with no `insert` and one whose `rows` do
 * not sum to the compartment list. None of those rules can run on the API server — every
 * one of those modules imports the geometry kernel — so a section left out here would not
 * be a 422, it would be a failed Phase 2 ten seconds into a run. The empty object is what
 * carries the schema's own defaults.
 *
 * Two archetypes also send *compartments* that are not one card stack. The tray sends one
 * pocket per grid cell, which is what `Compartment.contents` became a union for —
 * identical pockets, because v1 is a regular grid (one width per column, one depth per
 * row, one height overall) and `token_tray.validate` refuses anything else. The box
 * insert sends a list whose entries are each their own shape, card stack or pocket, which
 * is the ragged layout the tray deferred to it.
 *
 * A grid that is not two positive whole numbers produces **no compartments at all**,
 * and `localProblems` is what says so on the control that caused it. See `gridCells`.
 */
export function specFromForm(
  state: SpecFormState,
  fit: FitDefaults | null = null,
): Record<string, unknown> {
  const spec: Record<string, unknown> = { archetype: state.archetype, schema_version: 1 };
  Object.assign(spec, boxFromForm(state));

  if (state.archetype === 'box_insert') {
    // The one archetype whose compartments are each their own shape, so each is sent as
    // whichever half of the union it is — `count`/`card`/`sleeving` or the three
    // millimetres, never both, which is what `_union_class` refuses at the other end.
    // `fit_intent` rides along because a card well's clearance is chosen by it; a spec
    // with no card compartment carries it and builds nothing from it, which is the
    // "process fields this archetype does not read still hash" rule every module states.
    spec.compartments = state.compartments.map((compartment) => ({
      contents: compartment.kind === 'cards'
        ? {
            count: requiredNumber(compartment.count),
            card: compartment.card,
            sleeving: compartment.sleeving,
          }
        : {
            width_mm: requiredNumber(compartment.widthMm),
            depth_mm: requiredNumber(compartment.depthMm),
            height_mm: requiredNumber(compartment.heightMm),
          },
    }));
    spec.insert = { rows: parseRows(state.insertRows) };
    spec.process = present({
      fit_intent: state.fitIntent,
      wall_mm: optionalMm(state.wallMm),
      ...cardWellFit(state, fit),
    });
    return spec;
  }

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
    spec.lid = present({
      kind: 'lift_off',
      height_mm: optionalMm(state.lidHeightMm),
      clearance_mm: offeredMm(state.lidClearanceMm, fit?.lid_clearance_mm),
    });
    spec.process = present({
      fit_intent: state.fitIntent,
      wall_mm: optionalMm(state.wallMm),
      ...cardWellFit(state, fit),
    });
  } else {
    spec.divider = present({
      tab_position: state.tabPosition,
      thickness_mm: optionalMm(state.thicknessMm),
      tab_width_mm: optionalMm(state.tabWidthMm),
      tab_height_mm: optionalMm(state.tabHeightMm),
    });
  }
  const emboss = embossSection(state);
  if (emboss) spec.emboss = emboss;

  return spec;
}

/**
 * The two card-well fit fields, as the archetypes that read one take them.
 *
 * The deck box and the box insert both size a well as the sleeve envelope plus
 * `cavity_clearance_mm` and the stack plus `stack_slack_mm`; the tray and the divider
 * read neither, so neither is sent for them and no spec hash of theirs moves.
 */
function cardWellFit(
  state: SpecFormState,
  fit: FitDefaults | null,
): Record<string, unknown> {
  return {
    cavity_clearance_mm: offeredMm(state.cavityClearanceMm, fit?.cavity_clearance_mm),
    stack_slack_mm: offeredMm(state.stackSlackMm, fit?.stack_slack_mm),
  };
}

/**
 * A fit millimetre: what was typed, else what the printer offered, else omitted.
 *
 * `optionalMm`'s rule with one step inserted, and the step is the whole of issue #89 on
 * this side. Blank means "I have no opinion", and the thing with an opinion is the
 * printer — `POST /organizer/resolve` resolved its figure against the profile's sourced
 * class and against this spec's own fit intent, so what arrives here is a number to
 * send, never two numbers to add up. **No arithmetic happens in this file**, which is
 * the rule the whole composer is built on.
 *
 * Omitted when there is no offer either, and that is the degraded mode working rather
 * than a gap: a resolve that has not answered yet, or a server that cannot be reached,
 * leaves the schema to resolve its own defaults exactly as it did before #89. A browser
 * inventing 0,2 mm to fill the hole would be the one number here with nothing behind it.
 */
function offeredMm(raw: string, offered: number | undefined): number | string | undefined {
  const typed = optionalMm(raw);
  return typed !== undefined ? typed : offered;
}

/**
 * The `emboss` section, or null when nothing is to be lettered.
 *
 * Null for a blank text and for an archetype that letters nothing, and both are the
 * same rule: **an absent section is omitted, never sent as an empty object**. That is
 * what keeps an undecorated spec's canonical form — and therefore its `spec_hash` —
 * exactly what it was before this feature existed, which is the property
 * `_OPTIONAL_SECTIONS` in `pythonsrc/organizer/spec.py` exists to guarantee and the one
 * a browser is most able to break.
 *
 * The text is sent **trimmed of nothing**: the schema strips it, and stripping here too
 * would mean two places deciding what the canonical string is. The two millimetres go
 * through `optionalMm`, so blank means "take the schema's default" exactly as it does
 * for a wall.
 */
function embossSection(state: SpecFormState): Record<string, unknown> | null {
  if (!state.embossText.trim()) return null;
  if (!EMBOSS_FACES_BY_ARCHETYPE[state.archetype]?.length) return null;
  return present({
    text: state.embossText,
    face: state.embossFace,
    mode: state.embossMode,
    height_mm: optionalMm(state.embossHeightMm),
    relief_mm: optionalMm(state.embossReliefMm),
  });
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
  'spec.lid.clearance_mm': 'lidClearanceMm',
  'spec.process.cavity_clearance_mm': 'cavityClearanceMm',
  'spec.process.stack_slack_mm': 'stackSlackMm',
  'spec.lid.height_mm': 'lidHeightMm',
  'spec.divider.thickness_mm': 'thicknessMm',
  'spec.divider.tab_width_mm': 'tabWidthMm',
  'spec.divider.tab_height_mm': 'tabHeightMm',
  'spec.divider.tab_position': 'tabPosition',
  'spec.tray.columns': 'columns',
  'spec.insert.rows': 'insertRows',
  'spec.compartments[0].contents.width_mm': 'pocketWidthMm',
  'spec.compartments[0].contents.depth_mm': 'pocketDepthMm',
  'spec.compartments[0].contents.height_mm': 'pocketHeightMm',
  'spec.box.id': 'boxId',
  // Per axis, not flattened, and that is the opposite of what a tray's identical pockets
  // want: these three are three different controls holding three different numbers, so a
  // refusal about the depth belongs under the depth. See `flattenCompartment` for the
  // case that goes the other way, and why each is right for the control it is about.
  'spec.constraints.max_external_mm[0]': 'boxWidthMm',
  'spec.constraints.max_external_mm[1]': 'boxDepthMm',
  'spec.constraints.max_external_mm[2]': 'boxHeightMm',
  'spec.emboss.text': 'embossText',
  'spec.emboss.face': 'embossFace',
  'spec.emboss.mode': 'embossMode',
  'spec.emboss.height_mm': 'embossHeightMm',
  'spec.emboss.relief_mm': 'embossReliefMm',
};

/**
 * Which compartment control a `contents` field belongs to, for a box insert.
 *
 * Keyed on the schema's own field name rather than on a dotted path, because the path
 * carries the index and the index is the control: `spec.compartments[2].contents.count`
 * is compartment 3's card count and nothing else's. The two card fields a compartment
 * does not edit are absent by construction — a pocket sends no `count` — so the schema
 * cannot name one that has nowhere to land.
 */
type CompartmentFieldName = 'count' | 'card' | 'sleeving' | 'widthMm' | 'depthMm' | 'heightMm';

export const COMPARTMENT_FIELD_BY_KEY: Record<string, CompartmentFieldName> = {
  count: 'count',
  card: 'card',
  sleeving: 'sleeving',
  width_mm: 'widthMm',
  depth_mm: 'depthMm',
  height_mm: 'heightMm',
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
  'form.insertRows': 'insertRows',
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

/**
 * The compartment control a path names, for a box insert, or null.
 *
 * The **opposite** of `flattenCompartment`, and both are right for the archetype they
 * are about: a tray's compartments are identical, so one refusal belongs under one
 * control and five copies of it are noise; an insert's are each their own shape, so the
 * index is the only thing that says which one is wrong. Sending the dice well's refusal
 * to the card well would be worse than dropping it, because it looks answered.
 */
function compartmentField(path: string): CompartmentField | null {
  const match = /^spec\.compartments\[(\d+)\]\.contents\.(\w+)$/.exec(path);
  if (!match) return null;
  const name = COMPARTMENT_FIELD_BY_KEY[match[2]];
  return name ? (`compartment.${Number(match[1])}.${name}` as CompartmentField) : null;
}

/**
 * Which control a dotted problem path belongs on, in this archetype's layout.
 *
 * The archetype is an argument because one path routes two ways: a box insert wants
 * `spec.compartments[2]…` on compartment 3's own control and every other archetype wants
 * it flattened onto the one pocket control. It is optional so that a caller with no
 * archetype in hand keeps the behaviour this function always had.
 */
export function fieldForPath(path: string, archetype?: ArchetypeId): SpecField {
  if (archetype === 'box_insert') {
    const compartment = compartmentField(path);
    if (compartment) return compartment;
  }
  return FIELD_BY_PATH[path] ?? LOCAL_FIELD_BY_PATH[path]
    ?? FIELD_BY_PATH[stripIndices(path)] ?? 'form';
}

/**
 * A path with its list indices flattened: `compartments[3]` → `[0]`, `rows[1]` → `rows`.
 *
 * Two lists, two different flattenings, and both are one rule: *route a refusal to the
 * control that carries the value*. Six identical pockets share one control, so their
 * index goes to `[0]`; every entry of `insert.rows` is typed into the same comma-separated
 * field, so its index goes away entirely.
 */
function stripIndices(path: string): string {
  return flattenCompartment(path).replace(/\.rows\[\d+\]$/, '.rows');
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
export function problemsByField(
  problems: SpecProblem[], archetype?: ArchetypeId,
): Partial<Record<SpecField, string[]>> {
  const grouped: Partial<Record<SpecField, string[]>> = {};
  const seen = new Set<string>();
  for (const problem of problems) {
    const field = fieldForPath(problem.path, archetype);
    // Every message this schema produces opens with the path it is about and nothing
    // else — `problem_path` in `pythonsrc/organizer/spec.py` is the one place that says
    // so — which is what makes replacing the prefix safe. An insert keeps its indices:
    // the message is going under the compartment it names, so erasing which one it is
    // would strip the one word that makes it findable.
    const message = archetype === 'box_insert' && compartmentField(problem.path)
      ? problem.message
      : problem.message.replace(problem.path, stripIndices(problem.path));
    if (seen.has(`${field}·${message}`)) continue;
    seen.add(`${field}·${message}`);
    (grouped[field] ??= []).push(message);
  }
  return grouped;
}
