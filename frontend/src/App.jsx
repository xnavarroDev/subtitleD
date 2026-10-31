import { useContext } from "react";
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import "./App.css";
import ProjectCreationPage from "./pages/ProjectCreationPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import DeviceConnection, { DeviceSessionContext } from "./components/DeviceConnection";
import Icon from "./components/Icon";

export default function App() {
  return <BrowserRouter><DeviceConnection><AppShell /></DeviceConnection></BrowserRouter>;
}

function AppShell() {
  const { connected, openSetup, setupPanel, workspaceDirty } = useContext(DeviceSessionContext);
  const location = useLocation();
  const inStudio = location.pathname.startsWith("/projects/");
  return (
    <div className="app-shell" onClickCapture={(event) => {
      const link = event.target.closest("a[href]");
      if (!workspaceDirty || !link || link.target === "_blank" || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const next = new URL(link.href, window.location.href);
      if (next.origin === window.location.origin && next.pathname + next.search !== location.pathname + location.search
          && !window.confirm("Leave the workspace and discard unsaved caption edits?")) event.preventDefault();
    }}>
      <header className="app-topbar">
        <Link className="brand" to="/" aria-label="SubtitleD home"><BrandLogo /></Link>
        <nav className="app-breadcrumb" aria-label="Breadcrumb"><Link to="/">Projects</Link>{inStudio ? <><span>/</span><span>Subtitle studio</span></> : null}</nav>
        <div className="app-topbar-actions">
          <button className={connected ? "device-indicator is-connected" : "device-indicator is-disconnected"} onClick={openSetup} aria-label={connected ? "Device connected · open device settings" : "Device not connected · open setup instructions"} aria-expanded={Boolean(setupPanel)}>{connected ? <span className="connection-dot" /> : <Icon name="warning" />}{connected ? "Connected" : "Not connected"}</button>
          <Link className="button-link new-project-link" to="/?new=1"><Icon name="plus" />New project</Link>
        </div>
      </header>
      <aside className="app-toolrail" aria-label="Main navigation">
        <NavLink to="/" end aria-label="Projects" title="Projects"><Icon name="projects" size={18} /></NavLink>
        {inStudio ? <Link className="active" to={location.pathname} aria-label="Subtitle studio" title="Subtitle studio"><Icon name="captions" size={18} /></Link> : null}
        <Link to="/?new=1" aria-label="New project" title="New project"><Icon name="plus" size={18} /></Link>
        <button onClick={openSetup} aria-label="Device settings" title="Device settings"><Icon name="device" size={18} /></button>
        <span className="rail-local" title="Processing stays on your device"><Icon name="save" size={16} /></span>
      </aside>
      <div className="app-content">
        {setupPanel}
        <Routes>
          <Route path="/" element={<ProjectCreationPage key={String(connected)} />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage key={String(connected)} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

function BrandLogo() {
  return <span className="brand-logo" aria-hidden="true"><span className="brand-first">S</span><span className="brand-colon">:</span><span className="brand-expanded">ubtitle</span><span className="brand-last">D</span></span>;
}
