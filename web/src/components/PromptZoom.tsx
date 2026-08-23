import { useEffect, useRef } from 'react';
import { PromptNotice } from './PromptNotice';
import { ArrowRight, Minimize2 } from 'lucide-react';
import { Marks } from './Blueprint';
import { COUNTER_REVEAL, MAX_PROMPT_CHARS } from './promptLimits';
import styles from './PromptZoom.module.css';

interface PromptZoomProps {
  value: string;
  busy?: boolean;
  onChange: (next: string) => void;
  /** Called with the trimmed prompt. The parent owns starting the job. */
  onSubmit: (prompt: string) => void;
  onClose: () => void;
}

/**
 * The prompt field, lifted off the page.
 *
 * The landing field used to be draggable by its corner — uncapped, so it could be
 * pulled taller than the viewport, and pointless, because a resize handle is a way of
 * asking the writer to do layout. The field is a fixed size now, and this is what
 * replaces the handle: one control that raises the same text onto a plate in the middle
 * of the screen, at reading size, with everything behind it dimmed just enough to say
 * where to look.
 *
 * The dim is deliberately shallow. A near-black scrim would turn a change of scale into
 * a modal interruption, and this is the same task at a different magnification, not a
 * different task.
 */
export function PromptZoom({ value, busy, onChange, onSubmit, onClose }: PromptZoomProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const trimmed = value.trim();
  const remaining = MAX_PROMPT_CHARS - value.length;
  const canSubmit = trimmed.length > 0 && !busy;

  // Take focus with the caret *after* the existing text: this is a continuation of
  // what someone was already typing, and a selected-all field invites deleting it.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    const end = input.value.length;
    input.setSelectionRange(end, end);
  }, []);

  /**
   * Escape closes; Tab cycles inside the panel.
   *
   * The trap is hand-rolled rather than pulled from a library: the panel holds four
   * focusable things, and shipping a dependency to keep Tab inside them would cost
   * more than the loop does.
   */
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
      'textarea, button:not([disabled])',
    );
    if (!focusable || focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className={styles.shell} onKeyDown={onKeyDown}>
      {/* A click on the dimmed surface closes it — the same gesture as looking away. */}
      <button
        type="button"
        className={styles.scrim}
        aria-label="Close the expanded prompt"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Write the prompt"
      >
        <div className={styles.head}>
          <span className="label-accent">Prompt</span>
          <button type="button" className={styles.collapse} onClick={onClose}>
            <Minimize2 size={13} strokeWidth={1.5} aria-hidden="true" /> Collapse
          </button>
        </div>

        <div className={`blueprint marked-accent field-frame ${styles.frame}`}>
          <Marks />
          <textarea
            ref={inputRef}
            className={styles.input}
            value={value}
            maxLength={MAX_PROMPT_CHARS}
            placeholder="A low poly planter box with a modern geometric design…"
            aria-label="Describe the object to print"
            disabled={busy}
            onChange={event => onChange(event.target.value)}
            onKeyDown={event => {
              // ⌘/Ctrl+Enter sends from here. A bare Enter stays a newline: the whole
              // reason to be at this size is to write more than one line.
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                if (canSubmit) onSubmit(trimmed);
              }
            }}
          />
        </div>

        <div className={styles.footer}>
          <PromptNotice className={styles.notice} />
          <span className={styles.hint}>
            <kbd className={styles.kbd}>⌘</kbd>
            <kbd className={styles.kbd}>↵</kbd> to start · <kbd className={styles.kbd}>Esc</kbd> to
            collapse
          </span>
          <span className={styles.right}>
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
              onClick={() => canSubmit && onSubmit(trimmed)}
              disabled={!canSubmit}
            >
              {busy ? 'Starting' : 'Generate & print'}
              <ArrowRight size={15} strokeWidth={1.5} aria-hidden="true" />
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
