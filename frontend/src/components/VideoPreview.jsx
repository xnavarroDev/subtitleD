import { absoluteFileUrl } from "../api";
import "./VideoPreview.css";

export default function VideoPreview({ project }) {
  const renderedUrl = absoluteFileUrl(project.rendered_video_url);
  const sourceUrl = absoluteFileUrl(project.source_video_url);
  const videoUrl = renderedUrl || sourceUrl;

  return (
    <section className="panel video-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Preview</p>
          <h2>{renderedUrl ? "Rendered Video" : "Source Video"}</h2>
        </div>
      </div>
      {videoUrl ? <video controls src={videoUrl} /> : <div className="empty-state">No video yet.</div>}
    </section>
  );
}
