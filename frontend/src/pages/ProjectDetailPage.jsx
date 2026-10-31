import { useCallback, useContext, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  absoluteFileUrl, exportProjectSrt, getProject, getProjectStatus,
  transcribeProject, translateProject, renderProject,
} from "../api";
import ProjectMeta from "../components/ProjectMeta";
import StatusPill from "../components/StatusPill";
import SubtitleEditor from "../components/SubtitleEditor";
import Icon from "../components/Icon";
import { DeviceSessionContext } from "../components/DeviceConnection";
import "./ProjectDetailPage.css";

export default function ProjectDetailPage() {
  const { connected, openSetup } = useContext(DeviceSessionContext);
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [error, setError] = useState(null);
  const [busyAction, setBusyAction] = useState(null);
  const [hasUnsaved, setHasUnsaved] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const loadProject = useCallback(async () => {
    if (connected && projectId) setProject(await getProject(projectId));
  }, [connected, projectId]);

  useEffect(() => {
    setProject(null);
    setHasUnsaved(false);
    setError(null);
    loadProject().catch((caught) => setError(caught instanceof Error ? caught.message : "Project load failed."));
  }, [loadProject]);

  useEffect(() => {
    if (!projectId || !project || !isActiveJob(project)) return undefined;
    const intervalId = window.setInterval(async () => {
      try {
        const status = await getProjectStatus(projectId);
        setProject((current) => current ? { ...current, ...status } : current);
        if (!isActiveJob(status)) await loadProject();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Lost connection to local processing. Reconnect your device to check progress.");
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
      setError(caught instanceof Error ? caught.message : label + " failed.");
    } finally {
      setBusyAction(null);
    }
  }

  if (!projectId) return null;
  if (!connected) return <main className="page-shell studio-page"><header className="studio-project-header"><h1>Subtitle studio</h1></header><div className="notice device-browse-notice"><span>This project's video and subtitles live on your device. Connect to open them.</span><button onClick={openSetup}>Connect device</button></div></main>;
  if (!project) return <main className="page-shell"><div className={error ? "notice error" : "empty-state"}>{error || "Loading project..."}</div></main>;

  const active = isActiveJob(project);
  const hasTranscript = Boolean(project.has_transcript);
  const hasCaptions = hasTranscript || ["transcribed", "processed", "rendered"].includes(project.status);
  const canPublish = ["processed", "rendered"].includes(project.status) && !project.translation_needs_reprocessing && !hasUnsaved;
  const blocked = active || busyAction !== null || hasUnsaved;
  const progress = project.translation_progress || { completed: 0, total: 0 };
  const downloadUrl = absoluteFileUrl(project.download_url);
  const srtUrl = absoluteFileUrl(project.srt_download_url);

  return <main className="page-shell studio-page">
    <header className="studio-project-header">
      <div className="studio-project-title"><h1>{project.title}</h1><StatusPill status={project.status} /></div>
      <div className="studio-header-actions">
        <span className="project-language">{project.source_language_name || project.source_language} <span aria-hidden="true">→</span> {project.target_language_name || project.target_language}</span>
        <button onClick={() => setShowSettings(!showSettings)} aria-expanded={showSettings} aria-controls="studio-project-settings"><Icon name="settings" /><span>Settings</span></button>
        <details className="export-menu"><summary><Icon name="export" />Export</summary><div className="export-menu-content">
          <button onClick={() => runAction("Export SRT", () => exportProjectSrt(project.id))} disabled={!canPublish || blocked}>{busyAction === "Export SRT" ? "Creating SRT..." : "Create SRT"}</button>
          <button onClick={() => runAction("Render video", () => renderProject(project.id))} disabled={!canPublish || blocked}>{busyAction === "Render video" ? "Starting render..." : "Render subtitles"}</button>
          {srtUrl && !hasUnsaved ? <a className="button-link" referrerPolicy="no-referrer" href={srtUrl}>Download SRT</a> : null}
          {downloadUrl && !hasUnsaved ? <a className="button-link primary" referrerPolicy="no-referrer" href={downloadUrl}>Download MP4</a> : null}
          {!canPublish ? <small>{hasUnsaved ? "Save or discard your draft edits first." : "Translate the transcript before exporting."}</small> : null}
        </div></details>
      </div>
    </header>

    <section className="studio-jobbar" aria-label="Processing actions">
      <div className="studio-job-actions">
        <button className={!hasTranscript ? "primary-action" : ""} onClick={() => runAction("Transcribe", () => transcribeProject(project.id))} disabled={!project.source_video_url || blocked}><span className="action-number">1</span>{busyAction === "Transcribe" ? "Starting..." : hasTranscript ? "Transcribe again" : "Transcribe with WhisperX"}</button>
        <button className={hasTranscript && project.translation_needs_reprocessing ? "primary-action" : ""} onClick={() => runAction("Translate", () => translateProject(project.id))} disabled={!hasTranscript || blocked}><span className="action-number">2</span>{busyAction === "Translate" ? "Starting..." : "Translate transcript"}</button>
      </div>
      <span className="studio-workflow-hint">{hasUnsaved ? "Save or discard drafts before processing or exporting." : hasTranscript ? "Select a caption to edit wording and timing." : "Start with a transcript. Your video stays on this device."}</span>
    </section>
    {hasTranscript ? <p className="reprocess-hint">Transcribing again replaces the transcript and translations. Translating again replaces caption edits.</p> : null}
    {error ? <div className="notice error" role="alert">{error}</div> : null}
    {project.error_message ? <div className="notice error" role="alert">{project.error_message}</div> : null}
    {project.processing_warning ? <div className="notice warning">{project.processing_warning}</div> : null}
    {project.translation_needs_reprocessing ? <div className="notice warning">{project.status === "transcribed" ? "Transcript ready. Review it, then translate the saved words." : "Translation settings changed. Translate again before exporting."}</div> : null}
    {active ? <div className="processing-banner" role="status"><span className="processing-spinner" /><div><strong>{stageLabel(project.processing_stage)}</strong><small>{progress.total ? progress.completed + " of " + progress.total + " words" : "Processing on your device. This can take a few minutes."}</small></div>{progress.total ? <div className="progress-track"><span style={{ width: Math.min(100, progress.completed / progress.total * 100) + "%" }} /></div> : null}</div> : null}
    {showSettings ? <section className="studio-settings" id="studio-project-settings"><ProjectMeta project={project} onProjectChange={loadProject} /></section> : null}
    <SubtitleEditor key={project.id} project={project} enabled={hasCaptions && !active} transcriptOnly={project.status === "transcribed"} revision={project.updated_at} onSaved={loadProject} onDirtyChange={setHasUnsaved} />
  </main>;
}

function isActiveJob(project) {
  return project?.status === "processing" || project?.status === "rendering";
}

function stageLabel(stage) {
  return {
    queued: "Queued for processing", queued_transcribe: "Queued for transcription",
    queued_translate: "Queued for translation", queued_process: "Queued for processing",
    queued_render: "Queued for rendering", rendering: "Rendering subtitles with FFmpeg",
    segmenting: "Creating transcript captions", extracting_audio: "Extracting audio",
    transcribing: "Transcribing with WhisperX", loading_japanese_alignment: "Applying Japanese alignment",
    segmenting_and_translating: "Creating and translating captions",
  }[stage] || "Processing video";
}
