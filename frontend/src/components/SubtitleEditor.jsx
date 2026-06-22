import { useCallback, useEffect, useMemo, useState } from "react";

import { listSegments, updateSegment } from "../api";
import "./SubtitleEditor.css";

export default function SubtitleEditor({ projectId, enabled }) {
  const [segments, setSegments] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);

  const loadSegments = useCallback(async () => {
    const nextSegments = await listSegments(projectId);
    setSegments(nextSegments);
    setDrafts(
      Object.fromEntries(
        nextSegments.map((segment) => [
          segment.id,
          {
            start_time: String(segment.start_time),
            end_time: String(segment.end_time),
            speaker_label: segment.speaker_label ?? "",
            translated_text: segment.translated_text
          }
        ])
      )
    );
  }, [projectId]);

  useEffect(() => {
    if (enabled) {
      loadSegments().catch(() => undefined);
    }
  }, [enabled, loadSegments]);

  const rows = useMemo(() => segments, [segments]);
  const showSpeakers = rows.some((segment) => Boolean(segment.speaker_label));

  async function save(segmentId) {
    const draft = drafts[segmentId];
    if (!draft) {
      return;
    }

    const payload = {
      start_time: Number(draft.start_time),
      end_time: Number(draft.end_time),
      translated_text: draft.translated_text
    };
    if (showSpeakers) {
      payload.speaker_label = draft.speaker_label;
    }

    setSaving(segmentId);
    setError(null);
    try {
      const updated = await updateSegment(segmentId, payload);
      setSegments((current) =>
        current.map((segment) => (segment.id === segmentId ? updated : segment))
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Segment save failed.");
    } finally {
      setSaving(null);
    }
  }

  function updateDraft(segmentId, patch) {
    setDrafts((current) => ({
      ...current,
      [segmentId]: {
        ...(current[segmentId] ?? {
          start_time: "",
          end_time: "",
          speaker_label: "",
          translated_text: ""
        }),
        ...patch
      }
    }));
  }

  return (
    <section className="panel editor-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Subtitles</p>
          <h2>Editor</h2>
        </div>
        <button onClick={() => loadSegments()} disabled={!enabled}>
          Refresh
        </button>
      </div>

      {error ? <div className="notice error">{error}</div> : null}

      {!enabled ? (
        <div className="empty-state">Process the video to create subtitle segments.</div>
      ) : rows.length === 0 ? (
        <div className="empty-state">No segments found.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Start</th>
                <th>End</th>
                {showSpeakers ? <th>Speaker</th> : null}
                <th>Original text</th>
                <th>Translated text</th>
                <th>Save</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((segment) => {
                const draft = drafts[segment.id];
                return (
                  <tr key={segment.id}>
                    <td>
                      <input
                        className="time-input"
                        value={draft?.start_time ?? ""}
                        onChange={(event) =>
                          updateDraft(segment.id, { start_time: event.target.value })
                        }
                      />
                    </td>
                    <td>
                      <input
                        className="time-input"
                        value={draft?.end_time ?? ""}
                        onChange={(event) =>
                          updateDraft(segment.id, { end_time: event.target.value })
                        }
                      />
                    </td>
                    {showSpeakers ? (
                      <td>
                        <input
                          className="speaker-input"
                          value={draft?.speaker_label ?? ""}
                          onChange={(event) =>
                            updateDraft(segment.id, { speaker_label: event.target.value })
                          }
                          placeholder="SPEAKER_00"
                        />
                      </td>
                    ) : null}
                    <td className="original-text">{segment.original_text}</td>
                    <td>
                      <textarea
                        value={draft?.translated_text ?? ""}
                        onChange={(event) =>
                          updateDraft(segment.id, {
                            translated_text: event.target.value
                          })
                        }
                      />
                    </td>
                    <td>
                      <button onClick={() => save(segment.id)} disabled={saving === segment.id}>
                        {saving === segment.id ? "Saving..." : "Save"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
