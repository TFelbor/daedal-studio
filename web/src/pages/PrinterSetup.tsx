import { useEffect, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Eye,
  EyeOff,
  Loader2,
  Play,
  Square,
} from 'lucide-react';
import { Blueprint, Marks } from '../components/Blueprint';
import { BootMark } from '../components/BootMark';
import {
  getConfig,
  setConfig,
  revealConfig,
  testConnection,
  getSimulatorStatus,
  startSimulator,
  stopSimulator,
} from '../api/config';
import type { ConfigResponse, SimulatorStatus } from '../api/config';
import styles from './PrinterSetup.module.css';

/** What the server sends back in place of a stored secret. */
const MASK = '••••••••';

const DEFAULT_PROFILES = [
  'pythonsrc/profiles/anycubic_mega.json',
  'pythonsrc/profiles/bambu_test.json',
  'pythonsrc/profiles/ender3.json',
  'pythonsrc/profiles/klipper_test.json',
];

/** The four sections, in order. The index on the left is generated from this, so
 *  a section and its number can never disagree. */
const SECTIONS = [
  { id: 'settings-models', num: '01', title: 'Spec engine' },
  { id: 'settings-printer', num: '02', title: 'Printer' },
  { id: 'settings-simulators', num: '03', title: 'Simulators' },
  { id: 'settings-developer', num: '04', title: 'Developer' },
];

type PrinterKind = 'moonraker' | 'octoprint' | 'bambu';

const PRINTER_KINDS: { kind: PrinterKind; label: string }[] = [
  { kind: 'moonraker', label: 'Klipper / Moonraker' },
  { kind: 'octoprint', label: 'OctoPrint' },
  { kind: 'bambu', label: 'Bambu Lab' },
];

/** Which segment a stored firmware name belongs to. Profiles say `klipper` where
 *  this page says `moonraker`; both are the same machine. */
function printerKind(firmware: string): PrinterKind {
  if (firmware === 'octoprint') return 'octoprint';
  if (firmware === 'bambu') return 'bambu';
  return 'moonraker';
}

/**
 * The *service* to probe for a firmware.
 *
 * `/config/test-connection` takes service names: Moonraker is the HTTP API in
 * front of Klipper. Handing it a firmware name is why this test used to fail
 * permanently for Klipper. Bambu has a probe now too — a TCP connect to its LAN
 * MQTT port — so every firmware is checkable and none of them is assumed good.
 */
