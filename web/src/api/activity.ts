/**
 * Report interactions that never reach another endpoint.
 *
 * Switching a stage tab, scrubbing a layer, collapsing the log — from the server's
 * side a person who spent five minutes hunting for something looked exactly like an
 * idle one. These land in the in-memory activity feed only; nothing is persisted.
 *
 * Batched on purpose. A layer scrubber fires on every pointer move, and one request
 * per event would put hundreds of writes behind a drag — the thing this is meant to
 * help diagnose would become the thing causing the problem.
 */

import { apiFetch } from './http';

interface UiEvent {
  action: string;
  detail?: string;
}

const FLUSH_MS = 1000;
/** Matches the server's per-batch cap; anything above it would be dropped there. */
const MAX_BATCH = 50;

let queue: UiEvent[] = [];
let timer: number | null = null;

function flush() {
  timer = null;
  if (queue.length === 0) return;
  const events = queue.slice(0, MAX_BATCH);
  queue = queue.slice(MAX_BATCH);

  // `keepalive` so a report queued as the tab closes still goes out, and a silent
  // catch because a failed diagnostic must never surface as an error to the user.
  apiFetch('/activity/ui', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ events }),
    keepalive: true,
  }).catch(() => {});

  if (queue.length > 0) schedule();
}

function schedule() {
  if (timer !== null) return;
  timer = window.setTimeout(flush, FLUSH_MS);
}

/**
 * Note that the user did something.
 *
 * @param action Short verb phrase, stable across calls so it can be grouped.
 * @param detail Optional specifics — what changed, or to what.
 */
export function reportUi(action: string, detail?: string): void {
  // Drop rather than grow without bound: a drag that outruns the flush interval is
  // exactly when this must not become a memory leak.
  if (queue.length >= MAX_BATCH * 4) return;
  queue.push(detail ? { action, detail } : { action });
  schedule();
}
