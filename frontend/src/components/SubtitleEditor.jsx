import { useCallback, useEffect, useMemo, useState } from "react";

import { listSegments, updateSegment } from "../api";
import "./SubtitleEditor.css";

export default function SubtitleEditor({ projectId, enabled }) {
  const [segments, setSegments] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);

  const loadSegments = useCallback(async () => {
    const next = await listSegments(projectId);
    setSegments(next);
    setDrafts(Object.fromEntries(next.map((segment) => [segment.id, {
      start_time: String(segment.start_time),
      end_time: String(segment.end_time),
      speaker_label: segment.speaker_label ?? "",
      translated_text: segment.translated_text
    }])));
    setSelectedId((current) => next.some((segment) => segment.id === current) ? current : next[0]?.id ?? null);
  }, [projectId]);

  useEffect(() => {
    if (enabled) loadSegments().catch(() => undefined);
  }, [enabled, loadSegments]);

  const selectedSegment = useMemo(
    () => segments.find((segment) => segment.id === selectedId) ?? null,
    [segments, selectedId]
  );
  const selectedDraft = selectedSegment ? drafts[selectedSegment.id] : null;
  const showSpeakers = segments.some((segment) => Boolean(segment.speaker_label));

  function updateDraft(segmentId, patch) {
    setDrafts((current) => ({ ...current, [segmentId]: { ...current[segmentId], ...patch } }));
  }

  async function save(segmentId) {
    const draft = drafts[segmentId];
    if (!draft) return;
    setSaving(segmentId);
    setError(null);
    try {
      const payload = {
        start_time: Number(draft.start_time),
        end_time: Number(draft.end_time),
        translated_text: draft.translated_text
      };
      if (showSpeakers) payload.speaker_label = draft.speaker_label;
      const updated = await updateSegment(segmentId, payload);
      setSegments((current) => current.map((segment) => segment.id === segmentId ? updated : segment));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Segment save failed.");
    } finally {
      setSaving(null);
    }
  }

  function selectNeighbor(offset) {
    const index = segments.findIndex((segment) => segment.id === selectedId);
    const next = segments[index + offset];
    if (next) setSelectedId(next.id);
  }

  return (
    <section className="panel editor-panel">
      <div className="section-heading editor-heading">
        <div><p className="eyebrow">Subtitles</p><h2>Transcript and translation</h2></div>
        <div className="editor-heading-actions"><span>{segments.length} captions</span><button className="ghost-button" onClick={loadSegments} disabled={!enabled}>Refresh</button></div>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      {!enabled ? <div className="empty-state"><strong>No captions yet</strong><span>Process the video to generate a transcript and translation.</span></div> : !segments.length ? <div className="empty-state">No segments found.</div> : (
        <div className="caption-editor">
          <div className="caption-list" aria-label="Subtitle captions">
            {segments.map((segment, index) => {
              const active = segment.id === selectedId;
              const draft = drafts[segment.id];
              return (
                <button className={`caption-row ${active ? "active" : ""}`} key={segment.id} type="button" onClick={() => setSelectedId(segment.id)} aria-pressed={active}>
                  <span className="caption-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="caption-copy">
                    <span className="caption-source">{segment.original_text}</span>
                    <span className="caption-translation">{draft?.translated_text || "No translation"}</span>
                  </span>
                  <span className="caption-time">{formatTime(segment.start_time)}</span>
                  {segment.translation_confidence_warning ? <span className="caption-warning" aria-label="Needs review">!</span> : null}
                </button>
              );
            })}
          </div>

          {selectedSegment && selectedDraft ? (
            <div className="caption-inspector">
              <div className="inspector-header">
                <div><p className="eyebrow">Caption {segments.findIndex((segment) => segment.id === selectedId) + 1}</p><h3>Edit caption</h3></div>
                {selectedSegment.transcription_confidence != null ? <span className={`confidence ${confidenceClass(selectedSegment.transcription_confidence)}`}>{formatConfidence(selectedSegment.transcription_confidence)} confidence</span> : null}
              </div>

              <div className="timing-fields">
                <label><span>Start</span><input value={selectedDraft.start_time} onChange={(event) => updateDraft(selectedId, { start_time: event.target.value })} /></label>
                <label><span>End</span><input value={selectedDraft.end_time} onChange={(event) => updateDraft(selectedId, { end_time: event.target.value })} /></label>
                {showSpeakers ? <label><span>Speaker</span><input value={selectedDraft.speaker_label} onChange={(event) => updateDraft(selectedId, { speaker_label: event.target.value })} /></label> : null}
              </div>

              <label className="source-field"><span>Original transcript</span><div>{selectedSegment.original_text}</div></label>
              <label><span>Final translation</span><textarea value={selectedDraft.translated_text} onChange={(event) => updateDraft(selectedId, { translated_text: event.target.value })} /></label>

              <div className="caption-provenance">
                <span>{providerLabel(selectedSegment)}</span><span>{methodLabel(selectedSegment.translation_method)}</span>
                {selectedSegment.timing_quality === "estimated" ? <span className="warning-text">Estimated timing</span> : null}
              </div>

              <div className="inspector-actions">
                <div><button className="ghost-button" type="button" onClick={() => selectNeighbor(-1)} disabled={segments[0]?.id === selectedId}>&larr; Previous</button><button className="ghost-button" type="button" onClick={() => selectNeighbor(1)} disabled={segments.at(-1)?.id === selectedId}>Next &rarr;</button></div>
                <button className="primary-action" disabled={saving === selectedId} onClick={() => save(selectedId)}>{saving === selectedId ? "Saving..." : "Save changes"}</button>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function formatTime(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatConfidence(value) {
  return value == null ? "--" : `${Math.round(value * 100)}%`;
}

function confidenceClass(value) {
  if (value == null) return "unknown";
  if (value < 0.55) return "low";
  if (value < 0.75) return "medium";
  return "high";
}

function methodLabel(value) {
  const labels = {
    contextual_timing: "Legacy AI timing",
    contextual_timing_unit: "Legacy AI timing / semantic unit",
    contextual_timing_resized: "Legacy AI timing / resized",
    deterministic_timing: "Deterministic timing",
    deterministic_timing_unit: "Deterministic timing / semantic unit",
    deterministic_timing_resized: "Deterministic timing / resized",
    contextual: "Legacy contextual LLM",
    contextual_split: "Legacy contextual LLM / split",
    fallback: "Legacy deterministic fallback"
  };
  return labels[value] || value || "Translation";
}

function providerLabel(segment) {
  const labels = {
    "nllb-ct2": "NLLB local",
    "hy-mt2-kobold": "HY-MT2 via KoboldCpp",
    libretranslate: "LibreTranslate fallback",
    identity: "Same-language copy",
    mock: "Mock translator"
  };
  const provider = labels[segment.translation_provider] || segment.translation_provider || "Local translator";
  return segment.translation_model ? `${provider} (${segment.translation_model})` : provider;
}
