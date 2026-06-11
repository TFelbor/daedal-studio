import { Image, Cuboid, Ruler, Layers, Printer, AlertCircle, CheckCircle2 } from 'lucide-react';

interface PhaseStatus {
  phase: number;
  name: string;
  status: 'pending' | 'running' | 'complete' | 'error';
}

interface PipelineProgressBarProps {
  phases: PhaseStatus[];
}

const PHASE_CONFIG = [
  { phase: 1, name: 'Visualizer', icon: Image },
  { phase: 2, name: 'Sculptor', icon: Cuboid },
  { phase: 3, name: 'Engineer', icon: Ruler },
  { phase: 4, name: 'Slicer', icon: Layers },
  { phase: 5, name: 'Operator', icon: Printer },
];

export function PipelineProgressBar({ phases }: PipelineProgressBarProps) {
  const getStatus = (phaseNum: number) => {
    const p = phases.find(x => x.phase === phaseNum);
    return p ? p.status : 'pending';
  };

  return (
    <div style={{ width: '100%', padding: '16px 0', backgroundColor: '#fff', borderTop: '1px solid #e5e5e5' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', maxWidth: '1200px', margin: '0 auto', gap: '8px', padding: '0 16px' }}>
        {PHASE_CONFIG.map((config, index) => {
          const status = getStatus(config.phase);
          const Icon = config.icon;
          
          let bgColor = '#f3f4f6';
          let textColor = '#9ca3af';
          let iconColor = '#9ca3af';
          let isRunning = false;

          if (status === 'complete') {
            bgColor = '#10b981';
            textColor = '#fff';
            iconColor = '#fff';
          } else if (status === 'error') {
            bgColor = '#ef4444';
            textColor = '#fff';
            iconColor = '#fff';
          } else if (status === 'running') {
            bgColor = '#3b82f6';
            textColor = '#fff';
            iconColor = '#fff';
            isRunning = true;
          }

          return (
            <div key={config.phase} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div style={{ 
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', 
                backgroundColor: bgColor, padding: '12px 8px', borderRadius: '8px',
                position: 'relative', overflow: 'hidden',
                boxShadow: isRunning ? '0 0 10px rgba(59, 130, 246, 0.5)' : 'none',
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
                  <span style={{ color: textColor, fontWeight: 600, fontSize: '14px' }}>{config.name}</span>
                  {status === 'complete' && <CheckCircle2 size={16} color="#fff" />}
                  {status === 'error' && <AlertCircle size={16} color="#fff" />}
                </div>
              </div>
              
              {index < PHASE_CONFIG.length - 1 && (
                <div style={{ 
                  height: '4px', flex: 0.2, margin: '0 8px', borderRadius: '2px',
                  backgroundColor: status === 'complete' ? '#10b981' : '#e5e5e5',
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
      `}</style>
    </div>
  );
}
