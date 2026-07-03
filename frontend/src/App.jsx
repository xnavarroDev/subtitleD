import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";

import "./App.css";
import ProjectCreationPage from "./pages/ProjectCreationPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";

export default function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <Link className="brand" to="/">
          SubtitleD
        </Link>
      </header>
      <Routes>
        <Route path="/" element={<ProjectCreationPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
