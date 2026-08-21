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
