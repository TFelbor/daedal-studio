import { AlertTriangle, Ruler } from 'lucide-react';
import { Blueprint } from './Blueprint';
import {
  CARD_KINDS,
  EMBOSS_FACES_BY_ARCHETYPE,
  EMBOSS_FACE_LABELS,
  EMBOSS_MODE_LABELS,
  EMBOSS_TEXT_MAX_CHARS,
  FIT_INTENTS,
  FIT_INTENT_LABELS,
  LID_KINDS,
  SLEEVINGS,
  SLEEVING_NOTE,
  TAB_POSITIONS,
} from '../organizer/spec';
import {
  blankCompartment,
  embossModesFor,
  problemsByField,
  type CompartmentFormState,
  type SpecField,
  type SpecFormState,
} from '../organizer/specForm';
import type { GameBoxEntry, ResolvedStack, SpecProblem } from '../api/client';
import styles from './SpecForm.module.css';

interface SpecFormProps {
  state: SpecFormState;
  onChange: (next: SpecFormState) => void;
  /** Every problem the server named, from the live resolve or from a refused submit. */
  problems: SpecProblem[];
  /** The stacks `POST /organizer/resolve` computed, or none while it has not answered. */
  stacks: ResolvedStack[];
  /**
   * The curated box interiors from `GET /organizer/boxes`, or none.
   *
   * Empty is a legitimate state and not an error: the list is data, a fetch can fail, and
   * the form degrades to exactly the path a box nobody has measured takes anyway. It is
   * a prop rather than a fetch inside this component so the composer owns every request
   * it makes, as it does for the resolve.
   */
  boxes?: GameBoxEntry[];
  /** True between a change and the server's answer, so the readout can say it is stale. */
  resolving?: boolean;
  /**
   * True when the last resolve did not come back — a transport failure, not a refusal.
   *
   * The two used to look identical here: `stacks` empty and no problem on any control,
   * which the readout reported as *fix the fields above*. Telling someone their input
   * is wrong because a request failed is the worst answer available, because it is the
   * one they will act on.
   */
  unreachable?: boolean;
  disabled?: boolean;
}

/**
 * The refusals for one control, under it, in the failure treatment.
 *
 * Module level rather than a closure inside `SpecForm`: a component declared during
 * render is a new component type on every render, so React tears the old one down and
 * remounts it, and an input inside one would lose focus on every keystroke.
 */
