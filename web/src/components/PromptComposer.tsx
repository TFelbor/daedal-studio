import { useEffect, useRef, useState } from 'react';
import { ArrowRight, X } from 'lucide-react';
import { Marks } from './Blueprint';
import { reportUi } from '../api/activity';
import styles from './PromptComposer.module.css';

/**
 * Hard cap on a prompt.
 *
 * Enforced but not advertised. A counter sitting at `0 / 250` from the first keystroke
 * turns writing a sentence into filling in a form — it makes people count instead of
 * describe. So the limit is invisible until it is nearly relevant: `maxLength` stops
 * the 251st character, and the remaining-count only appears inside COUNTER_REVEAL of
 * the end, which is the first moment it is information rather than pressure.
 */
const MAX_CHARS = 250;
const COUNTER_REVEAL = 40;

interface PromptComposerProps {
  open: boolean;
  busy?: boolean;
  error?: string | null;
  /** Called with the trimmed prompt. The parent owns starting the job. */
  onSubmit: (prompt: string) => void;
  onCancel: () => void;
}

/**
 * The inline composer for starting the next job without leaving the one on screen.
 *
 * "New job" used to tear the running view down and return to the landing page, which
 * threw away the thing someone had just been looking at — usually the reason they want
 * another go. This expands in place instead: the previous result stays visible above
 * while the next prompt is written.
 *
 * The satisfying part is mostly restraint. It opens with one motion, takes focus so
 * the first keystroke lands in the right place, submits on ⌘/Ctrl+Enter and closes on
 * Escape, and says nothing at all until it has something worth saying.
 */
export function PromptComposer({ open, busy, error, onSubmit, onCancel }: PromptComposerProps) {
  const [value, setValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Take focus once the panel has started expanding, so the caret is not placed in a
  // 0px box and the first keystroke lands where the user is looking.
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 120);
    return () => window.clearTimeout(id);
  }, [open]);

  const trimmed = value.trim();
  const remaining = MAX_CHARS - value.length;
  const canSubmit = trimmed.length > 0 && !busy;

  /**
   * Clearing happens here and in `dismiss`, not in an effect keyed on `open`.
   *
   * Reopening must be a fresh sheet, not a half-finished thought from ten minutes ago
   * — but resetting from an effect is a cascading render, and every close already goes
   * through one of these two paths.
   */
  const submit = () => {
    if (!canSubmit) return;
    reportUi('new job composer', `submitted ${trimmed.length} chars`);
    setValue('');
    onSubmit(trimmed);
  };

  const dismiss = () => {
    reportUi('new job composer', 'cancelled');
    setValue('');
    onCancel();
  };

  return (
    <div
      className={open ? `${styles.shell} ${styles.shellOpen}` : styles.shell}
      aria-hidden={!open}
    >
      {/* `inert` keeps the collapsed panel out of tab order and off screen readers
          without unmounting it, which is what lets the height animate at all. */}
      <div className={styles.inner} {...(!open ? { inert: '' as unknown as boolean } : {})}>
        <div className={styles.head}>
          <span className="label">Next job</span>
          <button
            type="button"
            className={styles.close}
            onClick={dismiss}
            aria-label="Cancel"
          >
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>

        <div className={`blueprint marked-accent ${styles.frame}`}>
          <Marks />
          <textarea
            ref={inputRef}
            className={styles.input}
            value={value}
            maxLength={MAX_CHARS}
            placeholder="Describe the next part the way you would describe it to someone…"
            aria-label="Describe the object to print"
            disabled={busy}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              // ⌘/Ctrl+Enter submits. A bare Enter must stay a newline: the field is
              // for a sentence or two, and losing a half-written prompt to a stray
              // return is the kind of thing people do not forgive.
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              } else if (e.key === 'Escape') {
                e.preventDefault();
                dismiss();
              }
            }}
          />
          <div className={styles.footer}>
            <span className={styles.hint}>
              {error ? (
                <span className={styles.error}>{error}</span>
              ) : (
                <>
                  <kbd className={styles.kbd}>⌘</kbd>
                  <kbd className={styles.kbd}>↵</kbd> to start
                </>
              )}
            </span>
            <span className={styles.right}>
              {/* Appears only near the ceiling. See MAX_CHARS. */}
              <span
                className={
                  remaining <= COUNTER_REVEAL
                    ? `${styles.counter} ${styles.counterShown}`
                    : styles.counter
                }
                aria-live="polite"
              >
                {remaining} left
              </span>
              <button
                type="button"
                className={`btn btn-primary ${styles.go}`}
                onClick={submit}
                disabled={!canSubmit}
              >
                {busy ? 'Starting' : 'Start'}
                <ArrowRight size={15} strokeWidth={1.5} />
              </button>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
