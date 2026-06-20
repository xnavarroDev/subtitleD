import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createProject,
  deleteProject,
  listLanguages,
  listProjects,
  uploadProjectVideo
} from "../api";
import StatusPill from "../components/StatusPill";

export default function ProjectCreationPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [title, setTitle] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [minSpeakers, setMinSpeakers] = useState("");
  const [maxSpeakers, setMaxSpeakers] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => setProjects([]));
    listLanguages()
      .then((availableLanguages) => {
        setLanguages(availableLanguages);
        const codes = new Set(availableLanguages.map((language) => language.code));
        setSourceLanguage(codes.has("en") ? "en" : availableLanguages[0]?.code || "");
        setTargetLanguage(codes.has("es") ? "es" : availableLanguages[1]?.code || "");
      })
      .catch(() => setError("Could not load the translation provider's languages."));
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!videoFile) {
      setError("Choose a video file first.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        title,
        source_language: sourceLanguage,
        target_language: targetLanguage
      };
      if (minSpeakers.trim()) {
        payload.min_speakers = Number(minSpeakers);
      }
      if (maxSpeakers.trim()) {
        payload.max_speakers = Number(maxSpeakers);
      }

      const project = await createProject(payload);
      await uploadProjectVideo(project.id, videoFile);
      navigate(`/projects/${project.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Project creation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteProject(project) {
    if (!window.confirm(`Delete "${project.title}" and all of its files?`)) {
      return;
    }

    setDeletingProjectId(project.id);
    setError(null);
    try {
      await deleteProject(project.id);
      setProjects((current) =>
        current.filter((candidate) => candidate.id !== project.id)
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Project deletion failed.");
    } finally {
      setDeletingProjectId(null);
    }
  }

  return (
    <main className="page-shell">
      <section className="workspace-grid">
        <form className="panel project-form" onSubmit={handleSubmit}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">New project</p>
              <h1>Create SubtitleD Project</h1>
            </div>
            <StatusPill status="created" />
          </div>

          <label>
            <span>Title</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Launch demo"
              required
            />
          </label>

          <div className="form-row">
            <label>
              <span>Source language</span>
              <select
                value={sourceLanguage}
                onChange={(event) => setSourceLanguage(event.target.value)}
                required
              >
                <option value="auto">Auto-detect</option>
                <option value="" disabled>Select a language</option>
                {languages.map((language) => (
                  <option value={language.code} key={language.code}>
                    {language.name} ({language.code})
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Target language</span>
              <select
                value={targetLanguage}
                onChange={(event) => setTargetLanguage(event.target.value)}
                required
              >
                <option value="" disabled>Select a language</option>
                {languages.map((language) => (
                  <option value={language.code} key={language.code}>
                    {language.name} ({language.code})
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label>
            <span>Video file</span>
            <input
              accept=".mp4,.mov,.webm,.mkv,video/mp4,video/quicktime,video/webm"
              type="file"
              onChange={(event) => setVideoFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>

          <div className="form-row">
            <label>
              <span>Minimum speakers</span>
              <input
                min="1"
                type="number"
                value={minSpeakers}
                onChange={(event) => setMinSpeakers(event.target.value)}
                placeholder="Optional"
              />
            </label>
            <label>
              <span>Maximum speakers</span>
              <input
                min="1"
                type="number"
                value={maxSpeakers}
                onChange={(event) => setMaxSpeakers(event.target.value)}
                placeholder="Optional"
              />
            </label>
          </div>

          {error ? <div className="notice error">{error}</div> : null}

          <button
            className="primary-action"
            disabled={
              submitting || !title.trim() || !sourceLanguage || !targetLanguage
            }
          >
            {submitting ? "Creating..." : "Create and Upload"}
          </button>
        </form>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Projects</p>
              <h2>Recent Work</h2>
            </div>
          </div>
          <div className="project-list">
            {projects.length ? (
              projects.map((project) => (
                <div className="project-row" key={project.id}>
                  <Link
                    className="project-row-link"
                    to={`/projects/${project.id}`}
                  >
                    <div className="project-row-content">
                      <strong>{project.title}</strong>
                      <span>
                        {project.source_language} to {project.target_language}
                      </span>
                    </div>
                    <StatusPill status={project.status} />
                  </Link>
                  <div className="project-row-actions">
                    <button
                      aria-label={`Delete ${project.title}`}
                      className="project-delete-button"
                      disabled={deletingProjectId === project.id}
                      onClick={() => handleDeleteProject(project)}
                      title={`Delete ${project.title}`}
                      type="button"
                    >
                      {"\u00D7"}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">No projects yet.</div>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