function probeService(firmware: string): 'moonraker' | 'octoprint' | 'bambu' {
  return printerKind(firmware);
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

type Overall = 'loading' | 'checking' | 'ready' | 'error' | 'incomplete';

const OVERALL_LABEL: Record<Overall, string> = {
  loading: 'Loading',
  checking: 'Checking',
  ready: 'Ready',
  error: 'Not ready',
  incomplete: 'Incomplete',
};

const OVERALL_CLASS: Record<Overall, string> = {
  loading: 'status status-off',
  checking: 'status status-run',
  ready: 'status status-ok',
  error: 'status status-bad',
  incomplete: 'status status-bad',
};

interface TestResult {
  success: boolean;
  message: string;
  latency?: number | null;
}

export function PrinterSetup() {
  const [config, setConfigState] = useState<ConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeSection, setActiveSection] = useState(SECTIONS[0].id);

  const [simStatus, setSimStatus] = useState<SimulatorStatus | null>(null);
  const [simStatusLoading, setSimStatusLoading] = useState(true);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const [simConfigured, setSimConfigured] = useState(false);

  const [printerType, setPrinterType] = useState('moonraker');

  const [hfTokenInput, setHfTokenInput] = useState('');
  const [showHfToken, setShowHfToken] = useState(false);
  const [hfTestResult, setHfTestResult] = useState<TestResult | null>(null);
  const [hfTesting, setHfTesting] = useState(false);

  const [moonrakerUrl, setMoonrakerUrl] = useState('');
  const [moonrakerKey, setMoonrakerKey] = useState('');
  const [octoprintUrl, setOctoprintUrl] = useState('');
  const [octoprintKey, setOctoprintKey] = useState('');
  const [bambuIp, setBambuIp] = useState('');
  const [bambuCode, setBambuCode] = useState('');
  const [profileInput, setProfileInput] = useState('');

  const [printerTestResult, setPrinterTestResult] = useState<TestResult | null>(null);
  const [printerTesting, setPrinterTesting] = useState(false);

  const [savingField, setSavingField] = useState<string | null>(null);
  const [savedField, setSavedField] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [overall, setOverall] = useState<Overall>('loading');
  const [overallMessage, setOverallMessage] = useState<string | null>(null);

  useEffect(() => {
    void fetchData();
    void fetchSimStatus();
    const interval = setInterval(() => void fetchSimStatus(), 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      if (data['BAMBU_IP']?.value) setBambuIp(data['BAMBU_IP'].value);
      if (data['BAMBU_CODE']?.is_set) setBambuCode(data['BAMBU_CODE'].value || '');
      // Buffered locally rather than driven straight off the response: these two
      // are typed into, and a refetch mid-sentence would overwrite the caret.
      setProfileInput(data['DEFAULT_PROFILE']?.value || '');
    } catch (e) {
      setOverall('error');
      setOverallMessage(`Settings could not be loaded — ${errorMessage(e, 'the API server did not answer')}.`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!loading && config) {
      void runOverallChecks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, config, printerType]);

  /** Mark the section the reader is actually looking at in the left index. */
  useEffect(() => {
    if (loading) return;
    const elements = SECTIONS
      .map((section) => document.getElementById(section.id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (first) setActiveSection(first.target.id);
      },
      { rootMargin: '-96px 0px -55% 0px' }
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [loading]);

  const runOverallChecks = async () => {
    if (!config) return;

    const hfSet = config['HF_TOKEN']?.is_set;
    const skipViz = config['SKIP_VISUALIZER']?.value === 'true';
    const skipSculpt = config['SKIP_SCULPTOR']?.value === 'true';

    if (!hfSet && !skipViz) {
      setOverall('incomplete');
      setOverallMessage('No HuggingFace token yet — Phase 1 cannot fetch the FLUX weights without one. Add it under Spec engine.');
      return;
    }

    const printerSet =
      config['MOONRAKER_URL']?.value ||
      config['OCTOPRINT_URL']?.value ||
      config['BAMBU_IP']?.value ||
      (skipViz && skipSculpt);

    if (!printerSet) {
      setOverall('incomplete');
      setOverallMessage('No printer address yet — add one under Printer, or start the OctoPrint simulator under Simulators.');
      return;
    }

    setOverall('checking');
    setOverallMessage(null);

    if (!skipViz) {
      try {
        const hfRes = await testConnection('huggingface');
        if (!hfRes.success) {
          setOverall('error');
          setOverallMessage(`HuggingFace refused the token — ${hfRes.message}.`);
          return;
        }
      } catch (e) {
        setOverall('error');
        setOverallMessage(`HuggingFace check failed — ${errorMessage(e, 'the API server did not answer')}.`);
        return;
      }
    }

    // Every firmware is probed. This used to skip the check for Bambu and fall
    // straight through to "Ready", so the pill went green before anything had been
    // connected — it was reporting an assumption as a verified fact.
    try {
      const printerRes = await testConnection(probeService(printerType));
      if (!printerRes.success) {
        setOverall('error');
        setOverallMessage(`Printer connection failed — ${printerRes.message}`);
        return;
      }
      setOverall('ready');
      setOverallMessage(null);
    } catch (e) {
      setOverall('error');
      setOverallMessage(`Printer check failed — ${errorMessage(e, 'the API server did not answer')}.`);
    }
  };

  const fetchSimStatus = async () => {
    try {
      const status = await getSimulatorStatus();
      setSimStatus(status);
    } catch {
      // A polled status that failed once is not worth a banner; the next tick retries.
    } finally {
      setSimStatusLoading(false);
    }
  };

  const saveConfigValue = async (key: string, value: string) => {
    setSavingField(key);
    try {
      await setConfig(key, value);
      setSavedField(key);
      setTimeout(() => setSavedField(null), 2000);

      const data = await getConfig();
      setConfigState(data);
    } catch (e) {
      setSaveError(`${key} was not saved — ${errorMessage(e, 'the API server refused the change')}.`);
      setTimeout(() => setSaveError(null), 5000);
    } finally {
      setSavingField(null);
    }
  };

  /** Save a plain field on blur, but only when its value actually changed. */
  const commitValue = (key: string, value: string) => {
    if (value === (config?.[key]?.value ?? '')) return;
    void saveConfigValue(key, value);
  };

  /**
   * Save a secret on blur.
   *
   * An empty box means "left alone", never "erase the stored one" — tabbing
   * through a masked field must not overwrite a key nobody can see to retype.
   */
  const commitSecret = (key: string, value: string) => {
    if (!value.trim() || value === MASK) return;
    void saveConfigValue(key, value);
  };

  const handleSimAction = async (action: 'start' | 'stop') => {
    setSimBusy(true);
    setSimError(null);
    try {
      if (action === 'start') await startSimulator('octoprint');
      else await stopSimulator('octoprint');
      setTimeout(() => void fetchSimStatus(), 500);
    } catch (e) {
      setSimError(
        action === 'start'
          ? `The OctoPrint simulator did not start — ${errorMessage(e, 'Docker did not answer')}. Is Docker running?`
          : `The OctoPrint simulator did not stop — ${errorMessage(e, 'Docker did not answer')}.`
      );
      setTimeout(() => setSimError(null), 6000);
    } finally {
      setSimBusy(false);
    }
  };

  const applyOctoprintSimulator = async () => {
    if (!simStatus?.octoprint) return;
    setPrinterType('octoprint');
    await saveConfigValue('DEFAULT_PRINTER_FIRMWARE', 'octoprint');

    const url = simStatus.octoprint.url || 'http://localhost:5001';
    setOctoprintUrl(url);
    await saveConfigValue('OCTOPRINT_URL', url);

    if (simStatus.octoprint.api_key) {
      setOctoprintKey(simStatus.octoprint.api_key);
      await saveConfigValue('OCTOPRINT_API_KEY', simStatus.octoprint.api_key);
    }

    setSimConfigured(true);
    setTimeout(() => setSimConfigured(false), 3000);
  };

  const toggleReveal = async (
    key: string,
    setter: Dispatch<SetStateAction<string>>,
    shown: boolean,
    setShown: Dispatch<SetStateAction<boolean>>
  ) => {
    if (shown) {
      setShown(false);
      setter(MASK);
      return;
    }
    try {
      setter(await revealConfig(key));
      setShown(true);
    } catch (e) {
      setSaveError(`${key} could not be revealed — ${errorMessage(e, 'the API server refused')}.`);
      setTimeout(() => setSaveError(null), 5000);
    }
  };

  const testHfConnection = async () => {
    setHfTesting(true);
    setHfTestResult(null);
    try {
      const res = await testConnection('huggingface');
      setHfTestResult({ success: res.success, message: res.message });
    } catch (e) {
      setHfTestResult({ success: false, message: errorMessage(e, 'The API server did not answer') });
    } finally {
      setHfTesting(false);
    }
  };

  const testPrinterConnection = async () => {
    const service = probeService(printerType);
    if (!service) return;

    setPrinterTesting(true);
    setPrinterTestResult(null);
    try {
      const res = await testConnection(service);
      setPrinterTestResult({ success: res.success, message: res.message, latency: res.latency_ms });
    } catch (e) {
      setPrinterTestResult({ success: false, message: errorMessage(e, 'The API server did not answer') });
    } finally {
      setPrinterTesting(false);
    }
  };

  /**
   * Where a stored printer key is allowed to go, under its field.
   *
   * A key is bound to the host it was saved beside, so changing the URL alone stops
   * it being sent — an extra step, and one nobody would guess at from a probe that
   * merely says the printer rejected the credential. Shown for a stored key only:
   * there is nothing to explain about a field nobody has filled in.
   */
  const hostBinding = (key: string): ReactNode => {
    const binding = config?.[key]?.host_binding;
    if (!binding || !config?.[key]?.is_set) return null;
    if (binding.sends) {
      return (
        <p className={styles.bindingNote}>Key bound to {binding.bound_to}.</p>
      );
    }
    if (!binding.target) return null;
    return (
      <p className={`${styles.bindingNote} ${styles.bindingNoteWarn}`}>
        <AlertTriangle size={12} strokeWidth={1.5} />
        {binding.message ?? `The key is not bound to ${binding.target}.`}
      </p>
    );
  };

  /** Saving / Saved, rendered in a field's label line. */
  const fieldState = (key: string): ReactNode => {
    if (savingField === key) {
      return (
        <span className={styles.fieldState}>
          <Loader2 className="spin" size={11} strokeWidth={1.5} />
          Saving
        </span>
      );
    }
    if (savedField === key) {
      return <span className={`${styles.fieldState} ${styles.fieldStateSaved}`}>Saved</span>;
    }
    return null;
  };

  const renderResult = (result: TestResult) => (
    <p className={`${styles.result} ${result.success ? styles.resultOk : styles.resultBad}`}>
      {result.message}
      {result.success && result.latency ? ` · ${result.latency} ms` : ''}
    </p>
  );

  if (loading) {
    return (
      <div className="sheet">
        <h1 className="display">Settings</h1>
        <BootMark block label="Reading configuration" />
      </div>
    );
  }

  const kind = printerKind(printerType);
  // Every firmware has a probe now, including Bambu.
  const canProbePrinter = true;
  const noticeMessage = overall === 'error' || overall === 'incomplete' ? overallMessage : null;
  const octoRunning = simStatus?.octoprint?.running === true;
  const octoUrl = simStatus?.octoprint?.url || 'http://localhost:5001';

  return (
    <div className="sheet">
      <div className={styles.page}>
        {/* ── The index. Four numbered rows; the one you are reading is accent. ── */}
        <div className={styles.index}>
          <h1 className={`display ${styles.indexTitle}`}>Settings</h1>
          <nav className={styles.indexList} aria-label="Settings sections">
            {SECTIONS.map((section) => {
              const active = section.id === activeSection;
              return (
                <a
                  key={section.id}
                  href={`#${section.id}`}
                  className={active ? `${styles.indexRow} ${styles.indexRowActive}` : styles.indexRow}
                  aria-current={active ? 'true' : undefined}
                >
                  <span className={styles.indexNum}>{section.num}</span>
                  {section.title}
                </a>
              );
            })}
          </nav>
          <div className={styles.indexStatus}>
            <span className={OVERALL_CLASS[overall]}>{OVERALL_LABEL[overall]}</span>
          </div>
        </div>

        <div className={styles.body}>
          {(saveError || noticeMessage) && (
            <div className={styles.notices}>
              {saveError && (
                <div className="notice">
                  <AlertCircle size={15} strokeWidth={1.5} />
                  <div>{saveError}</div>
                </div>
              )}
              {noticeMessage && (
                <div className="notice">
                  {overall === 'incomplete' ? (
                    <AlertTriangle size={15} strokeWidth={1.5} />
                  ) : (
                    <AlertCircle size={15} strokeWidth={1.5} />
                  )}
                  <div>{noticeMessage}</div>
                </div>
              )}
            </div>
          )}

          {/* ── 01 Spec engine ────────────────────────────────────────────── */}
          <section id={SECTIONS[0].id} className={styles.section}>
            <div className={styles.sectionHead}>
              <span className={styles.sectionNum}>{SECTIONS[0].num}</span>
              <h2 className="heading">{SECTIONS[0].title}</h2>
              <span className={styles.sectionTag}>LLM · DIMENSION KB</span>
            </div>

            <div className={styles.sectionBody}>
              {/* What this section will hold. There is nothing to configure yet —
                  no LLM is called and no dimension KB is shipped — so it says that
                  instead of offering a key field that writes to a setting nothing
                  reads. An input that silently does nothing is worse than an
                  absence: it looks configured. */}
              <div className={styles.pendingBlock}>
                <span className="label">Spec engine · not yet wired</span>
                <p className="hint">
                  The composer will take one LLM call per job to read words into a spec, and
                  the compiler will size that spec against a dimension knowledge base of
                  sleeve, card and dice measurements. Neither exists in this build — the
                  parametric engine is roadmap §§0.1–7A. The model never produces geometry;
                  it only reads words into numbers.
                </p>
              </div>

              {/* Benched, not deleted. The generative path is off the critical path
                  in the roadmap but it is still what every job in this build runs,
                  so its credentials stay configurable and stay honestly labelled. */}
              <div className={styles.pendingBlock}>
                <span className="label">Generative branch · benched</span>
                <p className="hint">
                  Decorative lids and embossing, off the critical path — and, until the
                  parametric engine lands, still what phases 01 and 02 actually run.
                </p>
              </div>

              <div className="field">
                <div className={styles.fieldHead}>
                  <label className="field-label" htmlFor="hf-token">
                    HuggingFace token
                  </label>
                  {fieldState('HF_TOKEN')}
                </div>
                <div className={styles.row}>
                  <input
                    id="hf-token"
                    className={`input ${styles.rowInput}`}
                    type={showHfToken ? 'text' : 'password'}
                    value={hfTokenInput}
                    placeholder="hf_..."
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(e) => setHfTokenInput(e.target.value)}
                    onBlur={(e) => commitSecret('HF_TOKEN', e.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-label={showHfToken ? 'Hide the token' : 'Show the token'}
                    onClick={() => void toggleReveal('HF_TOKEN', setHfTokenInput, showHfToken, setShowHfToken)}
                  >
                    {showHfToken ? <EyeOff size={15} strokeWidth={1.5} /> : <Eye size={15} strokeWidth={1.5} />}
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary blueprint marked-accent"
                    onClick={() => void testHfConnection()}
                    disabled={hfTesting}
                  >
                    <Marks />
                    {hfTesting ? <Loader2 className="spin" size={15} strokeWidth={1.5} /> : 'Verify'}
                  </button>
                </div>
                <p className="hint">
                  Required to download the FLUX base model. Get one at{' '}
                  <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">
                    huggingface.co/settings/tokens
                  </a>
                  .
                </p>
                {hfTestResult && renderResult(hfTestResult)}
              </div>

              <div className={styles.toggleBox}>
                {[
                  {
                    key: 'SKIP_VISUALIZER',
                    name: 'Skip visualizer',
                    caption: 'Phase 01 — use an existing blueprint',
                  },
                  {
                    key: 'SKIP_SCULPTOR',
                    name: 'Skip sculptor',
                    caption: 'Phase 02 — use an existing mesh',
                  },
                ].map((toggle) => (
                  <label key={toggle.key} className={styles.toggleCell}>
                    <span>
                      <span className={styles.toggleName}>{toggle.name}</span>
                      <span className={styles.toggleCaption}>{toggle.caption}</span>
                    </span>
                    {savingField === toggle.key && <Loader2 className="spin" size={13} strokeWidth={1.5} />}
                    <input
                      type="checkbox"
                      className={styles.toggleInput}
                      checked={config?.[toggle.key]?.value === 'true'}
                      onChange={(e) => void saveConfigValue(toggle.key, e.target.checked ? 'true' : 'false')}
                    />
                    <span className={styles.switch}>
                      <span className={styles.switchKnob} />
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </section>

          {/* ── 02 Printer ────────────────────────────────────────────────── */}
          <section id={SECTIONS[1].id} className={styles.section}>
            <div className={styles.sectionHead}>
              <span className={styles.sectionNum}>{SECTIONS[1].num}</span>
              <h2 className="heading">{SECTIONS[1].title}</h2>
            </div>

            <div className={styles.sectionBody}>
              <div className="seg" role="group" aria-label="Printer firmware">
                {PRINTER_KINDS.map((option) => (
                  <button
                    key={option.kind}
                    type="button"
                    className={kind === option.kind ? 'is-active' : undefined}
                    aria-pressed={kind === option.kind}
                    onClick={() => {
                      setPrinterType(option.kind);
                      void saveConfigValue('DEFAULT_PRINTER_FIRMWARE', option.kind);
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              {kind === 'moonraker' && (
                <div className={styles.fieldGrid}>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="moonraker-url">
                        Moonraker URL
                      </label>
                      {fieldState('MOONRAKER_URL')}
                    </div>
                    <input
                      id="moonraker-url"
                      className="input"
                      type="text"
                      value={moonrakerUrl}
                      placeholder="http://192.168.1.100:7125"
                      spellCheck={false}
                      onChange={(e) => setMoonrakerUrl(e.target.value)}
                      onBlur={(e) => commitValue('MOONRAKER_URL', e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="moonraker-key">
                        API key (optional)
                      </label>
                      {fieldState('MOONRAKER_API_KEY')}
                    </div>
                    <input
                      id="moonraker-key"
                      className="input"
                      type="password"
                      value={moonrakerKey}
                      autoComplete="off"
                      onChange={(e) => setMoonrakerKey(e.target.value)}
                      onBlur={(e) => commitSecret('MOONRAKER_API_KEY', e.target.value)}
                    />
                    {hostBinding('MOONRAKER_API_KEY')}
                  </div>
                </div>
              )}

              {kind === 'octoprint' && (
                <div className={styles.fieldGrid}>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="octoprint-url">
                        OctoPrint URL
                      </label>
                      {fieldState('OCTOPRINT_URL')}
                    </div>
                    <input
                      id="octoprint-url"
                      className="input"
                      type="text"
                      value={octoprintUrl}
                      placeholder="http://192.168.1.100:5001"
                      spellCheck={false}
                      onChange={(e) => setOctoprintUrl(e.target.value)}
                      onBlur={(e) => commitValue('OCTOPRINT_URL', e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="octoprint-key">
                        API key
                      </label>
                      {fieldState('OCTOPRINT_API_KEY')}
                    </div>
                    <input
                      id="octoprint-key"
                      className="input"
                      type="password"
                      value={octoprintKey}
                      autoComplete="off"
                      onChange={(e) => setOctoprintKey(e.target.value)}
                      onBlur={(e) => commitSecret('OCTOPRINT_API_KEY', e.target.value)}
                    />
                    {hostBinding('OCTOPRINT_API_KEY')}
                  </div>
                </div>
              )}

              {kind === 'bambu' && (
                <div className={styles.fieldGrid}>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="bambu-ip">
                        IP address
                      </label>
                      {fieldState('BAMBU_IP')}
                    </div>
                    <input
                      id="bambu-ip"
                      className="input"
                      type="text"
                      value={bambuIp}
                      placeholder="192.168.1.150"
                      spellCheck={false}
                      onChange={(e) => setBambuIp(e.target.value)}
                      onBlur={(e) => commitValue('BAMBU_IP', e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <div className={styles.fieldHead}>
                      <label className="field-label" htmlFor="bambu-code">
                        LAN access code
                      </label>
                      {fieldState('BAMBU_CODE')}
                    </div>
                    <input
                      id="bambu-code"
                      className="input"
                      type="password"
                      value={bambuCode}
                      autoComplete="off"
                      onChange={(e) => setBambuCode(e.target.value)}
                      onBlur={(e) => commitSecret('BAMBU_CODE', e.target.value)}
                    />
                    {hostBinding('BAMBU_CODE')}
                  </div>
                </div>
              )}

              <div className="field">
                <div className={styles.fieldHead}>
                  <label className="field-label" htmlFor="default-profile">
                    Default slicing profile
                  </label>
                  {fieldState('DEFAULT_PROFILE')}
                </div>
                <input
                  id="default-profile"
                  className="input"
                  type="text"
                  list="ds-profile-list"
                  value={profileInput}
                  placeholder={DEFAULT_PROFILES[0]}
                  spellCheck={false}
                  onChange={(e) => setProfileInput(e.target.value)}
                  onBlur={(e) => commitValue('DEFAULT_PROFILE', e.target.value)}
                />
                <datalist id="ds-profile-list">
                  {DEFAULT_PROFILES.map((profile) => (
                    <option key={profile} value={profile} />
                  ))}
                </datalist>
              </div>

              <div className={styles.testRow}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void testPrinterConnection()}
                  disabled={printerTesting || !canProbePrinter}
                >
                  {printerTesting ? (
                    <>
                      <Loader2 className="spin" size={14} strokeWidth={1.5} />
                      Testing
                    </>
                  ) : (
                    'Test connection'
                  )}
                </button>
                <p className="hint">
                  {kind === 'octoprint' && 'Running OctoPrint on a Pi? Use its local IP.'}
                  {kind === 'moonraker' && 'Moonraker is the HTTP API in front of Klipper — port 7125 on the printer host.'}
                  {kind === 'bambu' &&
                    'Checks the printer answers on its LAN MQTT port. The access code is only proven when a print is sent. Enable LAN mode first: Settings → Network → LAN Mode Liveview.'}
                </p>
              </div>
              {printerTestResult && renderResult(printerTestResult)}
            </div>
          </section>

          {/* ── 03 Simulators ─────────────────────────────────────────────── */}
          <section id={SECTIONS[2].id} className={styles.section}>
            <div className={styles.sectionHead}>
              <span className={styles.sectionNum}>{SECTIONS[2].num}</span>
              <h2 className="heading">{SECTIONS[2].title}</h2>
              <span className={styles.sectionNote}>For testing without hardware</span>
            </div>

            <div className={styles.sectionBody}>
              <div className={styles.simGrid}>
                {/* There is no Moonraker simulator: the server's start/stop are
                    deprecated stubs that always report not-running. A Start
                    button here would be a control that can never work. */}
                <Blueprint className={styles.simCard}>
                  <div className={styles.simHead}>
                    <div>
                      <span className={styles.simName}>Moonraker</span>
                    </div>
                    <span className="status status-off">Not available</span>
                  </div>
                  <p className={styles.simNote}>
                    This build ships no Moonraker simulator. Use the OctoPrint simulator, or point the Klipper
                    settings at a real Moonraker host.
                  </p>
                </Blueprint>

                <Blueprint className={styles.simCard}>
                  <div className={styles.simHead}>
                    <div>
                      <span className={styles.simName}>OctoPrint</span>
                      {octoRunning && <span className={styles.simUrl}>{octoUrl}</span>}
                    </div>
                    <span className={octoRunning ? 'status status-ok' : 'status status-off'}>
                      {simStatusLoading ? 'Checking' : octoRunning ? 'Running' : 'Stopped'}
                    </span>
                  </div>
                  <div className={styles.simActions}>
                    {octoRunning ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          onClick={() => void handleSimAction('stop')}
                          disabled={simBusy}
                        >
                          {simBusy ? (
                            <Loader2 className="spin" size={13} strokeWidth={1.5} />
                          ) : (
                            <>
                              <Square size={13} strokeWidth={1.5} />
                              Stop
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          className={simConfigured ? 'btn btn-ok' : 'btn btn-primary blueprint marked-accent'}
                          onClick={() => void applyOctoprintSimulator()}
                          disabled={simBusy}
                        >
                          {simConfigured ? (
                            <>
                              <CheckCircle size={14} strokeWidth={1.5} />
                              Configured
                            </>
                          ) : (
                            <>
                              <Marks />
                              Use this simulator
                            </>
                          )}
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => void handleSimAction('start')}
                        disabled={simBusy || simStatusLoading}
                      >
                        {simBusy ? (
                          <Loader2 className="spin" size={13} strokeWidth={1.5} />
                        ) : (
                          <>
                            <Play size={13} strokeWidth={1.5} />
                            Start
                          </>
                        )}
                      </button>
                    )}
                  </div>
                </Blueprint>
              </div>

              {simError && (
                <div className="notice">
                  <AlertCircle size={15} strokeWidth={1.5} />
                  <div>{simError}</div>
                </div>
              )}
            </div>
          </section>

          {/* ── 04 Developer ──────────────────────────────────────────────── */}
          <section id={SECTIONS[3].id} className={styles.section}>
            <div className={styles.sectionHead}>
              <span className={styles.sectionNum}>{SECTIONS[3].num}</span>
              <h2 className="heading">{SECTIONS[3].title}</h2>
            </div>

            {/* The PYTHONPATH override that used to sit here is gone, and so is the
                key behind it. Every value saved on this page is handed to the
                pipeline container and to the operator, and an import path is one
                the image sets — not one anyone should be able to set over an
                unauthenticated HTTP request. */}
            <div className={styles.devGrid}>
              <div className="field">
                <div className={styles.fieldHead}>
                  <label className="field-label" htmlFor="log-level">
                    Log level
                  </label>
                  {fieldState('LOG_LEVEL')}
                </div>
                <select
                  id="log-level"
                  className="select"
                  value={config?.['LOG_LEVEL']?.value || 'INFO'}
                  onChange={(e) => void saveConfigValue('LOG_LEVEL', e.target.value)}
                >
                  <option value="INFO">INFO</option>
                  <option value="DEBUG">DEBUG</option>
                </select>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
