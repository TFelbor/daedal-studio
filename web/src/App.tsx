import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import { NewJob } from './pages/NewJob';
import { JobList } from './pages/JobList';
import { JobDetail } from './pages/JobDetail';
import { PrinterSetup } from './pages/PrinterSetup';
import { PrintMonitor } from './pages/PrintMonitor';
import { OutcomeFeedback } from './components/OutcomeFeedback';
import { GridTrail } from './components/GridTrail';
import { ThemeToggle } from './components/ThemeToggle';
import { Wordmark } from './components/Wordmark';
import { engineLabel, engineStatusClass, useEngineStatus } from './hooks/useEngineStatus';
import styles from './App.module.css';

const NAV_ITEMS = [
  { to: '/', label: 'Create', match: (path: string) => path === '/' },
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
        <Link to="/" className={styles.brand} aria-label="Daedal Studio">
          <Wordmark size={26} wordsClassName={styles.brandWords} />
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
      <div className={styles.navRight}>
        {/* Below 720px only the dot survives — "Printer unreachable" is ~150px of a
            375px bar and it was pushing the nav links out of their scroller. The
            colour is the signal; the words are the explanation, and the title
            keeps them reachable when they are not on screen. */}
        <span className={engineStatusClass(engine)} title={engineLabel(engine)}>
          <span className={styles.engineLabel}>{engineLabel(engine)}</span>
        </span>
        <ThemeToggle />
      </div>
    </nav>
  );
}

/** The four claims, and the machine credits that are not claims but obligations. */
function Attribution() {
  return (
    <footer className={styles.attribution}>
      <div className={styles.attributionInner}>
        {/* The trust line. Every one of these is a promise this audience has been
            burned on before — AI art in tabletop, black-box meshes, untested files
            flooding the marketplaces — so each is phrased as something checkable
            rather than as a slogan, and each has to stay true of the code. */}
        <div className={styles.attributionCredits}>
          <span>Functional geometry only — no AI art, ever</span>
          <span className={styles.sep} aria-hidden="true">·</span>
          <span>Editable parameters, not a black box</span>
          <span className={styles.sep} aria-hidden="true">·</span>
          <span>Every archetype print-tested on FDM</span>
          <span className={styles.sep} aria-hidden="true">·</span>
          <span>Prompts kept with the job</span>
        </div>
        {/* Required, not decorative, and deliberately *not* removed with the pivot
            copy above it. The generative branch is benched on the roadmap but it is
            still what runs: TRELLIS.2 conditions on Meta's DINOv3, whose licence
            permits commercial use only alongside prominent "Built with DINOv3"
            attribution, and the encoder is on the shape path of every job this
            build can run. It comes out when the code does, not before.
            See THIRD-PARTY-NOTICES.md. */}
        <div className={styles.attributionMachines}>
          <span>Built with DINOv3</span>
          <span className={styles.sep} aria-hidden="true">·</span>
          <span>3D reconstruction by TRELLIS.2 (© Microsoft, MIT)</span>
          <span className={styles.sep} aria-hidden="true">·</span>
          <span>Blueprints by FLUX.2-klein</span>
        </div>
      </div>
      <span className={styles.plate}>DAEDAL_STUDIO</span>
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
          {/* A mistyped URL used to render an empty page. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Attribution />
    </BrowserRouter>
  );
}

export default App;
