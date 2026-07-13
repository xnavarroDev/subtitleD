import { BrowserRouter, Link, Navigate, NavLink, Route, Routes } from "react-router-dom";

import "./App.css";
import ProjectCreationPage from "./pages/ProjectCreationPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <aside className="app-sidebar">
          <Link className="brand" to="/" aria-label="SubtitleD home">
            <BrandLogo />
          </Link>
          <nav className="app-nav" aria-label="Main navigation">
            <NavLink to="/" end>
              <span className="nav-icon" aria-hidden="true">#</span>
              Projects
            </NavLink>
            <Link to="/?new=1">
              <span className="nav-icon" aria-hidden="true">+</span>
              New project
            </Link>
          </nav>
          <div className="sidebar-status">
            <span className="status-dot" />
            Local workspace
          </div>
        </aside>
        <div className="app-content">
          <header className="mobile-topbar">
            <Link className="brand" to="/" aria-label="SubtitleD home">
              <BrandLogo compact />
            </Link>
            <Link className="compact-action" to="/?new=1">New project</Link>
          </header>
          <Routes>
            <Route path="/" element={<ProjectCreationPage />} />
            <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

function BrandLogo({ compact = false }) {
  return (
    <span className={`brand-logo ${compact ? "is-compact" : ""}`} aria-hidden="true">
      <span className="logo-frame logo-frame-dark"><span>S</span></span>
      <span className="logo-middle">ubtitle</span>
      <span className="logo-frame logo-frame-mint"><span>D</span></span>
    </span>
  );
}
