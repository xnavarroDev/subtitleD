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

  async function saveTranslationSettings(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await updateProject(project.id, {
        translation_settings: {
          temperature: Number(form.get("temperature")),
          top_p: Number(form.get("top_p")),
          top_k: Number(form.get("top_k")),
          repetition_penalty: Number(form.get("repetition_penalty")),
          max_tokens: Number(form.get("max_tokens")),
          context_captions: Number(form.get("context_captions"))
        }
      });
      await onProjectChange?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update translation settings.");
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
        <div><dt>Translation context</dt><dd>{project.translation_settings?.context_captions ?? 0} neighboring unit(s)</dd></div>
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
      <details className="advanced-settings">
        <summary>HY-MT2 translation settings</summary>
        <form key={project.updated_at} onSubmit={saveTranslationSettings}>
          <div className="form-row">
            <SettingInput label="Temperature" name="temperature" value={project.translation_settings?.temperature ?? 0.7} min="0" max="2" step="0.05" />
            <SettingInput label="Top-p" name="top_p" value={project.translation_settings?.top_p ?? 0.6} min="0.01" max="1" step="0.01" />
          </div>
          <div className="form-row">
            <SettingInput label="Top-k" name="top_k" value={project.translation_settings?.top_k ?? 20} min="0" max="500" step="1" />
            <SettingInput label="Repetition penalty" name="repetition_penalty" value={project.translation_settings?.repetition_penalty ?? 1.05} min="0.5" max="2" step="0.01" />
          </div>
          <div className="form-row">
            <SettingInput label="Maximum output tokens" name="max_tokens" value={project.translation_settings?.max_tokens ?? 256} min="16" max="2048" step="1" />
            <SettingInput label="Context captions" name="context_captions" value={project.translation_settings?.context_captions ?? 2} min="0" max="5" step="1" />
          </div>
          <button disabled={busy || project.status === "processing"} type="submit">Save translation settings</button>
        </form>
      </details>
      {error ? <div className="notice error">{error}</div> : null}
    </section>
  );
}

function SettingInput({ label, name, value, min, max, step }) {
  return (
    <label>
      <span>{label}</span>
      <input name={name} type="number" defaultValue={value} min={min} max={max} step={step} />
    </label>
  );
}
