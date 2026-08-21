import { BootMark } from '../components/BootMark';
import { DeadChannel } from '../components/DeadChannel';
import { Blueprint } from '../components/Blueprint';
import { WaitingStage } from '../components/WaitingStage';
import type { WaitingKind } from '../components/WaitingStage';
import styles from './WaitingStatesGallery.module.css';

/**
 * Every waiting state on one page, for reviewing them.
 *
 * These states are the hardest thing in the app to look at: each one appears for
 * seconds, in the middle of a five-phase run, and two of them only on a machine with
 * a printer attached. Reviewing them by starting jobs means waiting minutes to see a
 * drawing for ten seconds, which is how they came to be four different dashed boxes
 * in the first place.
 *
 * Mounted only under `import.meta.env.DEV` (see App.tsx), so it is not in the
 * production bundle and is not a product surface. It renders the real components —
 * there is no second copy of any drawing here to drift out of step.
 */
const STAGES: { kind: WaitingKind; label: string; note: string; caption: string }[] = [
  {
    kind: 'blueprint',
    label: 'PHASE 01 · OUTPUT',
    note: 'awaiting phase 01',
    caption:
      'A drafting head laying the isometric outline across the sheet. Construction lines first, then the object, with an accent band at the leading edge and a registration cross on every corner the head has passed. Drag to scrub it by hand.',
  },
  {
    kind: 'mesh',
    label: 'PHASE 03 · OUTPUT',
    note: 'awaiting phase 03',
    caption:
      'A stand-in solid assembling itself, vertices before edges, each vertex wearing a registration cross. Drag to orbit — the same gesture the real three.js viewer answers to, so the wait rehearses the control instead of blocking it.',
  },
  {
    kind: 'slice',
    label: 'PHASE 04 · OUTPUT',
    note: 'awaiting phase 04',
    caption:
      'The toolpath stack climbing. Cooled layers fade with depth, every fifth reads brighter, the layer being written carries its infill and the nozzle square sits on its perimeter. Drag vertically to travel the stack.',
  },
];

function Panel({ title, meta, children }: { title: string; meta: string; children: React.ReactNode }) {
  return (
    <div className={styles.panel}>
      <div className={styles.panelHead}>
        <span className="label">{title}</span>
        <span className={`mono ${styles.panelMeta}`}>{meta}</span>
      </div>
      {children}
    </div>
  );
}

export function WaitingStatesGallery() {
  return (
    <div className="sheet">
      <div className="eyebrow">
        <span className="label-accent">Dev only · not in the production bundle</span>
      </div>
      <h1 className="display">Waiting states</h1>
      <p className="lede" style={{ maxWidth: 720, marginBottom: 40 }}>
        Every state the app shows while something does not exist yet. Each drawn stage
        is live and draggable. The left column of each pair is the phase running; the
        right is the phase not started, which must not pulse and must not take the
        accent.
      </p>

      {STAGES.map(stage => (
        <section key={stage.kind} className={styles.section}>
          <div className={styles.sectionHead}>
            <span className="label">{stage.kind}</span>
          </div>
          <div className={styles.pair}>
            <Panel title="Running" meta="pulse · accent · rotating step">
              <Blueprint tone="accent" className={styles.stage}>
                <span className={styles.stageLabel}>{stage.label}</span>
                <WaitingStage kind={stage.kind} running fill />
              </Blueprint>
            </Panel>
            <Panel title="Not started" meta="no pulse · ink, not accent">
              <Blueprint tone="accent" className={styles.stage}>
                <span className={styles.stageLabel}>{stage.label}</span>
                <WaitingStage kind={stage.kind} note={stage.note} fill />
              </Blueprint>
            </Panel>
          </div>
          <p className={styles.caption}>{stage.caption}</p>
        </section>
      ))}

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className="label">Boot mark</span>
        </div>
        <div className={styles.pair}>
          <Panel title="Whole page" meta="54 px · on the ruled ground">
            <Blueprint className={styles.block}>
              <BootMark block ground label="Reading pipeline state" />
            </Blueprint>
          </Panel>
          <Panel title="Inline, in a panel" meta="22 px · stroke held at one weight">
            <Blueprint className={styles.block}>
              <div className={styles.inlineRow}>
                <BootMark size={22} label="Reading the report" />
              </div>
            </Blueprint>
          </Panel>
        </div>
        <p className={styles.caption}>
          The identity drawing itself: the finished top face fills, then the walls
          strike in. Replaces the spinning Lucide loader on every wait that is the app
          reading its own state. Deliberately the only place the logo animates, and
          deliberately never inside a button.
        </p>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className="label">Dead channel</span>
        </div>
        <div className={styles.pair}>
          <Panel title="Rail · 120 px" meta="telemetry, nothing reporting">
            <DeadChannel>No printer data until phase 05</DeadChannel>
          </Panel>
          <Panel title="Chart slot · 148 px" meta="hotend, whole print">
            <DeadChannel height={148}>
              The hotend charts here once the printer starts reporting
            </DeadChannel>
          </Panel>
        </div>
        <p className={styles.caption}>
          An instrument with nothing on the line, rather than an icon and a sentence.
          The trace is dead flat and honest; the sweep is what says the channel is open
          and listening, which is a different fact from a broken panel. It is the one
          element here that carries no interaction.
        </p>
      </section>
    </div>
  );
}
