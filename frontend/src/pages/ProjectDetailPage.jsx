import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  absoluteFileUrl,
  exportProjectSrt,
  getProject,
  getProjectStatus,
  processProject,
  renderProject
} from "../api";
import ProjectMeta from "../components/ProjectMeta";
import StatusPill from "../components/StatusPill";
import SubtitleEditor from "../components/SubtitleEditor";
import VideoPreview from "../components/VideoPreview";
import "./ProjectDetailPage.css";

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [error, setError] = useState(null);
  const [busyAction, setBusyAction] = useState(null);

  const loadProject = useCallback(async () => {
    if (projectId) setProject(await getProject(projectId));
  }, [projectId]);

  useEffect(() => {
    loadProject().catch((caught) => setError(caught instanceof Error ? caught.message : "Project load failed."));
  }, [loadProject]);

  useEffect(() => {
    if (!projectId || !project || !isActiveJob(project)) return undefined;
    const intervalId = window.setInterval(async () => {
      try {
        const status = await getProjectStatus(projectId);
        setProject((current) => current ? { ...current, ...status } : current);
        if (!isActiveJob(status)) await loadProject();
      } catch {
        // Keep the current project visible while polling retries.
      }
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [loadProject, project, projectId]);

  async function runAction(label, action) {
    setBusyAction(label);
    setError(null);
    try {
      await action();
      await loadProject();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `${label} failed.`);
    } finally {
      setBusyAction(null);
    }
  }

  if (!projectId) return null;
  if (!project) return <main className="page-shell"><div className="panel empty-state">Loading project...</div></main>;

  const hasSegments = project.status === "processed" || project.status === "rendered";
  const canPublishSegments = hasSegments && !project.translation_needs_reprocessing;
  const progress = project.translation_progress || { completed: 0, total: 0 };
  const downloadUrl = absoluteFileUrl(project.download_url);
  const srtUrl = absoluteFileUrl(project.srt_download_url);

  return (
    <main className="page-shell">
      <section className="detail-header">
        <div>
          <Link className="back-link" to="/">Back to projects</Link>
          <h1>{project.title}</h1>
          <p>{project.source_language_name || project.source_language} to {project.target_language_name || project.target_language}</p>
        </div>
        <StatusPill status={project.status} />
      </section>

      {error ? <div className="notice error">{error}</div> : null}
      {project.error_message ? <div className="notice error">{project.error_message}</div> : null}
      {project.processing_warning ? <div className="notice warning">{project.processing_warning}</div> : null}
      {project.translation_needs_reprocessing ? (
        <div className="notice warning">
          The translation engine or target language changed. Reprocess the video before exporting or rendering.
        </div>
      ) : null}
      {isActiveJob(project) ? (
        <div className="notice progress-notice">
          {stageLabel(project.processing_stage)}
          {progress.total ? ` — ${progress.completed} of ${progress.total} words` : ""}
        </div>
      ) : null}

      <section className="actions-bar">
        <button onClick={() => runAction("Process video", () => processProject(project.id))} disabled={!project.source_video_url || isActiveJob(project) || busyAction !== null}>
          {busyAction === "Process video" ? "Starting..." : "Process Video"}
        </button>
        <button onClick={() => runAction("Export SRT", () => exportProjectSrt(project.id))} disabled={!canPublishSegments || isActiveJob(project) || busyAction !== null}>
          {busyAction === "Export SRT" ? "Exporting..." : "Export SRT"}
        </button>
        <button onClick={() => runAction("Render video", () => renderProject(project.id))} disabled={!canPublishSegments || isActiveJob(project) || busyAction !== null}>
          {busyAction === "Render video" ? "Starting..." : "Render Subtitled Video"}
        </button>
        {srtUrl ? <a className="button-link" href={srtUrl}>Download SRT</a> : null}
        {downloadUrl ? <a className="button-link primary" href={downloadUrl}>Download MP4</a> : null}
      </section>

      <section className="detail-grid">
        <VideoPreview project={project} />
        <ProjectMeta project={project} onProjectChange={loadProject} />
      </section>
      <SubtitleEditor projectId={project.id} enabled={hasSegments} />
    </main>
  );
}

function isActiveJob(project) {
  return project?.status === "processing" || project?.status === "rendering";
}

function stageLabel(stage) {
  const labels = {
    queued: "Queued for processing",
    extracting_audio: "Extracting audio",
    transcribing: "Transcribing with WhisperX",
    loading_japanese_alignment: "Loading and applying Japanese forced alignment",
    segmenting_and_translating: "Selecting deterministic caption timing and translating"
  };
  return labels[stage] || "Processing video";
}
