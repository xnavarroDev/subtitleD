import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { listSegments, updateSegment, mergeSegments, splitSegment, translateSegment } from "../api";
import { adjacentSelection, splitDraft } from "../captionEditing";
import { formatTimestamp, parseTimestamp, sameDraft, segmentDraft, timelineLayout } from "../studio";
import Icon from "./Icon";
import VideoPreview from "./VideoPreview";
import { DeviceSessionContext } from "./DeviceConnection";
import "./SubtitleEditor.css";

export default function SubtitleEditor({ project, enabled, transcriptOnly = false, revision, onSaved, onDirtyChange }) {
  const { setWorkspaceDirty } = useContext(DeviceSessionContext);
  const [segments, setSegments] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [windowSize, setWindowSize] = useState(30);
  const [checkedIds, setCheckedIds] = useState([]);
  const [splitParts, setSplitParts] = useState(null);
  const [translationNotes, setTranslationNotes] = useState({});
  const splitInputs = useRef([]);
  const baseline = useRef({});
  const videoRef = useRef(null);
  const pendingSeek = useRef(null);
  const replayEnd = useRef(null);

  const loadSegments = useCallback(async () => {
    setLoading(true);
    try {
      const next = await listSegments(project.id);
      const oldBaseline = baseline.current;
      const nextBaseline = Object.fromEntries(next.map((segment) => [segment.id, segmentDraft(segment)]));
      setDrafts((current) => Object.fromEntries(next.map((segment) => [
        segment.id,
        current[segment.id] && oldBaseline[segment.id] && !sameDraft(current[segment.id], oldBaseline[segment.id])
          ? current[segment.id] : nextBaseline[segment.id],
      ])));
      baseline.current = nextBaseline;
      setSegments(next);
      setSelectedId((current) => next.some((segment) => segment.id === current) ? current : next[0]?.id ?? null);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load captions.");
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    if (enabled) loadSegments();
  }, [enabled, loadSegments, revision]);

  const dirtyIds = useMemo(() => segments.filter((segment) => drafts[segment.id] && !sameDraft(drafts[segment.id], baseline.current[segment.id])).map((segment) => segment.id), [segments, drafts]);
  const selectedIndex = segments.findIndex((segment) => segment.id === selectedId);
  const selectedSegment = segments[selectedIndex];
  const selectedDraft = drafts[selectedId];
  const showSpeakers = segments.some((segment) => Boolean(segment.speaker_label));
  const previewSegments = useMemo(() => segments.map((segment) => ({
    ...segment,
    start_time: parseTimestamp(drafts[segment.id]?.start_time ?? segment.start_time) ?? segment.start_time,
    end_time: parseTimestamp(drafts[segment.id]?.end_time ?? segment.end_time) ?? segment.end_time,
  })), [segments, drafts]);
  const totalDuration = duration || Math.max(0, ...previewSegments.map((segment) => segment.end_time));
  const timelineStart = Math.floor(Math.max(0, Math.min(currentTime, (totalDuration || currentTime) - .001)) / windowSize) * windowSize;
  const timelineEnd = Math.max(timelineStart + .01, Math.min(timelineStart + windowSize, totalDuration || windowSize));
  const clips = timelineLayout(previewSegments, timelineStart, timelineEnd);
  const laneCount = Math.max(1, ...clips.map((clip) => clip.lane + 1));
  const activeCaption = previewSegments.find((segment) => currentTime >= segment.start_time && currentTime < segment.end_time);
  const liveText = activeCaption ? (transcriptOnly ? activeCaption.original_text : drafts[activeCaption.id]?.translated_text ?? activeCaption.translated_text) : "";

  useEffect(() => { onDirtyChange?.(dirtyIds.length > 0 || Boolean(splitParts)); setWorkspaceDirty?.(dirtyIds.length > 0 || Boolean(splitParts)); }, [dirtyIds.length, splitParts, onDirtyChange, setWorkspaceDirty]);
  useEffect(() => () => setWorkspaceDirty?.(false), [setWorkspaceDirty]);
  useEffect(() => {
    if (!dirtyIds.length && !splitParts) return undefined;
    const protectDrafts = (event) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", protectDrafts);
    return () => window.removeEventListener("beforeunload", protectDrafts);
  }, [dirtyIds.length, splitParts]);

  function seek(time) {
    const next = Math.max(0, totalDuration ? Math.min(time, totalDuration) : time);
    replayEnd.current = null;
    setCurrentTime(next);
    if (videoRef.current?.readyState >= 1) videoRef.current.currentTime = next;
    else pendingSeek.current = next;
  }

  function selectSegment(segment) {
    if (saving !== null || splitParts) return;
    setSelectedId(segment.id);
    const draft = drafts[segment.id];
    seek(parseTimestamp(draft?.start_time ?? segment.start_time) ?? segment.start_time);
  }

  function selectNeighbor(offset) {
    const next = segments[selectedIndex + offset];
    if (next) selectSegment(next);
  }

  async function replay() {
    if (!selectedSegment) return;
    const timing = previewSegments.find((segment) => segment.id === selectedId);
    seek(timing.start_time);
    replayEnd.current = timing.end_time;
    try { await videoRef.current?.play(); } catch { setError("Clip playback is unavailable. Check the video preview and local connection."); }
  }

  function handleMetadata(event) {
    const video = event.currentTarget;
    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
    if (pendingSeek.current !== null) {
      video.currentTime = Math.min(pendingSeek.current, video.duration || pendingSeek.current);
      pendingSeek.current = null;
    }
  }

  function handleTimeUpdate(event) {
    const video = event.currentTarget;
    setCurrentTime(video.currentTime);
    if (replayEnd.current !== null && video.currentTime >= replayEnd.current) {
      video.pause();
      replayEnd.current = null;
    }
  }

  function updateDraft(patch) {
    setDrafts((current) => ({ ...current, [selectedId]: { ...current[selectedId], ...patch } }));
  }

  async function save(event) {
    event?.preventDefault();
    if (!selectedSegment || !selectedDraft || saving || !enabled || transcriptOnly || splitParts) return;
    const id = selectedId;
    const draft = { ...selectedDraft };
    const start = parseTimestamp(draft.start_time);
    const end = parseTimestamp(draft.end_time);
    if (start === null || end === null || start >= end) {
      setError("Use valid timestamps, such as 00:12.400. The end must be after the start.");
      return;
    }
    if (duration && end > duration + .1) {
      setError("The caption end is beyond the video's duration.");
      return;
    }
    setSaving(id);
    setError(null);
    try {
      const payload = { start_time: start, end_time: end, translated_text: draft.translated_text, revision: selectedSegment.updated_at };
      if (translationNotes[id]) payload.translation_provenance = translationNotes[id];
      if (showSpeakers) payload.speaker_label = draft.speaker_label;
      const updated = await updateSegment(id, payload);
      const savedDraft = segmentDraft(updated);
      baseline.current = { ...baseline.current, [id]: savedDraft };
      setSegments((current) => current.map((segment) => segment.id === id ? updated : segment));
      setDrafts((current) => ({ ...current, [id]: sameDraft(current[id], draft) ? savedDraft : current[id] }));
      setTranslationNotes(current => { const next = { ...current }; delete next[id]; return next; });
      await onSaved?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Caption save failed. Your draft is still here.");
    } finally {
      setSaving(null);
    }
  }

  const structureBlocked = !enabled || transcriptOnly || saving !== null || dirtyIds.length > 0 || Boolean(splitParts);

  async function combine() {
    if (structureBlocked || !adjacentSelection(segments, checkedIds)) return;
    setSaving("structure"); setError(null);
    try {
      const selected = segments.filter(segment => checkedIds.includes(segment.id));
      await mergeSegments(project.id, selected.map(segment => segment.id), Object.fromEntries(selected.map(segment => [segment.id, segment.updated_at])));
      setSelectedId(selected[0].id); setCheckedIds([]);
      await loadSegments(); await onSaved?.();
    } catch (caught) { setError(caught.message); }
    finally { setSaving(null); }
  }

  async function retranslate() {
    if (structureBlocked || !selectedSegment) return;
    const id = selectedSegment.id;
    setSaving("translation"); setError(null);
    try {
      const result = await translateSegment(id);
      if (result.revision !== selectedSegment.updated_at) throw new Error("The caption changed during translation. Refresh before trying again.");
      setDrafts(current => ({ ...current, [id]: { ...current[id], translated_text: result.translated_text } }));
      setTranslationNotes(current => ({ ...current, [id]: result }));
    } catch (caught) { setError(caught.message); }
    finally { setSaving(null); }
  }

  function moveRemainder(index) {
    const cursor = splitInputs.current[index]?.selectionStart;
    const text = splitParts[index].translated_text;
    if (!cursor || cursor >= text.length) { setError("Place the cursor where this caption's translation should end, then split the text."); return; }
    setSplitParts(parts => parts.map((part, position) => position === index ? { ...part, translated_text: text.slice(0, cursor).trim() } : position === index + 1 ? { ...part, translated_text: (text.slice(cursor).trim() + " " + part.translated_text).trim() } : part));
    setError(null);
  }

  async function commitSplit() {
    if (!splitParts || saving !== null) return;
    setSaving("structure"); setError(null);
    try {
      const next = await splitSegment(selectedId, splitParts, selectedSegment.updated_at);
      const first = next.find(segment => segment.segment_index === selectedIndex);
      setSelectedId(first?.id ?? next[0]?.id); setSplitParts(null); setCheckedIds([]);
      await loadSegments(); await onSaved?.();
    } catch (caught) { setError(caught.message); }
    finally { setSaving(null); }
  }

  return <section className="subtitle-studio" aria-label="Subtitle editing workspace">
    {error ? <div className="notice error" role="alert">{error}</div> : null}
    <div className="studio-editing-top">
      <VideoPreview project={project} videoRef={videoRef} currentTime={currentTime} duration={duration} caption={liveText} draftPreview={dirtyIds.length > 0} onTimeUpdate={handleTimeUpdate} onLoadedMetadata={handleMetadata} onPrevious={() => selectNeighbor(-1)} onNext={() => selectNeighbor(1)} onReplay={replay} hasSelection={Boolean(selectedSegment)} />
      <aside className="caption-inspector" aria-label="Selected caption">
        {selectedSegment && selectedDraft ? <form onSubmit={save} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); save(); } }}>
          <div className="inspector-header"><span className="eyebrow">Caption {String(selectedIndex + 1).padStart(2, "0")}</span><span className={dirtyIds.includes(selectedId) ? "caption-state is-dirty" : "caption-state"}>{dirtyIds.includes(selectedId) ? "Unsaved" : transcriptOnly ? "Transcript" : "Saved"}</span></div>
          <fieldset disabled={!enabled || transcriptOnly || saving !== null || Boolean(splitParts)}>
            <div className="timing-fields"><label>In<input aria-label="Caption start" value={selectedDraft.start_time} onChange={(event) => updateDraft({ start_time: event.target.value })} spellCheck="false" /></label><label>Out<input aria-label="Caption end" value={selectedDraft.end_time} onChange={(event) => updateDraft({ end_time: event.target.value })} spellCheck="false" /></label></div>
            {showSpeakers ? <label>Speaker<input value={selectedDraft.speaker_label} onChange={(event) => updateDraft({ speaker_label: event.target.value })} /></label> : null}
          </fieldset>
          <div className="source-field"><span>Original transcript</span><p>{selectedSegment.original_text}</p></div>
          {transcriptOnly ? <p className="inspector-explanation">Review the transcript, then choose Translate transcript. Translation uses the saved word timing.</p> : <label className="translation-field">Translation<textarea aria-label="Caption translation" value={selectedDraft.translated_text} onChange={(event) => updateDraft({ translated_text: event.target.value })} disabled={!enabled || saving !== null || Boolean(splitParts)} rows={4} /></label>}
          {translationNotes[selectedId] ? <p className="caption-review-note">Draft from {translationNotes[selectedId].provider === "nllb-ct2" ? "NLLB backup" : "HY-MT2"}. {translationNotes[selectedId].warning || (translationNotes[selectedId].context_supported ? "Surrounding captions were supplied as context." : "The combined passage was translated together; external conversation context is not supported by this backup.")} Save to keep this wording.</p> : null}
          {!transcriptOnly ? <div className="caption-structure-actions"><button type="button" disabled={structureBlocked} onClick={retranslate}>{saving === "translation" ? "Translating passage…" : "Retranslate passage"}</button><button type="button" disabled={structureBlocked || selectedSegment.original_text.length < 2} onClick={() => setSplitParts(splitDraft(selectedSegment, currentTime))}>{selectedSegment.merge_parts?.length ? "Split to original captions" : "Split caption"}</button></div> : null}
          {selectedSegment.translation_confidence_warning ? <p className="caption-review-note">{selectedSegment.translation_confidence_warning}</p> : null}
          {selectedSegment.timing_quality === "estimated" ? <p className="caption-review-note">Estimated timing · check this passage against the video.</p> : null}
          {!transcriptOnly ? <div className="inspector-save-actions"><button className="primary-action" disabled={!enabled || saving !== null || !dirtyIds.includes(selectedId)} type="submit"><Icon name="save" />{saving === selectedId ? "Saving..." : "Save changes"}</button><button type="button" disabled={saving !== null || !dirtyIds.includes(selectedId)} onClick={() => { setDrafts((current) => ({ ...current, [selectedId]: { ...baseline.current[selectedId] } })); setTranslationNotes(current => { const next = { ...current }; delete next[selectedId]; return next; }); setError(null); }}>Discard</button></div> : null}
          <div className="caption-provenance"><span>{providerLabel(selectedSegment)}</span>{selectedSegment.transcription_confidence != null ? <span>Recognition confidence {Math.round(selectedSegment.transcription_confidence * 100)}%</span> : null}<span>{transcriptOnly ? "Original words preserved" : "Ctrl / ⌘ + Enter to save"}</span></div>
          <div className="inspector-navigation"><button type="button" onClick={() => selectNeighbor(-1)} disabled={selectedIndex <= 0}>Previous</button><button type="button" onClick={() => selectNeighbor(1)} disabled={selectedIndex >= segments.length - 1}>Next</button></div>
        </form> : <div className="inspector-empty"><Icon name="captions" size={24} /><h2>Your caption, in focus.</h2><p>{loading ? "Loading captions..." : "Transcribe your video to start. Select a caption to edit wording and timing here."}</p></div>}
      </aside>
    </div>
    <section className="caption-timeline" aria-label="Caption timeline">
      <div className="timeline-heading"><h2><Icon name="timeline" />Caption timeline</h2><span className="timeline-note">Select a caption to jump to its start</span><label className="timeline-window">View<select aria-label="Timeline window" value={windowSize} onChange={(event) => setWindowSize(Number(event.target.value))}><option value={15}>15 seconds</option><option value={30}>30 seconds</option><option value={60}>1 minute</option><option value={120}>2 minutes</option></select></label></div>
      <div className="timeline-surface">
        <div className="timeline-ruler">{Array.from({ length: 5 }, (_, i) => <span key={i}>{formatTimestamp(timelineStart + (timelineEnd - timelineStart) * i / 4, false)}</span>)}</div>
        <label className="playback-scrubber"><span className="sr-only">Playback position</span><input type="range" aria-label="Playback position" min={0} max={totalDuration || 1} step=".01" value={Math.min(currentTime, totalDuration || 1)} disabled={!totalDuration} onChange={(event) => seek(Number(event.target.value))} /></label>
        <div className="timeline-tracks" style={{ height: Math.max(46, laneCount * 36 + 10) }}>
          {clips.map(({ segment, lane, left, width }) => <button key={segment.id} className={segment.id === selectedId ? "timeline-clip is-selected" : "timeline-clip"} style={{ left: left + "%", width: width + "%", top: lane * 36 + 4 }} aria-label={"Jump to caption " + (segments.findIndex((item) => item.id === segment.id) + 1)} aria-pressed={segment.id === selectedId} title={segment.original_text} onClick={() => selectSegment(segment)}><span>{segment.original_text}</span></button>)}
          {totalDuration ? <div className="timeline-playhead" aria-hidden="true" style={{ left: Math.min(100, Math.max(0, (currentTime - timelineStart) / (timelineEnd - timelineStart) * 100)) + "%" }} /> : null}
          {!segments.length ? <span className="timeline-empty">Your caption timings will appear here after transcription.</span> : !clips.length ? <span className="timeline-empty">No captions in this time range.</span> : null}
        </div>
      </div>
    </section>
    {splitParts ? <section className="caption-split-panel panel" aria-label="Split caption editor"><h2>Split passage into captions</h2><p>{selectedSegment.merge_parts?.length ? "Original source text and timings are preserved. Distribute the translation into each caption." : "The split uses the playhead, or the midpoint if the playhead is outside this caption. Review the source text, translation, and estimated timing."}</p><blockquote>{selectedSegment.translated_text}</blockquote>{splitParts.map((part, index) => <div className="caption-split-part" key={index}><strong>Caption {index + 1} · {formatTimestamp(part.start_time)} → {formatTimestamp(part.end_time)}</strong>{selectedSegment.merge_parts?.length ? <p>{part.original_text}</p> : <label>Original text {index + 1}<textarea aria-label={`Original text ${index + 1}`} value={part.original_text} onChange={event => setSplitParts(parts => parts.map((item, position) => position === index ? { ...item, original_text: event.target.value } : item))} disabled={saving !== null} /></label>}<label>Translation part {index + 1}<textarea aria-label={`Translation part ${index + 1}`} ref={element => { splitInputs.current[index] = element; }} value={part.translated_text} onChange={event => setSplitParts(parts => parts.map((item, position) => position === index ? { ...item, translated_text: event.target.value } : item))} disabled={saving !== null} /></label>{index < splitParts.length - 1 ? <button disabled={saving !== null} onClick={() => moveRemainder(index)}>Move text after cursor to next caption</button> : null}</div>)}<div className="inspector-save-actions"><button className="primary-action" disabled={saving !== null || splitParts.some(part => !part.translated_text.trim() || !part.original_text.trim())} onClick={commitSplit}>Save split captions</button><button disabled={saving !== null} onClick={() => { setSplitParts(null); setError(null); }}>Cancel split</button></div></section> : null}
    <section className="caption-table-panel" aria-label="Project captions">
      {!transcriptOnly ? <div className="caption-merge-toolbar"><span>Select adjacent captions to translate them as one passage.</span><button disabled={structureBlocked || !adjacentSelection(segments, checkedIds)} onClick={combine}>Combine selected{checkedIds.length ? ` (${checkedIds.length})` : ""}</button>{checkedIds.length ? <button disabled={saving !== null} onClick={() => setCheckedIds([])}>Clear selection</button> : null}{dirtyIds.length ? <small>Save or discard drafts before combining or splitting.</small> : null}</div> : null}
      <div className="caption-table-heading"><h2>Captions <span>{segments.length} total</span></h2><div>{dirtyIds.length ? <span className="unsaved-count">{dirtyIds.length} unsaved</span> : null}<button onClick={loadSegments} disabled={!enabled || loading || saving !== null || Boolean(splitParts)}>{loading ? "Refreshing..." : "Refresh"}</button></div></div>
      {segments.length ? <div className="caption-table-scroll"><table className="caption-table"><thead><tr><th scope="col">#</th><th scope="col">Time</th><th scope="col">Original</th><th scope="col">Translation</th><th scope="col"><span className="sr-only">Review note</span></th></tr></thead><tbody>
        {segments.map((segment, index) => <tr key={segment.id} className={segment.id === selectedId ? "is-selected" : ""} onClick={() => selectSegment(segment)}>
          <td><div className="caption-row-selection">{!transcriptOnly ? <input type="checkbox" aria-label={"Include caption " + (index + 1) + " in passage"} checked={checkedIds.includes(segment.id)} disabled={structureBlocked} onClick={event => event.stopPropagation()} onChange={event => setCheckedIds(current => event.target.checked ? [...current, segment.id] : current.filter(id => id !== segment.id))} /> : null}<button className="caption-select" aria-label={"Select caption " + (index + 1)} aria-pressed={segment.id === selectedId}>{String(index + 1).padStart(2, "0")}</button></div></td>
          <td className="caption-table-time">{drafts[segment.id]?.start_time || formatTimestamp(segment.start_time)}</td>
          <td className="caption-table-original">{segment.original_text}</td>
          <td>{drafts[segment.id]?.translated_text || <span className="muted">{transcriptOnly ? "Ready to translate" : "No translation"}</span>}</td>
          <td className="caption-table-mark">{dirtyIds.includes(segment.id) ? <span title="Unsaved changes" aria-label="Unsaved changes">●</span> : segment.translation_confidence_warning || segment.timing_quality === "estimated" ? <span title={segment.translation_confidence_warning || "Estimated timing"} aria-label="Needs review">!</span> : null}</td>
        </tr>)}
      </tbody></table></div> : <div className="captions-empty">{loading ? "Loading captions..." : "No captions yet. Start with Transcribe with WhisperX above."}</div>}
    </section>
    <footer className="workspace-footer"><span><Icon name="device" />WhisperX + your translation engine · on this device</span><span>{dirtyIds.length ? "Draft preview · save edits before exporting" : "Caption edits save to your local project"}</span></footer>
  </section>;
}

function providerLabel(segment) {
  const labels = { "nllb-ct2": "NLLB local", "hy-mt2-kobold": "HY-MT2 via KoboldCpp", libretranslate: "LibreTranslate", identity: "Same-language copy", mock: "Mock translator", transcript: "WhisperX transcript" };
  return labels[segment.translation_provider] || segment.translation_provider || "Local translator";
}
