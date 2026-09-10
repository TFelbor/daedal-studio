import { ARCHETYPES, type ArchetypeId } from '../organizer/spec';
import styles from './ArchetypeStrip.module.css';

interface ArchetypeStripProps {
  /** The chosen archetype, or null for a free prompt with no steer. */
  value: ArchetypeId | null;
  onChange: (next: ArchetypeId | null) => void;
  disabled?: boolean;
}

/**
 * The archetypes the engine can compile, as a segmented strip above the prompt.
 *
 * The list comes from `organizer/spec.ts` and is exactly the backend's `ARCHETYPES`,
 * so a cell never offers a shape the compiler would refuse.
 *
 * Progressive disclosure, in the Hero Forge sense: the broadest choice first, so
 * the prompt underneath has somewhere to start rather than facing an empty box.
 * Choosing is optional — a free prompt is still the primary path and the reason
 * the selected cell toggles off when clicked again — because the archetype is a
 * hint to the composer, not a mode the rest of the form switches on.
 */
export function ArchetypeStrip({ value, onChange, disabled = false }: ArchetypeStripProps) {
  return (
    <div className={styles.wrap}>
      <span className={styles.legend}>Archetype</span>
      <div className={`seg ${styles.strip}`} role="group" aria-label="Archetype">
        {ARCHETYPES.map((a) => {
          const active = value === a.id;
          return (
            <button
              key={a.id}
              type="button"
              disabled={disabled}
              aria-pressed={active}
              className={active ? 'is-active' : undefined}
              // Clicking the chosen one clears it: the strip is a steer, and a
              // steer you cannot take back is a mode.
              onClick={() => onChange(active ? null : a.id)}
            >
              {a.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