function FieldProblems({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null;
  return (
    <ul className={styles.problems} role="alert">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

/**
 * The configurator: a spec, composed by hand, one field at a time.
 *
 * The alpha's way in. The redesigned composer promised "your words become a spec" and
 * then had no path from a person to one — the archetype strip reported its choice to
 * telemetry and sent it nowhere, and the only way to run a spec job was the CLI. This
 * is the form half of that (roadmap §5A cut #3); extraction from a prompt is a later
 * issue, and the rule that keeps them apart is the one the whole pivot turns on: the
 * LLM interprets words, it never produces geometry.
 *
 * Three properties, and each of them is a refusal:
 *
 * **Nothing is offered that the engine cannot compile.** Every vocabulary here —
 * sleevings, fit intents, tab positions — is a literal bound to its Python
 * counterpart by `tests/test_composer_options.py`. The strip offered three archetypes
 * that did not exist once; that is the failure being designed out, not a hypothetical.
 *
 * **Nothing is computed here.** The card footprint, the stack height and the basis
 * come from `POST /organizer/resolve`, which runs the same dimension table the
 * geometry is built from. A millimetre field left blank is sent as *absent*, so the
 * spec panel shows the archetype's own default rather than a copy of it hardcoded in
 * a browser.
 *
 * **Nothing that is wrong is hidden.** Every refusal lands on the control it names,
 * and anything the mapping does not recognise is shown whole above the form.
 */
export function SpecForm({
  state,
  onChange,
  problems,
  stacks,
  boxes = [],
  resolving = false,
  unreachable = false,
  disabled = false,
}: SpecFormProps) {
  const byField = problemsByField(problems, state.archetype);
  const set = (patch: Partial<SpecFormState>) => onChange({ ...state, ...patch });
  const isDeckBox = state.archetype === 'deck_box';
  const isTray = state.archetype === 'token_tray';
  const isInsert = state.archetype === 'box_insert';

  const setCompartment = (index: number, patch: Partial<CompartmentFormState>) =>
    set({
      compartments: state.compartments.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });

  return (
    <div className={styles.form}>
      {/* Anything the field mapping did not recognise. Shown rather than swallowed:
          a refusal nobody can see is a submit button that silently stops working. */}
      {/* A request that never landed is not a refusal, and it does not belong under a
          control: nothing the person typed caused it and nothing they type fixes it. */}
      {unreachable ? (
        <div className={`notice ${styles.formProblems}`} role="status">
          <AlertTriangle size={15} strokeWidth={1.5} aria-hidden="true" />
          <span>
            <span className={styles.formProblem}>
              Could not reach the server to check this spec. The fields below are not
              the problem; the figures will fill in when it answers again.
            </span>
          </span>
        </div>
      ) : null}

      {byField.form?.length ? (
        <div className={`notice ${styles.formProblems}`} role="alert">
          <AlertTriangle size={15} strokeWidth={1.5} aria-hidden="true" />
          <span>
            {byField.form.map((message) => (
              <span key={message} className={styles.formProblem}>{message}</span>
            ))}
          </span>
        </div>
      ) : null}

      {/* The box insert is the one archetype whose compartments are each their own
          shape, so its contents are a *list* rather than a fixed set of controls: add a
          card well or a pocket, remove one, and say which row each belongs to. The list
          is above the grid rather than in it because each entry is several controls that
          have to read as one compartment — and because a refusal about compartment 3
          needs a compartment 3 on screen to sit under. */}
      {isInsert ? (
        <>
          <div className={styles.compartments}>
            {state.compartments.map((compartment, index) => (
              <CompartmentEditor
                key={index}
                index={index}
                state={compartment}
                byField={byField}
                disabled={disabled}
                removable={state.compartments.length > 1}
                onChange={(patch) => setCompartment(index, patch)}
                onRemove={() =>
                  set({ compartments: state.compartments.filter((_, i) => i !== index) })
                }
              />
            ))}
          </div>

          <div className={styles.compartmentTools}>
            <button
              type="button"
              className="btn"
              disabled={disabled}
              onClick={() =>
                set({ compartments: [...state.compartments, blankCompartment('cards')] })
              }
            >
              Add a card well
            </button>
            <button
              type="button"
              className="btn"
              disabled={disabled}
              onClick={() =>
                set({ compartments: [...state.compartments, blankCompartment()] })
              }
            >
              Add a pocket
            </button>
          </div>
        </>
      ) : null}

      <div className={styles.grid}>
        {isInsert ? (
          <>
            <label className={styles.field}>
              <span className="label-tight">Rows</span>
              <input
                className="input"
                type="text"
                inputMode="numeric"
                placeholder="e.g. 1, 2"
                value={state.insertRows}
                disabled={disabled}
                onChange={(e) => set({ insertRows: e.target.value })}
              />
              <span className={styles.fieldNote}>
                how many compartments in each row, front to back; they fill it in the
                order above
              </span>
              {/* Two sources, one control. A badly typed entry is `spec.insert.rows[1]`,
                  which the schema names and routes here; that the counts *add up to the
                  compartment list* is `box_insert.validate`'s rule, which needs the
                  geometry kernel the API server does not install — so the browser makes
                  that one itself. See `localProblems`. */}
              <FieldProblems messages={byField.insertRows} />
            </label>

            <div className={styles.field}>
              <span className="label-tight">Fit</span>
              <div className={`seg ${styles.intentSeg}`} role="group" aria-label="Fit intent">
                {FIT_INTENTS.map((intent) => (
                  <button
                    key={intent}
                    type="button"
                    disabled={disabled}
                    aria-pressed={state.fitIntent === intent}
                    className={state.fitIntent === intent ? 'is-active' : undefined}
                    onClick={() => set({ fitIntent: intent })}
                  >
                    {FIT_INTENT_LABELS[intent] ?? intent}
                  </button>
                ))}
              </div>
              <span className={styles.fieldNote}>
                how much room a card well gets around the deck; a pocket is the
                millimetres you typed and this does not touch it
              </span>
              <FieldProblems messages={byField.fitIntent} />
            </div>

            <label className={styles.field}>
              <span className="label-tight">Wall</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the archetype’s own"
                value={state.wallMm}
                disabled={disabled}
                onChange={(e) => set({ wallMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                the minimum: a row narrower than the widest shares the difference equally
                over its own walls, so those come out thicker
              </span>
              <FieldProblems messages={byField.wallMm} />
            </label>
          </>
        ) : null}

        {/* A tray holds pockets, not cards, so the two card controls are not merely
            ignored for it — they are absent. `specFromForm` sends no card stack for a
            token tray either, and a control that sends nothing is a control that
            cannot be refused, which is worse than one that is not there. An insert has
            these controls too, but per compartment rather than once — they are in the
            list above, where the compartment they belong to is. */}
        {isTray || isInsert ? null : (
          <>
            <label className={styles.field}>
              <span className="label-tight">Cards</span>
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={state.count}
                disabled={disabled}
                onChange={(e) => set({ count: e.target.value })}
              />
              {/* One card kind, and it says which rather than offering a dead select:
                  the Japanese size has no sourced sleeve envelope, and inventing a
                  footprint for it is the fabricated number this engine refuses. */}
              <span className={styles.fieldNote}>{CARD_KINDS[0]} size — 63,5 × 88,9 mm</span>
              <FieldProblems messages={byField.count} />
              <FieldProblems messages={byField.card} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Sleeves</span>
              <select
                className="input"
                value={state.sleeving}
                disabled={disabled}
                onChange={(e) => set({ sleeving: e.target.value })}
              >
                {SLEEVINGS.map((sleeving) => (
                  <option key={sleeving} value={sleeving}>
                    {SLEEVING_NOTE[sleeving] ?? sleeving}
                  </option>
                ))}
              </select>
              <span className={styles.fieldNote}>decides the envelope and the pitch per card</span>
              <FieldProblems messages={byField.sleeving} />
            </label>
          </>
        )}

        {isInsert ? null : isTray ? (
          <>
            <label className={styles.field}>
              <span className="label-tight">Rows</span>
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={state.rows}
                disabled={disabled}
                onChange={(e) => set({ rows: e.target.value })}
              />
              <span className={styles.fieldNote}>
                one compartment per cell; the grid is regular in v1
              </span>
              {/* The one control whose refusals are the browser's own. `rows` is never
                  sent — `Tray` carries `columns`, and the schema derives the rows from
                  the compartment count — so no 422 can ever name it, and without
                  `localProblems` a blank or fractional entry became one compartment in
                  silence. See `specForm.ts`. */}
              <FieldProblems messages={byField.rows} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Columns</span>
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={state.columns}
                disabled={disabled}
                onChange={(e) => set({ columns: e.target.value })}
              />
              <span className={styles.fieldNote}>square pockets, square corners — no fillets yet</span>
              <FieldProblems messages={byField.columns} />
            </label>

            {/* The three pocket dimensions are the *input*, not a default: no token or
                dice size is sourced anywhere in the dimension research, so there is no
                table to resolve them against and a preset would be a sourced size plus
                an invented clearance. They open on the example's figures and say so. */}
            <label className={styles.field}>
              <span className="label-tight">Pocket width</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.pocketWidthMm}
                disabled={disabled}
                onChange={(e) => set({ pocketWidthMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                internal, per pocket; no token or dice size is sourced, so this is yours
              </span>
              <FieldProblems messages={byField.pocketWidthMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Pocket depth</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.pocketDepthMm}
                disabled={disabled}
                onChange={(e) => set({ pocketDepthMm: e.target.value })}
              />
              <span className={styles.fieldNote}>internal, front to back</span>
              <FieldProblems messages={byField.pocketDepthMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Pocket depth (Z)</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.pocketHeightMm}
                disabled={disabled}
                onChange={(e) => set({ pocketHeightMm: e.target.value })}
              />
              <span className={styles.fieldNote}>how deep the hole is, above the floor</span>
              <FieldProblems messages={byField.pocketHeightMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Wall</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the archetype’s own"
                value={state.wallMm}
                disabled={disabled}
                onChange={(e) => set({ wallMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                the outer walls and every divider; thinner than three extrusion widths is
                refused by the compiler
              </span>
              <FieldProblems messages={byField.wallMm} />
            </label>
          </>
        ) : isDeckBox ? (
          <>
            <div className={styles.field}>
              <span className="label-tight">Fit</span>
              <div className={`seg ${styles.intentSeg}`} role="group" aria-label="Fit intent">
                {FIT_INTENTS.map((intent) => (
                  <button
                    key={intent}
                    type="button"
                    disabled={disabled}
                    aria-pressed={state.fitIntent === intent}
                    className={state.fitIntent === intent ? 'is-active' : undefined}
                    onClick={() => set({ fitIntent: intent })}
                  >
                    {FIT_INTENT_LABELS[intent] ?? intent}
                  </button>
                ))}
              </div>
              {/* The millimetres are deliberately not named here — they are the
                  schema's, and they arrive on the resolved spec below. */}
              <span className={styles.fieldNote}>
                how much room the cards get; the clearance it chooses is in the spec below
              </span>
              <FieldProblems messages={byField.fitIntent} />
            </div>

            <label className={styles.field}>
              <span className="label-tight">Wall</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the archetype’s own"
                value={state.wallMm}
                disabled={disabled}
                onChange={(e) => set({ wallMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                thinner than three extrusion widths is refused by the compiler
              </span>
              <FieldProblems messages={byField.wallMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Lid engagement</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the default"
                value={state.lidHeightMm}
                disabled={disabled}
                onChange={(e) => set({ lidHeightMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                how far the {LID_KINDS[0].replace('_', '-')} lid covers the body’s lip; it is the
                only closure this archetype builds
              </span>
              <FieldProblems messages={byField.lidHeightMm} />
            </label>
          </>
        ) : (
          <>
            <label className={styles.field}>
              <span className="label-tight">Tab position</span>
              <select
                className="input"
                value={state.tabPosition}
                disabled={disabled}
                onChange={(e) => set({ tabPosition: e.target.value })}
              >
                {TAB_POSITIONS.map((position) => (
                  <option key={position} value={position}>{position}</option>
                ))}
              </select>
              <span className={styles.fieldNote}>where the label tab sits on the top edge</span>
              <FieldProblems messages={byField.tabPosition} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Plate thickness</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the default"
                value={state.thicknessMm}
                disabled={disabled}
                onChange={(e) => set({ thicknessMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                1,2–1,6 mm insert band; one practitioner’s practice, not a standard
              </span>
              <FieldProblems messages={byField.thicknessMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Tab width</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the default"
                value={state.tabWidthMm}
                disabled={disabled}
                onChange={(e) => set({ tabWidthMm: e.target.value })}
              />
              <span className={styles.fieldNote}>design default, unsourced; narrower than the plate</span>
              <FieldProblems messages={byField.tabWidthMm} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Tab height</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm — blank for the default"
                value={state.tabHeightMm}
                disabled={disabled}
                onChange={(e) => set({ tabHeightMm: e.target.value })}
              />
              <span className={styles.fieldNote}>how far the tab stands proud of the cards</span>
              <FieldProblems messages={byField.tabHeightMm} />
            </label>
          </>
        )}
      </div>

      <BoxPicker
        state={state}
        boxes={boxes}
        byField={byField}
        disabled={disabled}
        onChange={set}
      />

      <Lettering state={state} byField={byField} disabled={disabled} set={set} />

      <FieldProblems messages={byField.archetype} />

      <StackReadout
        stacks={stacks}
        resolving={resolving}
        unreachable={unreachable}
        expectsStack={
          isInsert ? state.compartments.some((c) => c.kind === 'cards') : !isTray
        }
      />
    </div>
  );
}

/**
 * The box the part has to fit inside: a curated interior, or three typed millimetres.
 *
 * The "Interior-First" input the board-gamer segment is founded on (issue #154). An
 * insert compiled against a box nobody measured is the failure mode the whole practice is
 * about, and until the dimension KB existed this field could only be typed.
 *
 * **Both halves are always reachable, and the degraded one is not a lesser state.** The
 * KB is three curated boxes today and will never be every box that exists; a game not in
 * it is the ordinary case, not an error, so the typed fields are right there and the
 * refusal for a box nobody has measured is *no refusal at all*. `constraints.fit_margin_mm`
 * comes off every axis either way, because a curated interior is also one copy of one box
 * measured once, and boxes flare ±1–2 mm between copies.
 *
 * **Which of the two was used is said on screen, in both directions.** Pick an entry and
 * its three provenance sentences appear — a source and a capture date, checkable against
 * the page they were transcribed from. Type the millimetres and the note says they are
 * typed. Two numbers that look identical in a table and are not the same kind of claim is
 * precisely the habit this product exists to break, and the KB is worth nothing if the
 * screen cannot tell them apart.
 *
 * **No millimetre here is computed in the browser.** The interior of a curated entry comes
 * off `GET /organizer/boxes` and is shown as the server sent it; the spec sends the id
 * alone and the schema fills the limit. An empty list — the fetch failed, or is still in
 * flight — degrades to the typed fields and says so, which is the same shape of answer the
 * stack readout gives for an unreachable server.
 */
function BoxPicker({
  state,
  boxes,
  byField,
  disabled,
  onChange,
}: {
  state: SpecFormState;
  boxes: GameBoxEntry[];
  byField: Partial<Record<SpecField, string[]>>;
  disabled: boolean;
  onChange: (patch: Partial<SpecFormState>) => void;
}) {
  const chosen = boxes.find((box) => box.id === state.boxId) ?? null;
  const typed = !state.boxId;

  return (
    <div className={styles.box}>
      <label className={styles.field}>
        <span className="label-tight">Box it has to fit</span>
        <select
          className="input"
          value={state.boxId}
          disabled={disabled}
          onChange={(e) => onChange({ boxId: e.target.value })}
        >
          <option value="">A box nobody has measured — I’ll type the interior</option>
          {boxes.map((box) => (
            <option key={box.id} value={box.id}>
              {box.name}
              {box.publisher ? ` · ${box.publisher}` : ''}
            </option>
          ))}
        </select>
        <span className={styles.fieldNote}>
          {boxes.length
            ? 'the dimension KB carries a few curated interiors; anything else is typed'
            : 'the curated list could not be loaded, so the interior is typed — which is the same path a box nobody has measured takes'}
        </span>
        <FieldProblems messages={byField.boxId} />
      </label>

      {chosen ? (
        <div className={styles.boxProvenance}>
          <p className={styles.boxInterior}>
            <Ruler size={14} strokeWidth={1.5} aria-hidden="true" />
            <span>
              Interior {chosen.interior_mm.map((mm) => `${mm}`).join(' × ')} mm, from the
              dimension KB. The fit margin still comes off every axis: a curated interior is
              one copy of one box, and boxes vary ±1–2 mm between copies.
            </span>
          </p>
          {/* One sentence per axis rather than one for the box, because provenance in
              this project is per value: a width off a caliper and a height off a product
              page are two different claims. */}
          <dl className={styles.boxSources}>
            {(['width', 'depth', 'height'] as const).map((axis) => (
              <div key={axis}>
                <dt>{axis}</dt>
                <dd>{chosen.provenance[axis] ?? 'no source recorded'}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {/* Spelled out rather than mapped over a list of three, like every other control
          in this form: `byField.boxWidthMm` has to be readable in the source, because
          `tests/test_composer_options.py` reads it to prove every routed refusal has a
          control to land on — and a dynamic `byField[field]` is exactly the kind of
          indirection that passes a reviewer and fails that promise silently. */}
      {typed ? (
        <div className={styles.grid}>
          <label className={styles.field}>
            <span className="label-tight">Interior width</span>
            <input
              className="input"
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="mm — blank for no limit at all"
              value={state.boxWidthMm}
              disabled={disabled}
              onChange={(e) => onChange({ boxWidthMm: e.target.value })}
            />
            <span className={styles.fieldNote}>
              measured off your own copy; the fit margin comes off every axis before
              anything is compared
            </span>
            <FieldProblems messages={byField.boxWidthMm} />
          </label>

          <label className={styles.field}>
            <span className="label-tight">Interior depth</span>
            <input
              className="input"
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="mm — blank for no limit at all"
              value={state.boxDepthMm}
              disabled={disabled}
              onChange={(e) => onChange({ boxDepthMm: e.target.value })}
            />
            <span className={styles.fieldNote}>typed — no source behind this number</span>
            <FieldProblems messages={byField.boxDepthMm} />
          </label>

          <label className={styles.field}>
            <span className="label-tight">Interior height</span>
            <input
              className="input"
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="mm — blank for no limit at all"
              value={state.boxHeightMm}
              disabled={disabled}
              onChange={(e) => onChange({ boxHeightMm: e.target.value })}
            />
            <span className={styles.fieldNote}>typed — no source behind this number</span>
            <FieldProblems messages={byField.boxHeightMm} />
          </label>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The decorative tier (F13): a name raised on, or sunk into, one face of the part.
 *
 * **Shown only for the archetypes that letter something**, which is
 * `EMBOSS_FACES_BY_ARCHETYPE` and not a list written out again here: a token tray and a
 * box insert build no lettered face, so they get no group at all rather than a group
 * whose every option is refused. Same rule as the archetype strip, one level down.
 *
 * **The face select drives the mode select**, for the same reason: only the card
 * divider's tab takes `raised` — every deck box face is either against the build plate
 * or vertical — so changing the face re-picks the mode when the one that was chosen is
 * not available on the new one. Leaving a stale `raised` selected would resolve clean
 * and be refused by name in Phase 2, which is precisely the failure this whole file is
 * built to avoid.
 *
 * Module level for `FieldProblems`' reason — a component declared during render remounts
 * on every keystroke and the input loses focus.
 *
 * **No millimetre of the lettering is computed here.** How wide `"Commander"` sets at a
 * 6 mm cap height is a function of the vendored font's metrics, and the answer comes
 * back from `POST /organizer/resolve`, measured by the same code that cuts the glyphs.
 * What this group does is collect five fields and send them.
 */
function Lettering({
  state,
  byField,
  disabled,
  set,
}: {
  state: SpecFormState;
  byField: Partial<Record<SpecField, string[]>>;
  disabled: boolean;
  set: (patch: Partial<SpecFormState>) => void;
}) {
  const faces = EMBOSS_FACES_BY_ARCHETYPE[state.archetype];
  if (!faces?.length) return null;
  const modes = embossModesFor(state.archetype, state.embossFace);

  const pickFace = (face: string) => {
    const available = embossModesFor(state.archetype, face);
    set({
      embossFace: face,
      embossMode: available.includes(state.embossMode) ? state.embossMode : available[0],
    });
  };

  return (
    <div className={styles.grid}>
      <label className={styles.field}>
        <span className="label-tight">Lettering</span>
        <input
          className="input"
          type="text"
          maxLength={EMBOSS_TEXT_MAX_CHARS}
          placeholder="leave blank for no lettering"
          value={state.embossText}
          disabled={disabled}
          onChange={(e) => set({ embossText: e.target.value })}
        />
        <span className={styles.fieldNote}>
          cut into the part itself, so it is screened like the prompt; blank composes the
          spec exactly as it was before
        </span>
        <FieldProblems messages={byField.embossText} />
      </label>

      {state.embossText.trim() ? (
        <>
          <label className={styles.field}>
            <span className="label-tight">Face</span>
            <select
              className="input"
              value={state.embossFace}
              disabled={disabled}
              onChange={(e) => pickFace(e.target.value)}
            >
              {faces.map(({ face }) => (
                <option key={face} value={face}>{EMBOSS_FACE_LABELS[face] ?? face}</option>
              ))}
            </select>
            <span className={styles.fieldNote}>
              the compiler refuses text that does not fit, and names the size that would
            </span>
            <FieldProblems messages={byField.embossFace} />
          </label>

          <label className={styles.field}>
            <span className="label-tight">Relief</span>
            <select
              className="input"
              value={state.embossMode}
              disabled={disabled || modes.length < 2}
              onChange={(e) => set({ embossMode: e.target.value })}
            >
              {modes.map((mode) => (
                <option key={mode} value={mode}>{EMBOSS_MODE_LABELS[mode] ?? mode}</option>
              ))}
            </select>
            <span className={styles.fieldNote}>
              {modes.length < 2
                ? 'this face prints face-down or vertical, so the text is sunk into it — raised would need support'
                : 'the tab is the only face that points up as it prints, so it takes either'}
            </span>
            <FieldProblems messages={byField.embossMode} />
          </label>

          <label className={styles.field}>
            <span className="label-tight">Letter height</span>
            <input
              className="input"
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="mm — blank for the default"
              value={state.embossHeightMm}
              disabled={disabled}
              onChange={(e) => set({ embossHeightMm: e.target.value })}
            />
            <span className={styles.fieldNote}>
              cap height; smaller letters have thinner strokes, and the compiler refuses a
              stroke the nozzle cannot lay
            </span>
            <FieldProblems messages={byField.embossHeightMm} />
          </label>

          <label className={styles.field}>
            <span className="label-tight">Relief depth</span>
            <input
              className="input"
              type="number"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="mm — blank for the default"
              value={state.embossReliefMm}
              disabled={disabled}
              onChange={(e) => set({ embossReliefMm: e.target.value })}
            />
            <span className={styles.fieldNote}>
              design default, unsourced — three 0,2 mm layers
            </span>
            <FieldProblems messages={byField.embossReliefMm} />
          </label>
        </>
      ) : null}
    </div>
  );
}

/**
 * One compartment of a box insert: which shape it is, and that shape's own fields.
 *
 * Module level for `FieldProblems`' reason — a component declared during render remounts
 * on every keystroke and the input loses focus.
 *
 * The kind toggle keeps both halves of the state, so switching a compartment to a pocket
 * and back does not throw away the card count that was typed. Only the half that is
 * *shown* is sent (`specFromForm`), which is the union's own rule: a mapping carrying
 * both `count` and `width_mm` is refused by the schema naming both shapes, on purpose.
 */
function CompartmentEditor({
  index,
  state,
  byField,
  disabled,
  removable,
  onChange,
  onRemove,
}: {
  index: number;
  state: CompartmentFormState;
  byField: Partial<Record<SpecField, string[]>>;
  disabled: boolean;
  removable: boolean;
  onChange: (patch: Partial<CompartmentFormState>) => void;
  onRemove: () => void;
}) {
  const problems = (name: string) =>
    byField[`compartment.${index}.${name}` as SpecField];
  const isCards = state.kind === 'cards';

  return (
    <div className={styles.compartment}>
      <div className={styles.compartmentHead}>
        <span className="label">Compartment {index + 1}</span>
        <div className={styles.compartmentTools}>
          <div className="seg" role="group" aria-label={`Compartment ${index + 1} holds`}>
            {(['cards', 'pocket'] as const).map((kind) => (
              <button
                key={kind}
                type="button"
                disabled={disabled}
                aria-pressed={state.kind === kind}
                className={state.kind === kind ? 'is-active' : undefined}
                onClick={() => onChange({ kind })}
              >
                {kind === 'cards' ? 'Cards' : 'Pocket'}
              </button>
            ))}
          </div>
          <button type="button" className="btn" disabled={disabled || !removable} onClick={onRemove}>
            Remove
          </button>
        </div>
      </div>

      <div className={styles.grid}>
        {isCards ? (
          <>
            <label className={styles.field}>
              <span className="label-tight">Cards</span>
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={state.count}
                disabled={disabled}
                onChange={(e) => onChange({ count: e.target.value })}
              />
              <span className={styles.fieldNote}>
                {CARD_KINDS[0]} size — 63,5 × 88,9 mm; the deck lies flat
              </span>
              <FieldProblems messages={problems('count')} />
              <FieldProblems messages={problems('card')} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Sleeves</span>
              <select
                className="input"
                value={state.sleeving}
                disabled={disabled}
                onChange={(e) => onChange({ sleeving: e.target.value })}
              >
                {SLEEVINGS.map((sleeving) => (
                  <option key={sleeving} value={sleeving}>
                    {SLEEVING_NOTE[sleeving] ?? sleeving}
                  </option>
                ))}
              </select>
              <span className={styles.fieldNote}>decides the envelope and the pitch per card</span>
              <FieldProblems messages={problems('sleeving')} />
            </label>
          </>
        ) : (
          <>
            {/* The three millimetres are the *input*, not a default: no token or dice
                size is sourced anywhere in the dimension research, so there is no table
                to resolve them against and a preset would be a sourced size plus an
                invented clearance. */}
            <label className={styles.field}>
              <span className="label-tight">Width</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.widthMm}
                disabled={disabled}
                onChange={(e) => onChange({ widthMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                internal; no token or dice size is sourced, so this is yours
              </span>
              <FieldProblems messages={problems('widthMm')} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Depth</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.depthMm}
                disabled={disabled}
                onChange={(e) => onChange({ depthMm: e.target.value })}
              />
              <span className={styles.fieldNote}>internal, front to back</span>
              <FieldProblems messages={problems('depthMm')} />
            </label>

            <label className={styles.field}>
              <span className="label-tight">Depth (Z)</span>
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                placeholder="mm"
                value={state.heightMm}
                disabled={disabled}
                onChange={(e) => onChange({ heightMm: e.target.value })}
              />
              <span className={styles.fieldNote}>
                how deep this hole is; a shallower one sits on a floor that has risen
              </span>
              <FieldProblems messages={problems('heightMm')} />
            </label>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The resolved card stack — the sum, and where every number in it came from.
 *
 * Emphatically **not** a fit verdict, and it does not borrow one's words. It is the
 * server's own `resolve_stack`, printed: the sleeved envelope, the design pitch, the
 * height the stack comes to, and the `basis` sentence naming the measurement each of
 * those rests on. Whether the result fits is a measurement of an exported mesh, taken
 * in Phase 3, and nothing before then may imply it.
 *
 * `expectsStack` is false for the token tray, whose compartments are pockets: there is
 * nothing to resolve, `POST /organizer/resolve` returns `stacks: []` by design, and the
 * empty state's *fix the fields above* would be telling somebody their input is wrong
 * when it is not — the same failure `unreachable` was added to stop.
 */
function StackReadout({
  stacks,
  resolving,
  unreachable,
  expectsStack,
}: {
  stacks: ResolvedStack[];
  resolving: boolean;
  unreachable: boolean;
  expectsStack: boolean;
}) {
  if (!expectsStack) {
    return (
      <div className={styles.stackEmpty}>
        <Ruler size={13} strokeWidth={1.5} aria-hidden="true" />
        <span>
          No stack to resolve — a tray’s pockets are the millimetres you typed. Nothing
          in the dimension research sources a token or dice size, so there is no table
          behind these figures and the design does not pretend otherwise.
        </span>
      </div>
    );
  }
  if (!stacks.length) {
    return (
      <div className={styles.stackEmpty}>
        <Ruler size={13} strokeWidth={1.5} aria-hidden="true" />
        <span>
          {resolving
            ? 'Resolving the stack…'
            : unreachable
              ? 'The server did not answer, so there is no stack to show. Your fields are fine; this will fill in when it comes back.'
              : 'No stack resolved — fix the fields above and the server will work it out.'}
        </span>
      </div>
    );
  }

  return (
    <>
      {stacks.map((stack, i) => (
        <Blueprint key={i} className={styles.stack}>
          <div className={styles.stackHead}>
            <span className="label">Resolved stack</span>
            <span className={styles.stackTag}>{resolving ? 'recomputing…' : 'server-computed'}</span>
          </div>
          <p className={styles.stackSum}>
            {stack.count} × {stack.pitch_mm} mm = {stack.stack_height_mm} mm stack ·{' '}
            {stack.footprint_w_mm} × {stack.footprint_h_mm} mm per card
          </p>
          <p className={styles.stackBasis}>{stack.basis}</p>
        </Blueprint>
      ))}
    </>
  );
}
