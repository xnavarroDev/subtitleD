import { useState } from "react";

import { updateProject } from "../api";

export default function ProjectMeta({ project, onProjectChange }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function toggle(name, value) {
    setBusy(true);
    setError(null);
    try {
      await updateProject(project.id, { [name]: value });
      await onProjectChange?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update project settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel meta-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Metadata</p>
          <h2>Project State</h2>
        </div>
      </div>
      <dl>
        <div>
          <dt>Created</dt>
          <dd>{new Date(project.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{new Date(project.updated_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Source video</dt>
          <dd>{project.source_video_path ? "Uploaded" : "Missing"}</dd>
        </div>
        <div>
          <dt>Rendered video</dt>
          <dd>{project.output_video_path ? "Ready" : "Pending"}</dd>
        </div>
        <div><dt>Processing stage</dt><dd>{project.processing_stage || "Not started"}</dd></div>
        <div><dt>Translated words</dt><dd>{project.translation_progress?.completed || 0} / {project.translation_progress?.total || 0}</dd></div>
        <div><dt>Caption timing</dt><dd>Deterministic</dd></div>
        <div><dt>Speaker detection</dt><dd>{project.detect_speakers ? "Enabled" : "Disabled"}</dd></div>
        <div><dt>Speaker smoothing</dt><dd>{project.smooth_speaker_fragments ? "Enabled" : "Disabled"}</dd></div>
        <div><dt>Glossary terms</dt><dd>{project.glossary ? project.glossary.split(/[,\n]/).filter(Boolean).length : 0}</dd></div>
      </dl>
      <div className="project-option-list">
        <label className="checkbox-option">
          <input type="checkbox" checked={Boolean(project.detect_speakers)} disabled={busy || project.status === "processing"} onChange={(event) => toggle("detect_speakers", event.target.checked)} />
          <span><strong>Detect speakers</strong><small>Runs Pyannote the next time this video is processed.</small></span>
        </label>
        <label className="checkbox-option">
          <input type="checkbox" checked={Boolean(project.smooth_speaker_fragments)} disabled={busy || project.status === "processing" || !project.detect_speakers} onChange={(event) => toggle("smooth_speaker_fragments", event.target.checked)} />
          <span><strong>Smooth short speaker fragments</strong><small>Optional diarization cleanup used the next time this video is processed.</small></span>
        </label>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
    </section>
  );
}
