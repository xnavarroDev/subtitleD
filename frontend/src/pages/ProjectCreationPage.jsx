import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createProject, listProjects, uploadProjectVideo } from "../api";
import StatusPill from "../components/StatusPill";

export default function ProjectCreationPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [title, setTitle] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("English");
  const [targetLanguage, setTargetLanguage] = useState("Spanish");
  const [minSpeakers, setMinSpeakers] = useState("");
  const [maxSpeakers, setMaxSpeakers] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => setProjects([]));
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
              <input
                value={sourceLanguage}
                onChange={(event) => setSourceLanguage(event.target.value)}
                required
              />
            </label>
            <label>
              <span>Target language</span>
              <input
                value={targetLanguage}
                onChange={(event) => setTargetLanguage(event.target.value)}
                required
              />
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

          <button className="primary-action" disabled={submitting || !title.trim()}>
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
                <Link className="project-row" to={`/projects/${project.id}`} key={project.id}>
                  <div>
                    <strong>{project.title}</strong>
                    <span>
                      {project.source_language} to {project.target_language}
                    </span>
                  </div>
                  <StatusPill status={project.status} />
                </Link>
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
