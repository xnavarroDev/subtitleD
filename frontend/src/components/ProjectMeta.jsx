import "./ProjectMeta.css";

export default function ProjectMeta({ project }) {
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
      </dl>
    </section>
  );
}
