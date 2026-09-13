import { AlertTriangle, Ruler } from 'lucide-react';
import { Blueprint } from './Blueprint';
import {
  CARD_KINDS,
  FIT_INTENTS,
  FIT_INTENT_LABELS,
  LID_KINDS,
  SLEEVINGS,
  SLEEVING_NOTE,
  TAB_POSITIONS,
} from '../organizer/spec';
import { problemsByField, type SpecFormState } from '../organizer/specForm';
import type { ResolvedStack, SpecProblem } from '../api/client';
import styles from './SpecForm.module.css';

interface SpecFormProps {
  state: SpecFormState;
  onChange: (next: SpecFormState) => void;
  /** Every problem the server named, from the live resolve or from a refused submit. */
  problems: SpecProblem[];
  /** The stacks `POST /organizer/resolve` computed, or none while it has not answered. */
  stacks: ResolvedStack[];
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
  resolving = false,
  unreachable = false,
  disabled = false,
}: SpecFormProps) {
  const byField = problemsByField(problems);
  const set = (patch: Partial<SpecFormState>) => onChange({ ...state, ...patch });
  const isDeckBox = state.archetype === 'deck_box';
  const isTray = state.archetype === 'token_tray';

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

      <div className={styles.grid}>
        {/* A tray holds pockets, not cards, so the two card controls are not merely
            ignored for it — they are absent. `specFromForm` sends no card stack for a
            token tray either, and a control that sends nothing is a control that
            cannot be refused, which is worse than one that is not there. */}
        {isTray ? null : (
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

        {isTray ? (
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

      <FieldProblems messages={byField.archetype} />

      <StackReadout
        stacks={stacks}
        resolving={resolving}
        unreachable={unreachable}
        expectsStack={!isTray}
      />
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
