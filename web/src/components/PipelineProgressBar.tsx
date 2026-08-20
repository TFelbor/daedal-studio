import { Image, Cuboid, Ruler, ShieldCheck, Layers, Printer, AlertCircle, CheckCircle2 } from 'lucide-react';

interface PhaseStatus {
  phase: number;
  name: string;
  status: 'pending' | 'running' | 'complete' | 'error';
}

interface PipelineProgressBarProps {
  phases: PhaseStatus[];
  /** Printability runs between Engineer and Slicer. It is not a numbered phase — the
   *  .status protocol and every historical job key off phases 1-5 — so its state comes
   *  from whether a report exists rather than from a phase number. */
  printabilityStatus?: PhaseStatus['status'];
}

const PRINTABILITY_STEP = -1;   // sentinel: a step with no phase number

const PHASE_CONFIG = [
  { phase: 1, name: 'Visualizer', icon: Image },
  { phase: 2, name: 'Sculptor', icon: Cuboid },
  { phase: 3, name: 'Engineer', icon: Ruler },
  { phase: PRINTABILITY_STEP, name: 'Printability', icon: ShieldCheck },
  { phase: 4, name: 'Slicer', icon: Layers },
  { phase: 5, name: 'Operator', icon: Printer },
];

export function PipelineProgressBar({ phases, printabilityStatus }: PipelineProgressBarProps) {
  const getStatus = (phaseNum: number) => {
    if (phaseNum === PRINTABILITY_STEP) {
      if (printabilityStatus) return printabilityStatus;
      // Engineer finishing is what triggers scoring, so mirror its completion.
      return phases.find(x => x.phase === 3)?.status === 'complete' ? 'running' : 'pending';
    }
    const p = phases.find(x => x.phase === phaseNum);
    return p ? p.status : 'pending';
  };

  return (
    <div style={{ width: '100%', padding: '12px 0', backgroundColor: 'transparent', borderTop: '1px solid var(--border-color)', containerType: 'inline-size' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', margin: '0 auto', gap: '8px', padding: '0 24px' }}>
        {PHASE_CONFIG.map((config, index) => {
          const status = getStatus(config.phase);
          const Icon = config.icon;
          
          let bgColor = 'var(--surface-color)';
          let textColor = 'var(--text-secondary)';
          let iconColor = 'var(--text-secondary)';
          let borderColor = 'var(--border-color)';
          let isRunning = false;

          if (status === 'complete') {
            textColor = '#10b981';
            iconColor = '#10b981';
            borderColor = '#10b981';
          } else if (status === 'error') {
            textColor = 'var(--accent-color)';
            iconColor = 'var(--accent-color)';
            borderColor = 'var(--accent-color)';
          } else if (status === 'running') {
            textColor = '#3b82f6';
            iconColor = '#3b82f6';
            borderColor = '#3b82f6';
            isRunning = true;
          }

          return (
            <div key={config.phase} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div style={{ 
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', 
                backgroundColor: bgColor, padding: '12px 8px', 
                borderRadius: 'var(--border-radius)',
                border: `1px solid ${borderColor}`,
                position: 'relative', overflow: 'hidden',
                boxShadow: 'none',
                transition: 'all 0.3s ease'
              }}>
                {isRunning && (
                  <div style={{
                    position: 'absolute', inset: 0,
                    background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent)',
                    transform: 'skewX(-20deg)',
                    animation: 'shimmer-bar 1.5s infinite'
                  }} />
                )}
                
                <div style={{ position: 'relative', zIndex: 1, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Icon size={20} color={iconColor} />
                  <span className="phase-label" style={{ color: textColor, fontWeight: 600, fontSize: '14px' }}>{config.name}</span>
                  {status === 'complete' && <CheckCircle2 size={16} color="#10b981" />}
                  {status === 'error' && <AlertCircle size={16} color="var(--accent-color)" />}
                </div>
              </div>
              
              {index < PHASE_CONFIG.length - 1 && (
                <div style={{ 
                  height: '1px', flex: 0.2, margin: '0 8px',
                  backgroundColor: status === 'complete' ? '#10b981' : 'var(--border-color)',
                  transition: 'background-color 0.3s ease'
                }} />
              )}
            </div>
          );
        })}
      </div>
      <style>{`
        @keyframes shimmer-bar {
          0% { left: -100%; }
          100% { left: 200%; }
        }
        @container (max-width: 600px) {
          .phase-label {
            display: none;
          }
        }
      `}</style>
    </div>
  );
}
