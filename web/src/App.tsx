import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import { NewJob } from './pages/NewJob';
import { JobList } from './pages/JobList';
import { JobDetail } from './pages/JobDetail';
import { PrinterSetup } from './pages/PrinterSetup';
import { PrintMonitor } from './pages/PrintMonitor';
import { WaitingStatesGallery } from './pages/WaitingStatesGallery';
import { OutcomeFeedback } from './components/OutcomeFeedback';
import { GridTrail } from './components/GridTrail';
import { engineLabel, engineStatusClass, useEngineStatus } from './hooks/useEngineStatus';
import logo from './assets/p2p-logo.png';
import styles from './App.module.css';

const NAV_ITEMS = [
  { to: '/', label: 'New job', match: (path: string) => path === '/' },
  { to: '/dashboard', label: 'Dashboard', match: (path: string) => path.startsWith('/dashboard') },
  { to: '/monitor', label: 'Monitor', match: (path: string) => path === '/monitor' },
  { to: '/setup', label: 'Settings', match: (path: string) => path === '/setup' },
];

function Navigation() {
  const { pathname } = useLocation();
  const engine = useEngineStatus();

  return (
    <nav className={styles.nav}>
      <div className={styles.navLeft}>
        <Link to="/" className={styles.brand} aria-label="Prompt2Print">
          <img src={logo} alt="" width={26} height={26} />
        </Link>
        <div className={styles.navLinks}>
          {NAV_ITEMS.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={active ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink}
                aria-current={active ? 'page' : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>
      <span className={engineStatusClass(engine)}>{engineLabel(engine)}</span>
    </nav>
  );
}

function Attribution() {
  // Required, not decorative. TRELLIS.2 conditions on Meta's DINOv3, whose licence
  // permits commercial use only alongside prominent "Built with DINOv3"
  // attribution — and the encoder is on the shape path, so there is no build of
  // this app that does not use it. See THIRD-PARTY-NOTICES.md.
  return (
    <footer className={styles.attribution}>
      <div className={styles.attributionCredits}>
        <span>Built with DINOv3</span>
        <span className={styles.sep} aria-hidden="true">·</span>
        <span>3D reconstruction by TRELLIS.2 (© Microsoft, MIT)</span>
        <span className={styles.sep} aria-hidden="true">·</span>
        <span>Blueprints by FLUX.2-klein</span>
      </div>
      <span className={styles.plate}>PROMPT2PRINT</span>
    </footer>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Navigation />
      <main className="surface">
        {/* The surface grid is drawn in CSS; this only lights the module under the
            pointer, and only where the surface is bare. */}
        <GridTrail />
        {/* Sits in the shell rather than on one page: a user who finished a print and
            navigated elsewhere is exactly the person we need an answer from. */}
        <OutcomeFeedback />
        <Routes>
          <Route path="/" element={<NewJob />} />
          <Route path="/dashboard" element={<JobList />} />
          <Route path="/dashboard/:id" element={<JobDetail />} />
          <Route path="/monitor" element={<PrintMonitor />} />
          <Route path="/setup" element={<PrinterSetup />} />
          {/* Every waiting state on one page, for reviewing them without sitting
              through a five-phase run. Dev-only: the guard is what keeps a review
              harness out of the shipped app. */}
          {import.meta.env.DEV && (
            <Route path="/states" element={<WaitingStatesGallery />} />
          )}
          {/* A mistyped URL used to render an empty page. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Attribution />
    </BrowserRouter>
  );
}

export default App;
