import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { NewJob } from './pages/NewJob';
import { JobList } from './pages/JobList';
import { JobDetail } from './pages/JobDetail';
import { PrinterSetup } from './pages/PrinterSetup';
import { PrintMonitor } from './pages/PrintMonitor';
import { LayoutDashboard, PlusCircle, Settings, Monitor } from 'lucide-react';
import './index.css';
import styles from './App.module.css';

function Navigation() {
  const location = useLocation();
  
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
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Navigation />
      <main className="container">
        <Routes>
          <Route path="/" element={<NewJob />} />
          <Route path="/dashboard" element={<JobList />} />
          <Route path="/dashboard/:id" element={<JobDetail />} />
          <Route path="/monitor" element={<PrintMonitor />} />
          <Route path="/setup" element={<PrinterSetup />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

export default App;
