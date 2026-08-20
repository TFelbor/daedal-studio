import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { NewJob } from './pages/NewJob';
import { JobList } from './pages/JobList';
import { JobDetail } from './pages/JobDetail';
import { PrinterSetup } from './pages/PrinterSetup';
import { PrintMonitor } from './pages/PrintMonitor';
import { OutcomeFeedback } from './components/OutcomeFeedback';
import { LayoutDashboard, PlusCircle, Settings, Monitor, MoonStar, SunMedium } from 'lucide-react';
import { toggleTheme } from './theme';
import styles from './App.module.css';

function Navigation() {
  const location = useLocation();
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'));

  useEffect(() => {
    const updateTheme = () => {
      setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    };

    updateTheme();
    window.addEventListener('themechange', updateTheme);
    return () => window.removeEventListener('themechange', updateTheme);
  }, []);

  return (
    <nav className={styles.nav}>
      <div className={styles.navContainer}>
        <Link to="/" className={styles.logo}>
          P2P
        </Link>
        <div className={styles.navLinks}>
          <Link to="/" className={`${styles.navLink} ${location.pathname === '/' ? styles.active : ''}`}>
            <PlusCircle size={18} /> New Job
          </Link>
          <Link to="/dashboard" className={`${styles.navLink} ${location.pathname.startsWith('/dashboard') ? styles.active : ''}`}>
            <LayoutDashboard size={18} /> Dashboard
          </Link>
          <Link to="/monitor" className={`${styles.navLink} ${location.pathname === '/monitor' ? styles.active : ''}`}>
            <Monitor size={18} /> Monitor
          </Link>
          <Link to="/setup" className={`${styles.navLink} ${location.pathname === '/setup' ? styles.active : ''}`}>
            <Settings size={18} /> Settings
          </Link>
          <button
            type="button"
            className="btn btn-secondary theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <SunMedium size={16} /> : <MoonStar size={16} />}
            <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>
      </div>
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
      <span>Built with DINOv3</span>
      <span className={styles.attributionSep} aria-hidden="true">
        ·
      </span>
      <span>3D reconstruction by TRELLIS.2 (© Microsoft, MIT)</span>
      <span className={styles.attributionSep} aria-hidden="true">
        ·
      </span>
      <span>Blueprints by FLUX.2-klein</span>
    </footer>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Navigation />
      <main className="container">
        {/* Sits in the shell rather than on one page: a user who finished a print and
            navigated elsewhere is exactly the person we need an answer from. */}
        <OutcomeFeedback />
        <Routes>
          <Route path="/" element={<NewJob />} />
          <Route path="/dashboard" element={<JobList />} />
          <Route path="/dashboard/:id" element={<JobDetail />} />
          <Route path="/monitor" element={<PrintMonitor />} />
          <Route path="/setup" element={<PrinterSetup />} />
        </Routes>
      </main>
      <Attribution />
    </BrowserRouter>
  );
}

export default App;
