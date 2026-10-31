import { useContext, useRef, useState } from "react";
import { absoluteFileUrl } from "../api";
import { DeviceSessionContext } from "./DeviceConnection";
import Icon from "./Icon";
import { formatTimestamp } from "../studio";
import "./VideoPreview.css";

export default function VideoPreview({ project, videoRef, currentTime = 0, duration = 0, caption = "", draftPreview = false, onTimeUpdate, onLoadedMetadata, onPrevious, onNext, onReplay, hasSelection }) {
  useContext(DeviceSessionContext);
  const [rendered, setRendered] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState(null);
  const stageRef = useRef(null);
  const renderedUrl = absoluteFileUrl(project.rendered_video_url);
  const sourceUrl = absoluteFileUrl(project.source_video_url);
  const useRendered = rendered && renderedUrl;
  const videoUrl = useRendered ? renderedUrl : sourceUrl;

  async function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    setError(null);
    if (video.paused) {
      try { await video.play(); } catch { setError("The video could not play. Check that the local connector is running and this format is supported by your browser."); }
    } else video.pause();
  }

  async function fullscreen() {
    try { await stageRef.current?.requestFullscreen(); } catch { setError("Fullscreen is unavailable in this browser."); }
  }

  return <section className="video-panel" aria-label="Video preview">
    <div className="video-topline">
      <span>{useRendered ? "Rendered video" : "Source preview"}{draftPreview && !useRendered ? <span className="draft-indicator"> · draft subtitles</span> : null}</span>
      {renderedUrl ? <div className="preview-modes" aria-label="Video version"><button aria-pressed={!useRendered} onClick={() => setRendered(false)}>Source</button><button aria-pressed={Boolean(useRendered)} onClick={() => setRendered(true)}>Rendered</button></div> : <span className="muted">Live subtitle preview</span>}
    </div>
    <div className="video-stage" ref={stageRef}>
      {videoUrl ? <video ref={videoRef} src={videoUrl} preload="metadata" playsInline muted={muted} onTimeUpdate={onTimeUpdate} onLoadedMetadata={onLoadedMetadata} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => setError("Preview unavailable. Check the connector connection and video format. Processing may still work for formats this browser cannot play.")} onClick={togglePlayback} aria-label="Project video" /> : <div className="video-empty"><Icon name="captions" size={30} /><span>Upload a video to begin.</span></div>}
      {!useRendered && caption ? <div className="live-subtitle" aria-live="off"><span>{caption}</span></div> : null}
    </div>
    <div className="video-transport">
      <span className="transport-time">{formatTimestamp(currentTime)} <span>/ {duration ? formatTimestamp(duration, false) : "--:--"}</span></span>
      <div className="transport-buttons"><button aria-label="Previous caption" onClick={onPrevious} disabled={!hasSelection}><Icon name="previous" /></button><button className="transport-play" aria-label={playing ? "Pause video" : "Play video"} onClick={togglePlayback} disabled={!videoUrl}><Icon name={playing ? "pause" : "play"} /></button><button aria-label="Next caption" onClick={onNext} disabled={!hasSelection}><Icon name="next" /></button></div>
      <div className="transport-extras"><button onClick={onReplay} disabled={!hasSelection} title="Replay selected caption"><Icon name="replay" /><span>Replay clip</span></button><button onClick={() => setMuted(!muted)} aria-label={muted ? "Unmute video" : "Mute video"} aria-pressed={muted}><Icon name="volume" /></button><button onClick={fullscreen} disabled={!videoUrl} aria-label="Fullscreen preview"><Icon name="fullscreen" /></button></div>
    </div>
    {error ? <div className="notice warning" role="status">{error}</div> : null}
  </section>;
}
