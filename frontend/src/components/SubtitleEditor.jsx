import { useCallback, useEffect, useState } from "react";

import { listSegments, updateSegment } from "../api";

export default function SubtitleEditor({ projectId, enabled }) {
  const [segments, setSegments] = useState([]);
  const [drafts, setDrafts] = useState({});
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
  }, [projectId]);

  useEffect(() => {
    if (enabled) loadSegments().catch(() => undefined);
  }, [enabled, loadSegments]);

  const showSpeakers = segments.some((segment) => Boolean(segment.speaker_label));
  const showConfidence = segments.some((segment) => segment.transcription_confidence != null);

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

  return (
    <section className="panel editor-panel">
      <div className="section-heading">
        <div><p className="eyebrow">Subtitles</p><h2>Transcript and Translation</h2></div>
        <button onClick={loadSegments} disabled={!enabled}>Refresh</button>
      </div>
      <p className="editor-help">The transcript is the untouched WhisperX result. The translation and caption boundaries are produced with sliding-window context.</p>
      {error ? <div className="notice error">{error}</div> : null}
      {!enabled ? <div className="empty-state">Process the video to create subtitle segments.</div> : !segments.length ? <div className="empty-state">No segments found.</div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Start</th><th>End</th>{showSpeakers ? <th>Speaker</th> : null}{showConfidence ? <th>Confidence</th> : null}<th>WhisperX transcript</th><th>Final translation</th><th>Save</th></tr></thead>
          <tbody>{segments.map((segment) => {
            const draft = drafts[segment.id];
            return <tr key={segment.id}>
              <td><input className="time-input" value={draft?.start_time ?? ""} onChange={(event) => updateDraft(segment.id, { start_time: event.target.value })} /></td>
              <td><input className="time-input" value={draft?.end_time ?? ""} onChange={(event) => updateDraft(segment.id, { end_time: event.target.value })} /></td>
              {showSpeakers ? <td><input className="speaker-input" value={draft?.speaker_label ?? ""} onChange={(event) => updateDraft(segment.id, { speaker_label: event.target.value })} /></td> : null}
              {showConfidence ? <td><span className={`confidence ${confidenceClass(segment.transcription_confidence)}`}>{formatConfidence(segment.transcription_confidence)}</span></td> : null}
              <td className="original-text">{segment.original_text}</td>
              <td><textarea value={draft?.translated_text ?? ""} onChange={(event) => updateDraft(segment.id, { translated_text: event.target.value })} /></td>
              <td><button disabled={saving === segment.id} onClick={() => save(segment.id)}>{saving === segment.id ? "Saving..." : "Save"}</button></td>
            </tr>;
          })}</tbody>
        </table></div>
      )}
    </section>
  );
}

function formatConfidence(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function confidenceClass(value) {
  if (value == null) return "unknown";
  if (value < 0.55) return "low";
  if (value < 0.75) return "medium";
  return "high";
}
