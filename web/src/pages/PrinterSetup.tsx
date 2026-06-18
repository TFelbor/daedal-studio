import { useState, useEffect } from 'react';
import { Server, Settings, Info, Eye, EyeOff, Loader2, CheckCircle, AlertCircle, AlertTriangle } from 'lucide-react';
import {
  getConfig,
  setConfig,
  revealConfig,
  testConnection,
  getSimulatorStatus,
  startSimulator,
  stopSimulator
} from '../api/config';
import type { ConfigResponse, SimulatorStatus } from '../api/config';
import styles from './PrinterSetup.module.css';

const DEFAULT_PROFILES = [
  'pythonsrc/profiles/anycubic_mega.json',
  'pythonsrc/profiles/bambu_test.json',
  'pythonsrc/profiles/ender3.json',
  'pythonsrc/profiles/klipper_test.json',
];

export function PrinterSetup() {
  const [config, setConfigState] = useState<ConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [simStatus, setSimStatus] = useState<SimulatorStatus | null>(null);
  const [simStatusLoading, setSimStatusLoading] = useState(true);
  const [useSimSuccess, setUseSimSuccess] = useState<'moonraker' | 'octoprint' | null>(null);
  const [printerType, setPrinterType] = useState('moonraker');
  
  const [hfTokenInput, setHfTokenInput] = useState('');
  const [showHfToken, setShowHfToken] = useState(false);
  const [hfTestResult, setHfTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [hfTesting, setHfTesting] = useState(false);
  
  const [moonrakerUrl, setMoonrakerUrl] = useState('');
  const [moonrakerKey, setMoonrakerKey] = useState('');
  
  const [octoprintUrl, setOctoprintUrl] = useState('');
  const [octoprintKey, setOctoprintKey] = useState('');
  
  const [bambuIp, setBambuIp] = useState('');
  const [bambuCode, setBambuCode] = useState('');
  
  const [printerTestResult, setPrinterTestResult] = useState<{ success: boolean; message: string; latency?: number | null } | null>(null);
  const [printerTesting, setPrinterTesting] = useState(false);

  const [savingField, setSavingField] = useState<string | null>(null);
  const [savedField, setSavedField] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [simLoading, setSimLoading] = useState<string | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

  const [overallStatus, setOverallStatus] = useState<'loading' | 'checking' | 'ready' | 'error' | 'incomplete'>('loading');
  const [overallMessage, setOverallMessage] = useState('Loading configuration...');

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchSimStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const data = await getConfig();
      setConfigState(data);
      
      if (data['DEFAULT_PRINTER_FIRMWARE']?.value) setPrinterType(data['DEFAULT_PRINTER_FIRMWARE'].value);
      if (data['HF_TOKEN']?.is_set) setHfTokenInput(data['HF_TOKEN'].value || '');
      if (data['MOONRAKER_URL']?.value) setMoonrakerUrl(data['MOONRAKER_URL'].value);
      if (data['MOONRAKER_API_KEY']?.is_set) setMoonrakerKey(data['MOONRAKER_API_KEY'].value || '');
      if (data['OCTOPRINT_URL']?.value) setOctoprintUrl(data['OCTOPRINT_URL'].value);
      if (data['OCTOPRINT_API_KEY']?.is_set) setOctoprintKey(data['OCTOPRINT_API_KEY'].value || '');
      // Additional config defaults
      if (data['BAMBU_IP']?.value) setBambuIp(data['BAMBU_IP'].value);
      if (data['BAMBU_CODE']?.is_set) setBambuCode(data['BAMBU_CODE'].value || '');

    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!loading && config) {
      runOverallChecks();
    }
  }, [loading, config, printerType]);

  const runOverallChecks = async () => {
    if (!config) return;

    const hfSet = config['HF_TOKEN']?.is_set;
    const skipViz = config['SKIP_VISUALIZER']?.value === 'true';
    const skipSculpt = config['SKIP_SCULPTOR']?.value === 'true';

    if (!hfSet && !skipViz) {
      setOverallStatus('incomplete');
      setOverallMessage('Setup incomplete — HuggingFace token missing.');
      return;
    }

    const moonrakerSet = config['MOONRAKER_URL']?.value;
    const octoprintSet = config['OCTOPRINT_URL']?.value;
    const bambuSet = config['BAMBU_IP']?.value;
    const printerSet = moonrakerSet || octoprintSet || bambuSet || (skipViz && skipSculpt);

    if (!printerSet) {
      setOverallStatus('incomplete');
      setOverallMessage('Setup incomplete — Printer URL not configured.');
      return;
    }

    setOverallStatus('checking');
    setOverallMessage('Checking HuggingFace and Printer connections...');

    // Test HF
    if (!skipViz) {
      try {
        const hfRes = await testConnection('huggingface');
        if (!hfRes.success) {
          setOverallStatus('error');
          setOverallMessage(`HuggingFace connection failed: ${hfRes.message}`);
          return;
        }
      } catch (e: any) {
        setOverallStatus('error');
        setOverallMessage(`HuggingFace check error: ${e?.message || 'Failed'}`);
        return;
      }
    }

    // Test Printer
    try {
      const pRes = await testConnection(printerType);
      if (!pRes.success) {
        setOverallStatus('error');
        setOverallMessage(`Printer connection failed: ${pRes.message} (Is your printer or simulator running?)`);
        return;
      }
    } catch (e: any) {
      setOverallStatus('error');
      setOverallMessage(`Printer check error: ${e?.message || 'Failed'}`);
      return;
    }

    setOverallStatus('ready');
    setOverallMessage('Ready to print — all systems operational');
  };

  const fetchSimStatus = async () => {
    try {
      const status = await getSimulatorStatus();
      setSimStatus(status);
    } catch (e) {
      // ignore
    } finally {
      setSimStatusLoading(false);
    }
  };

  const handleSaveConfig = async (key: string, value: string) => {
    if (value === '••••••••' && config?.[key]?.secret) return;
    setSavingField(key);
    try {
      await setConfig(key, value);
      setSavedField(key);
      setTimeout(() => setSavedField(null), 2000);
      
      const data = await getConfig();
      setConfigState(data);
    } catch (e: any) {
      setSaveError(e?.message || 'Save failed');
      setTimeout(() => setSaveError(null), 3000);
    } finally {
      setSavingField(null);
    }
  };

  const handleSimAction = async (service: string, action: 'start' | 'stop') => {
    setSimLoading(service);
    setSimError(null);
    try {
      if (action === 'start') await startSimulator(service);
      else await stopSimulator(service);
      setTimeout(() => fetchSimStatus(), 500);
    } catch (e: any) {
      setSimError(`${service}: ${e?.message || 'action failed'}`);
      setTimeout(() => setSimError(null), 5000);
    } finally {
      setSimLoading(null);
    }
  };

  const handleToggleReveal = async (key: string, setter: (val: string) => void, showState: boolean, setShowState: (val: boolean) => void) => {
    if (showState) {
      setShowState(false);
      setter('••••••••');
    } else {
      try {
        const revealed = await revealConfig(key);
        setter(revealed);
        setShowState(true);
      } catch (e) {
        console.error("Failed to reveal");
      }
    }
  };

  const testHfConnection = async () => {
    setHfTesting(true);
    setHfTestResult(null);
    try {
      const res = await testConnection('huggingface');
      setHfTestResult({ success: res.success, message: res.message });
    } catch (e: any) {
      setHfTestResult({ success: false, message: e.message || 'Error' });
    } finally {
      setHfTesting(false);
    }
  };

  const testPrinterConnection = async () => {
    setPrinterTesting(true);
    setPrinterTestResult(null);
    try {
      const res = await testConnection(printerType);
      setPrinterTestResult({ success: res.success, message: res.message, latency: res.latency_ms });
    } catch (e: any) {
      setPrinterTestResult({ success: false, message: e.message || 'Error' });
    } finally {
      setPrinterTesting(false);
    }
  };

  const renderStatusIcon = () => {
    switch (overallStatus) {
      case 'loading':
      case 'checking':
        return <Loader2 className="animate-spin" />;
      case 'ready':
        return <CheckCircle />;
      case 'error':
        return <AlertCircle />;
      case 'incomplete':
        return <AlertTriangle />;
    }
  };

  const getStatusColor = () => {
    switch (overallStatus) {
      case 'loading':
      case 'checking':
        return 'var(--text-secondary)';
      case 'ready':
        return 'green';
      case 'error':
      case 'incomplete':
        return 'var(--accent-color)';
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className={styles.container}>
      <h1 style={{ marginBottom: '1.5rem', marginTop: 0 }}>Settings</h1>

      <div style={{ display: 'flex', gap: '8px', padding: '16px', borderRadius: 'var(--border-radius)', marginBottom: '24px', backgroundColor: 'var(--surface-color)', border: `1px solid ${overallStatus === 'ready' ? 'green' : 'var(--border-color)'}`, color: getStatusColor() }}>
        {renderStatusIcon()}
        <span style={{ fontWeight: 500 }}>{overallMessage}</span>
      </div>

      {saveError && (
        <div style={{ display: 'flex', gap: '8px', padding: '12px 16px', borderRadius: 'var(--border-radius)', marginBottom: '24px', backgroundColor: 'var(--surface-color)', border: '1px solid var(--accent-color)', color: 'var(--accent-color)', fontWeight: 500 }}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '1px' }} /> {saveError}
        </div>
      )}

      {simError && (
        <div style={{ display: 'flex', gap: '8px', padding: '12px 16px', borderRadius: 'var(--border-radius)', marginBottom: '24px', backgroundColor: 'var(--surface-color)', border: '1px solid var(--accent-color)', color: 'var(--accent-color)', fontWeight: 500 }}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '1px' }} /> {simError}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        {/* Section 1: AI Models */}
        <div className="card" style={{ padding: '24px', textAlign: 'left' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: 0 }}>
            <Server size={24} /> AI Models
          </h2>
          <div className="form-group" style={{ maxWidth: '600px' }}>
            <label>HuggingFace Token</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type={showHfToken ? "text" : "password"}
                className="input"
                value={hfTokenInput}
                onChange={(e) => setHfTokenInput(e.target.value)}
                onBlur={(e) => {
                  if (e.target.value && e.target.value !== '••••••••') handleSaveConfig('HF_TOKEN', e.target.value);
                }}
                placeholder="hf_..."
                style={{ flex: 1 }}
              />
              <button 
                className="btn btn-secondary"
                onClick={() => handleToggleReveal('HF_TOKEN', setHfTokenInput, showHfToken, setShowHfToken)}
              >
                {showHfToken ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
              <button className="btn btn-primary" onClick={testHfConnection} disabled={hfTesting}>
                {hfTesting ? <Loader2 className="animate-spin" size={16} /> : 'Verify Token'}
              </button>
              {savingField === 'HF_TOKEN' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
              {savedField === 'HF_TOKEN' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
            </div>
            {hfTestResult && (
              <div style={{ color: hfTestResult.success ? 'green' : 'red', marginTop: '8px', fontSize: '14px' }}>
                {hfTestResult.success ? '✓ ' : '✗ '}{hfTestResult.message}
              </div>
            )}
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '8px' }}>
              Required to download the FLUX base model. Get your token at <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">huggingface.co/settings/tokens</a>.
            </div>
          </div>

          <div style={{ marginTop: '24px', display: 'flex', gap: '24px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input 
                type="checkbox" 
                checked={config?.['SKIP_VISUALIZER']?.value === 'true'}
                onChange={(e) => handleSaveConfig('SKIP_VISUALIZER', e.target.checked ? 'true' : 'false')}
              />
              Skip Visualizer (Phase 1)
              {savingField === 'SKIP_VISUALIZER' && <Loader2 className="animate-spin" size={14}/>}
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input 
                type="checkbox" 
                checked={config?.['SKIP_SCULPTOR']?.value === 'true'}
                onChange={(e) => handleSaveConfig('SKIP_SCULPTOR', e.target.checked ? 'true' : 'false')}
              />
              Skip Sculptor (Phase 2)
              {savingField === 'SKIP_SCULPTOR' && <Loader2 className="animate-spin" size={14}/>}
            </label>
          </div>
        </div>

        {/* Section 2: Printer Configuration */}
        <div className="card" style={{ padding: '24px', textAlign: 'left' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: 0 }}>
            <Settings size={24} /> Printer Configuration
          </h2>
          
          <div style={{ display: 'flex', gap: '24px', marginBottom: '24px' }}>
            {['moonraker', 'octoprint', 'bambu'].map(type => (
              <label key={type} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input 
                  type="radio" 
                  name="printerType" 
                  value={type}
                  checked={printerType === type}
                  onChange={(e) => {
                    setPrinterType(e.target.value);
                    handleSaveConfig('DEFAULT_PRINTER_FIRMWARE', e.target.value);
                  }}
                />
                {type === 'moonraker' ? 'Klipper / Moonraker' : type === 'octoprint' ? 'OctoPrint' : 'Bambu Lab'}
              </label>
            ))}
          </div>

          <div style={{ maxWidth: '500px' }}>
            {printerType === 'moonraker' && (
              <>
                <div className="form-group">
                  <label>Moonraker URL</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="text" 
                      className="input" 
                      value={moonrakerUrl}
                      onChange={e => setMoonrakerUrl(e.target.value)}
                      onBlur={e => handleSaveConfig('MOONRAKER_URL', e.target.value)}
                      placeholder="http://192.168.1.100:7125"
                    />
                    {savingField === 'MOONRAKER_URL' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'MOONRAKER_URL' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
                <div className="form-group">
                  <label>API Key (Optional)</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="password" 
                      className="input" 
                      value={moonrakerKey}
                      onChange={e => setMoonrakerKey(e.target.value)}
                      onBlur={e => {
                        if (e.target.value !== '••••••••') handleSaveConfig('MOONRAKER_API_KEY', e.target.value);
                      }}
                    />
                    {savingField === 'MOONRAKER_API_KEY' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'MOONRAKER_API_KEY' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
              </>
            )}

            {printerType === 'octoprint' && (
              <>
                <div style={{ display: 'flex', gap: '8px', padding: '12px', backgroundColor: 'var(--surface-color)', border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)', marginBottom: '16px' }}>
                  <Info size={20} color="var(--text-secondary)" />
                  <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                    Running OctoPrint on a Raspberry Pi? Enter its local IP above. <a href="#" style={{ color: 'var(--accent-color)', textDecoration: 'underline' }}>See our setup guide →</a>
                  </span>
                </div>
                <div className="form-group">
                  <label>OctoPrint URL</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="text" 
                      className="input" 
                      value={octoprintUrl}
                      onChange={e => setOctoprintUrl(e.target.value)}
                      onBlur={e => handleSaveConfig('OCTOPRINT_URL', e.target.value)}
                      placeholder="http://192.168.1.100:5001"
                    />
                    {savingField === 'OCTOPRINT_URL' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'OCTOPRINT_URL' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
                <div className="form-group">
                  <label>API Key</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="password" 
                      className="input" 
                      value={octoprintKey}
                      onChange={e => setOctoprintKey(e.target.value)}
                      onBlur={e => {
                        if (e.target.value !== '••••••••') handleSaveConfig('OCTOPRINT_API_KEY', e.target.value);
                      }}
                    />
                    {savingField === 'OCTOPRINT_API_KEY' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'OCTOPRINT_API_KEY' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
              </>
            )}

            {printerType === 'bambu' && (
              <>
                <div style={{ display: 'flex', gap: '8px', padding: '12px', backgroundColor: 'var(--surface-color)', border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)', marginBottom: '16px' }}>
                  <Info size={20} color="var(--text-secondary)" />
                  <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                    Enable LAN mode on your Bambu printer: Settings → Network → LAN Mode Liveview
                  </span>
                </div>
                <div className="form-group">
                  <label>IP Address</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="text" 
                      className="input" 
                      value={bambuIp}
                      onChange={e => setBambuIp(e.target.value)}
                      onBlur={e => handleSaveConfig('BAMBU_IP', e.target.value)}
                    />
                    {savingField === 'BAMBU_IP' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'BAMBU_IP' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
                <div className="form-group">
                  <label>LAN Access Code</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input 
                      type="password" 
                      className="input" 
                      value={bambuCode}
                      onChange={e => setBambuCode(e.target.value)}
                      onBlur={e => {
                        if (e.target.value !== '••••••••') handleSaveConfig('BAMBU_CODE', e.target.value);
                      }}
                    />
                    {savingField === 'BAMBU_CODE' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
                    {savedField === 'BAMBU_CODE' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
                  </div>
                </div>
              </>
            )}

            <button 
              className="btn btn-secondary" 
              onClick={testPrinterConnection} 
              disabled={printerTesting || printerType === 'bambu'}
              style={{ marginTop: '8px' }}
            >
              {printerTesting ? <Loader2 className="animate-spin" size={16} /> : 'Test Connection'}
            </button>
            {printerTestResult && (
              <div style={{ color: printerTestResult.success ? 'green' : 'red', marginTop: '8px', fontSize: '14px' }}>
                {printerTestResult.success ? '✓ ' : '✗ '}{printerTestResult.message}
                {printerTestResult.latency && ` (${printerTestResult.latency}ms)`}
              </div>
            )}
          </div>

          <div className="form-group" style={{ marginTop: '32px', maxWidth: '500px' }}>
            <label>Default Profile Selector</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                className="input"
                list="profile-list"
                value={config?.['DEFAULT_PROFILE']?.value || DEFAULT_PROFILES[0]}
                onChange={(e) => handleSaveConfig('DEFAULT_PROFILE', e.target.value)}
                placeholder="pythonsrc/profiles/my_printer.json"
              />
              <datalist id="profile-list">
                {DEFAULT_PROFILES.map(p => <option key={p} value={p} />)}
              </datalist>
              {savingField === 'DEFAULT_PROFILE' && <Loader2 className={styles.spinner} style={{ alignSelf: 'center', minWidth: '16px' }} />}
              {savedField === 'DEFAULT_PROFILE' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
            </div>
          </div>
        </div>

        {/* Section 3: Simulators */}
        <div className="card" style={{ padding: '24px', textAlign: 'left' }}>
          <h2 style={{ marginTop: 0 }}>Simulators</h2>
          <div style={{ border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)', padding: '16px' }}>
            <h3 style={{ marginTop: 0 }}>Moonraker Simulator</h3>
            {simStatusLoading ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)' }}>
                <Loader2 className="animate-spin" size={16} /> Loading simulator status...
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                  <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: simStatus?.moonraker?.running ? 'var(--accent-color)' : 'var(--text-secondary)' }}></div>
                  <span>Status: {simStatus?.moonraker?.running ? 'Running' : 'Stopped'}</span>
                </div>
                
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  {simStatus?.moonraker?.running ? (
                    <>
                      <button className="btn btn-secondary" onClick={() => handleSimAction('moonraker', 'stop')} disabled={simLoading === 'moonraker'}>
                        {simLoading === 'moonraker' ? <Loader2 className={styles.spinner} size={16} /> : 'Stop Simulator'}
                      </button>
                      <span style={{ fontSize: '14px', fontFamily: 'monospace' }}>{simStatus.moonraker.url || 'ws://localhost:7125'}</span>
                      <button
                        className={`btn ${useSimSuccess === 'moonraker' ? 'btn-success' : 'btn-primary'}`}
                        style={useSimSuccess === 'moonraker' ? { backgroundColor: 'var(--success-color)', color: 'white' } : {}}
                        disabled={simLoading === 'moonraker'}
                        onClick={async () => {
                          setPrinterType('moonraker');
                          await handleSaveConfig('DEFAULT_PRINTER_FIRMWARE', 'moonraker');
                          const url = (simStatus.moonraker.url || 'ws://localhost:7125').replace('ws://', 'http://');
                          setMoonrakerUrl(url);
                          await handleSaveConfig('MOONRAKER_URL', url);
                          setUseSimSuccess('moonraker');
                          setTimeout(() => setUseSimSuccess(null), 3000);
                        }}
                      >
                        {useSimSuccess === 'moonraker' ? <><CheckCircle size={16} /> Configured</> : 'Use this simulator'}
                      </button>
                    </>
                  ) : (
                    <button className="btn btn-primary" onClick={() => handleSimAction('moonraker', 'start')} disabled={simLoading === 'moonraker'}>
                        {simLoading === 'moonraker' ? <Loader2 className={styles.spinner} size={16} /> : 'Start Simulator'}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
          <div style={{ border: '1px solid var(--border-color)', borderRadius: 'var(--border-radius)', padding: '16px', marginTop: '16px' }}>
            <h3 style={{ marginTop: 0 }}>OctoPrint Simulator</h3>
            {simStatusLoading ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)' }}>
                <Loader2 className="animate-spin" size={16} /> Loading simulator status...
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
                  <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: simStatus?.octoprint?.running ? 'var(--accent-color)' : 'var(--text-secondary)' }}></div>
                  <span>Status: {simStatus?.octoprint?.running ? 'Running' : 'Stopped'}</span>
                </div>
                
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                  {simStatus?.octoprint?.running ? (
                    <>
                      <button className="btn btn-secondary" onClick={() => handleSimAction('octoprint', 'stop')} disabled={simLoading === 'octoprint'}>
                        {simLoading === 'octoprint' ? <Loader2 className={styles.spinner} size={16} /> : 'Stop Simulator'}
                      </button>
                      <span style={{ fontSize: '14px', fontFamily: 'monospace' }}>{simStatus.octoprint.url || 'http://localhost:5001'}</span>
                      <button
                        className={`btn ${useSimSuccess === 'octoprint' ? 'btn-success' : 'btn-primary'}`}
                        style={useSimSuccess === 'octoprint' ? { backgroundColor: 'var(--success-color)', color: 'white' } : {}}
                        disabled={simLoading === 'octoprint'}
                        onClick={async () => {
                          setPrinterType('octoprint');
                          await handleSaveConfig('DEFAULT_PRINTER_FIRMWARE', 'octoprint');
                          const url = simStatus.octoprint.url || 'http://localhost:5001';
                          setOctoprintUrl(url);
                          await handleSaveConfig('OCTOPRINT_URL', url);
                          if (simStatus.octoprint.api_key) {
                            setOctoprintKey(simStatus.octoprint.api_key);
                            await handleSaveConfig('OCTOPRINT_API_KEY', simStatus.octoprint.api_key);
                          }
                          setUseSimSuccess('octoprint');
                          setTimeout(() => setUseSimSuccess(null), 3000);
                        }}
                      >
                        {useSimSuccess === 'octoprint' ? <><CheckCircle size={16} /> Configured</> : 'Use this simulator'}
                      </button>
                    </>
                  ) : (
                    <button className="btn btn-primary" onClick={() => handleSimAction('octoprint', 'start')} disabled={simLoading === 'octoprint'}>
                        {simLoading === 'octoprint' ? <Loader2 className={styles.spinner} size={16} /> : 'Start Simulator'}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Section 4: Advanced / Developer Settings */}
        <div className="card" style={{ padding: '24px', textAlign: 'left' }}>
          <h2 style={{ marginTop: 0 }}>Advanced / Developer Settings</h2>
          
          <div className="form-group" style={{ maxWidth: '500px' }}>
            <label>PYTHONPATH Override</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input 
                type="text" 
                className="input" 
                placeholder="/path/to/repo"
                value={config?.['PYTHONPATH']?.value || ''}
                onChange={e => {
                  setConfigState(prev => prev ? {...prev, PYTHONPATH: {...(prev.PYTHONPATH || {label:'', description:'', secret:false, required:false, is_set:true}), value: e.target.value}} : null);
                }}
                onBlur={e => handleSaveConfig('PYTHONPATH', e.target.value)}
              />
              {savingField === 'PYTHONPATH' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
              {savedField === 'PYTHONPATH' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
            </div>
          </div>

          <div className="form-group" style={{ maxWidth: '500px', marginTop: '16px' }}>
            <label>Log Level</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <select 
                className="input"
                value={config?.['LOG_LEVEL']?.value || 'INFO'}
                onChange={e => handleSaveConfig('LOG_LEVEL', e.target.value)}
              >
                <option value="INFO">INFO</option>
                <option value="DEBUG">DEBUG</option>
              </select>
              {savingField === 'LOG_LEVEL' && <Loader2 className="animate-spin" style={{ alignSelf: 'center', minWidth: '16px' }} />}
              {savedField === 'LOG_LEVEL' && <span style={{ color: 'green', alignSelf: 'center', fontSize: '14px', whiteSpace: 'nowrap' }}>Saved ✓</span>}
            </div>
          </div>

                  </div>

      </div>
    </div>
  );
}
