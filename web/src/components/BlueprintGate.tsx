import { useState } from 'react';
import { AlertTriangle, ArrowRight, RotateCcw } from 'lucide-react';
import { decideBlueprint } from '../api/client';
import type { BlueprintGateSubject } from '../api/client';
import { Marks } from './Blueprint';
import { SpecPanel } from './SpecPanel';
import { NO_SPEC_REASON, type OrganizerSpec } from '../organizer/spec';
import { reportUi } from '../api/activity';
import styles from './BlueprintGate.module.css';

interface BlueprintGateProps {
  jobId: string;
  subject: BlueprintGateSubject | null;
  /**
   * The compiled spec, when there is one.
   *
   * The gate is the same decision either way — a person looks at what will be
   * built and says yes — but *what* they are looking at decides how it is
   * titled. Nothing produces a spec yet, so this is null in every build today
   * and the gate names the blueprint it is actually showing.
   */
  spec?: OrganizerSpec | null;
  /** Called once Phase 2 has been started, so the view can follow it. */
  onApproved: () => void;
  /** Called when the requester declines this blueprint. */
  onRejected: () => void;
}

/**
 * The last cheap moment in the pipeline.
 *
 * Everything after this point costs something that cannot be given back: a paid
 * reconstruction on the hosted sculptor, GPU minutes on a self-hosted one, then
 * filament and hours. Up to here the only thing spent is one image.
 *
 * Two reasons it exists, and the second is the bigger one.
 *
 * **It is where a person decides about resemblance.** The prompt screen reads text and
 * the image screen scores a render against a list of names; neither can be the last
 * word on whether a shape reproduces someone else's character, and the image screen's
 * threshold is not calibrated yet. A flag arrives here for a human rather than failing
 * Phase 1 with no appeal.
 *
 * **It is where expectations get corrected.** The pipeline discards appearance and
 * prints in one colour, at a 0.4mm nozzle. Whatever the prompt asked for, what arrives
 * is a silhouette. Someone who was picturing something else should find that out from
 * a picture in thirty seconds, not from a part four minutes and EUR 0.32 later.
 *
 * The hash is sent back with the decision. Approving an image that has since been
 * replaced is not approving, and the server answers 409 — the same rule the dispatch
 * gate applies to a printer that is no longer the target.
 */
export function BlueprintGate({ jobId, subject, spec = null, onApproved, onRejected }: BlueprintGateProps) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (approve: boolean) => {
    if (busy) return;
    setBusy(approve ? 'approve' : 'reject');
    setError(null);
    try {
      reportUi('blueprint gate', approve ? 'approved' : 'rejected');
      await decideBlueprint(jobId, approve, subject?.sha256 ?? null);
      if (approve) onApproved();
      else onRejected();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The decision could not be recorded');
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={`blueprint ${styles.gate}`} aria-labelledby="blueprint-gate-title">
      <Marks />
      <div className={styles.head}>
        <h2 className="label-accent" id="blueprint-gate-title">
          {spec ? 'Approve the spec · waiting on you' : 'Approve the blueprint · waiting on you'}
        </h2>
        <p className={styles.blurb}>
          {spec
            ? 'These are the numbers the part will be built from. Check the fit — nothing slices until you approve them.'
            : 'Nothing has been reconstructed yet. This is the last step before the 3D model is generated, which is the part that costs money and time. The print itself is a single colour — what carries over from this image is the shape.'}
        </p>
      </div>

      {/* The spec, when one exists. A gated job is a Phase 1 job by construction —
          a spec run skips both generative phases and is never gated — so this states
          the reason rather than showing an empty table, and the blueprint below it
          stays the thing being approved. */}
      <SpecPanel spec={spec} unavailableReason={NO_SPEC_REASON} />

      {subject ? (
        <img className={styles.preview} src={subject.url} alt="The generated blueprint awaiting approval" />
      ) : (
        <p className={styles.blurb}>The blueprint is not available to display.</p>
      )}

      {error && (
        <p className={`notice ${styles.error}`} role="alert">
          <AlertTriangle size={13} strokeWidth={1.5} aria-hidden="true" />
          {error}
        </p>
      )}

      <div className={styles.actions}>
        <button
          type="button"
          className={`btn btn-primary blueprint marked-accent ${styles.approve}`}
          onClick={() => decide(true)}
          disabled={busy !== null || !subject}
        >
          <Marks />
          {busy === 'approve' ? 'Starting…' : spec ? 'Approve & slice' : 'Approve & build the model'}
          {busy !== 'approve' && <ArrowRight size={15} strokeWidth={1.5} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={`btn ${styles.reject}`}
          onClick={() => decide(false)}
          disabled={busy !== null}
        >
          <RotateCcw size={14} strokeWidth={1.5} aria-hidden="true" />
          {busy === 'reject' ? 'Stopping…' : 'Not this one'}
        </button>
      </div>
      {subject && (
        <p className={styles.hashLine}>
          <span className="label-tight">Image</span>
          <code>{subject.sha256.slice(0, 12)}</code>
        </p>
      )}
    </section>
  );
}
