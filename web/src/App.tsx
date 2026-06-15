import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { NewJob } from './pages/NewJob';
import { JobList } from './pages/JobList';
import { JobDetail } from './pages/JobDetail';
import { PrinterSetup } from './pages/PrinterSetup';
import { LayoutDashboard, PlusCircle, Settings } from 'lucide-react';
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
          <Link to="/jobs" className={`${styles.navLink} ${location.pathname.startsWith('/jobs') ? styles.active : ''}`}>
            <LayoutDashboard size={18} /> Dashboard
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
          <Route path="/jobs" element={<JobList />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/setup" element={<PrinterSetup />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

export default App;
