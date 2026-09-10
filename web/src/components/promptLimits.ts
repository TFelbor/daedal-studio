/**
 * Hard cap on a prompt, shared by every field that takes one.
 *
 * Enforced but not advertised. A counter sitting at `0 / 250` from the first keystroke
 * turns writing a sentence into filling in a form — it makes people count instead of
 * describe. So the limit is invisible until it is nearly relevant: `maxLength` stops
 * the 251st character, and the remaining count only appears inside `COUNTER_REVEAL` of
 * the end, which is the first moment it is information rather than pressure.
 *
 * Held in one module because the landing field and the inline composer are the same
 * control in two places. The landing field previously had no cap at all: a pasted
 * novel went to the model, and to the telemetry row.
 */
export const MAX_PROMPT_CHARS = 250;

/** How close to the ceiling the remaining count becomes visible. */
export const COUNTER_REVEAL = 40;

/**
 * The verb on the button that sends a prompt, and its busy form.
 *
 * The landing field and `PromptZoom` are one control at two magnifications — the zoom
 * edits the same state and submits through the same `startJob` — and their buttons
 * disagreed about what pressing one does: `Compile & preview` on the page and
 * `Generate & print` on the plate. Both halves of the second one were wrong. *Generate*
 * is the benched generative path, in the one place the product says what it makes; and
 * a job submitted from the app sends `print: false, start_print: false`, so it stops at
 * the slicer and waits for a person at the dispatch gate — nothing this button does
 * starts a print.
 *
 * One constant rather than two literals pinned to each other by a test, for
 * `MAX_PROMPT_CHARS`'s reason: the drift is what has to be impossible, and a text guard
 * can only notice it afterwards.
 */
export const PROMPT_SUBMIT_LABEL = 'Compile & preview';

/** Shown while the job is being created. */
export const PROMPT_SUBMIT_BUSY_LABEL = 'Starting…';
