import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createProject,
  DEFAULT_TRANSLATION_PROVIDERS,
  deleteProject,
  getTranslationSettings,
  listLanguages,
  listProjects,
  uploadProjectVideo
} from "../api";
import StatusPill from "../components/StatusPill";
import { targetLanguagesFor } from "../translationLanguages";
import "./ProjectCreationPage.css";

const LANGUAGE_LOAD_ERROR = "Could not load the selected translation provider's languages.";

export default function ProjectCreationPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [languagesLoading, setLanguagesLoading] = useState(false);
  const [title, setTitle] = useState("");
  const [translationProvider, setTranslationProvider] = useState("hy-mt2-kobold");
  const [translationProviders, setTranslationProviders] = useState(DEFAULT_TRANSLATION_PROVIDERS);
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [minSpeakers, setMinSpeakers] = useState("");
  const [maxSpeakers, setMaxSpeakers] = useState("");
  const [glossary, setGlossary] = useState("");
  const [detectSpeakers, setDetectSpeakers] = useState(false);
  const [smoothSpeakerFragments, setSmoothSpeakerFragments] = useState(false);
  const [translationSettings, setTranslationSettings] = useState({
    temperature: "0.7",
    top_p: "0.6",
    top_k: "20",
    repetition_penalty: "1.05",
    max_tokens: "256",
    context_captions: "2"
  });
  const [videoFile, setVideoFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => setProjects([]));
    getTranslationSettings()
      .then((settings) => {
        setTranslationProvider(settings.provider || "hy-mt2-kobold");
        setTranslationProviders(
          settings.providers?.length ? settings.providers : DEFAULT_TRANSLATION_PROVIDERS
        );
        setTranslationSettings({
          temperature: String(settings.temperature),
          top_p: String(settings.top_p),
          top_k: String(settings.top_k),
          repetition_penalty: String(settings.repetition_penalty),
          max_tokens: String(settings.max_tokens),
          context_captions: String(settings.context_captions)
        });
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!translationProvider) {
      return undefined;
    }
    let active = true;
    setLanguagesLoading(true);
    setLanguages([]);
    listLanguages(translationProvider)
      .then((availableLanguages) => {
        if (!active) {
          return;
        }
        setLanguages(availableLanguages);
        const codes = new Set(availableLanguages.map((language) => language.code));
        setSourceLanguage((current) => {
          if (current === "auto" || codes.has(current)) {
            return current;
          }
          return codes.has("en") ? "en" : availableLanguages[0]?.code || "";
        });
        setLanguagesLoading(false);
        setError((current) => current === LANGUAGE_LOAD_ERROR ? null : current);
      })
      .catch(() => {
        if (active) {
          setLanguages([]);
          setLanguagesLoading(false);
          setError(LANGUAGE_LOAD_ERROR);
        }
      });
    return () => {
      active = false;
    };
  }, [translationProvider]);

  useEffect(() => {
    if (languagesLoading || !languages.length) {
      return;
    }
    const availableTargets = targetLanguagesFor(languages, sourceLanguage);
    const targetCodes = new Set(availableTargets.map((language) => language.code));
    setTargetLanguage((current) => {
      if (targetCodes.has(current)) {
        return current;
      }
      return targetCodes.has("es") ? "es" : availableTargets[0]?.code || "";
    });
  }, [languages, languagesLoading, sourceLanguage]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!videoFile) {
      setError("Choose a video file first.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        title,
        translation_provider: translationProvider,
        source_language: sourceLanguage,
        target_language: targetLanguage,
        glossary,
        detect_speakers: detectSpeakers,
        smooth_speaker_fragments: detectSpeakers && smoothSpeakerFragments,
        translation_settings: {
          temperature: Number(translationSettings.temperature),
          top_p: Number(translationSettings.top_p),
          top_k: Number(translationSettings.top_k),
          repetition_penalty: Number(translationSettings.repetition_penalty),
          max_tokens: Number(translationSettings.max_tokens),
          context_captions: Number(translationSettings.context_captions)
        }
      };
      if (detectSpeakers && minSpeakers.trim()) {
        payload.min_speakers = Number(minSpeakers);
      }
      if (detectSpeakers && maxSpeakers.trim()) {
        payload.max_speakers = Number(maxSpeakers);
      }

      const project = await createProject(payload);
      await uploadProjectVideo(project.id, videoFile);
      navigate(`/projects/${project.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Project creation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteProject(project) {
    if (!window.confirm(`Delete "${project.title}" and all of its files?`)) {
      return;
    }

    setDeletingProjectId(project.id);
    setError(null);
    try {
      await deleteProject(project.id);
      setProjects((current) =>
        current.filter((candidate) => candidate.id !== project.id)
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Project deletion failed.");
    } finally {
      setDeletingProjectId(null);
    }
  }

  const showGenerationSettings = translationProvider === "hy-mt2-kobold";
  const targetLanguages = targetLanguagesFor(languages, sourceLanguage);
  const sourceLanguageAvailable = (
    sourceLanguage === "auto"
    || languages.some((language) => language.code === sourceLanguage)
  );
  const targetLanguageAvailable = targetLanguages.some(
    (language) => language.code === targetLanguage
  );

  return (
    <main className="page-shell">
      <section className="workspace-grid">
        <form className="panel project-form" onSubmit={handleSubmit}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">New project</p>
              <h1>Create SubtitleD Project</h1>
            </div>
            <StatusPill status="created" />
          </div>

          <label>
            <span>Title</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Launch demo"
              required
            />
          </label>

          <label>
            <span>Translation engine</span>
            <select
              value={translationProvider}
              onChange={(event) => setTranslationProvider(event.target.value)}
              required
            >
              {translationProviders.map((provider) => (
                <option value={provider.id} key={provider.id}>
                  {provider.label}
                </option>
              ))}
            </select>
          </label>

          <div className="form-row">
            <label>
              <span>Source language</span>
              <select
                value={sourceLanguage}
                disabled={languagesLoading}
                onChange={(event) => setSourceLanguage(event.target.value)}
                required
              >
                <option value="auto">Auto-detect</option>
                <option value="" disabled>Select a language</option>
                {languages.map((language) => (
                  <option value={language.code} key={language.code}>
                    {language.name} ({language.code})
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Target language</span>
              <select
                value={targetLanguage}
                disabled={languagesLoading}
                onChange={(event) => setTargetLanguage(event.target.value)}
                required
              >
                <option value="" disabled>Select a language</option>
                {targetLanguages.map((language) => (
                  <option value={language.code} key={language.code}>
                    {language.name} ({language.code})
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label>
            <span>Expected names and terms</span>
            <textarea
              value={glossary}
              onChange={(event) => setGlossary(event.target.value)}
              placeholder={"Alonzo\nSubtitleD\nKoboldCpp"}
            />
            <small>One term per line. WhisperX uses these as recognition hints.</small>
          </label>

          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={detectSpeakers}
              onChange={(event) => setDetectSpeakers(event.target.checked)}
            />
            <span><strong>Detect speakers</strong><small>Runs Pyannote diarization and requires an authorized Hugging Face token.</small></span>
          </label>

          <details className="advanced-settings">
            <summary>{showGenerationSettings ? "KoboldCpp translation settings" : "Translation settings"}</summary>
            {showGenerationSettings ? (
              <>
                <small>These values are sent with each KoboldCpp translation request.</small>
                <div className="form-row">
                  <TranslationSetting label="Temperature" name="temperature" min="0" max="2" step="0.05" values={translationSettings} setValues={setTranslationSettings} />
                  <TranslationSetting label="Top-p" name="top_p" min="0.01" max="1" step="0.01" values={translationSettings} setValues={setTranslationSettings} />
                </div>
                <div className="form-row">
                  <TranslationSetting label="Top-k" name="top_k" min="0" max="500" step="1" values={translationSettings} setValues={setTranslationSettings} />
                  <TranslationSetting label="Repetition penalty" name="repetition_penalty" min="0.5" max="2" step="0.01" values={translationSettings} setValues={setTranslationSettings} />
                </div>
              </>
            ) : null}
            <div className="form-row">
              {showGenerationSettings ? <TranslationSetting label="Maximum output tokens" name="max_tokens" min="16" max="2048" step="1" values={translationSettings} setValues={setTranslationSettings} /> : null}
              <TranslationSetting label="Context captions" name="context_captions" min="0" max="5" step="1" values={translationSettings} setValues={setTranslationSettings} />
            </div>
          </details>

          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={smoothSpeakerFragments}
              disabled={!detectSpeakers}
              onChange={(event) => setSmoothSpeakerFragments(event.target.checked)}
            />
            <span><strong>Smooth short speaker fragments</strong><small>Reassigns likely brief diarization glitches for cleaner captions. Leave off when short interjections must retain exact speaker labels.</small></span>
          </label>

          <label>
            <span>Video file</span>
            <input
              accept=".mp4,.mov,.webm,.mkv,video/mp4,video/quicktime,video/webm"
              type="file"
              onChange={(event) => setVideoFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>

          <div className="form-row">
            <label>
              <span>Minimum speakers</span>
              <input
                min="1"
                type="number"
                value={minSpeakers}
                onChange={(event) => setMinSpeakers(event.target.value)}
                placeholder="Optional"
                disabled={!detectSpeakers}
              />
            </label>
            <label>
              <span>Maximum speakers</span>
              <input
                min="1"
                type="number"
                value={maxSpeakers}
                onChange={(event) => setMaxSpeakers(event.target.value)}
                placeholder="Optional"
                disabled={!detectSpeakers}
              />
            </label>
          </div>

          {error ? <div className="notice error">{error}</div> : null}

          <button
            className="primary-action"
            disabled={
              submitting
              || languagesLoading
              || !languages.length
              || !title.trim()
              || !sourceLanguageAvailable
              || !targetLanguageAvailable
            }
          >
            {submitting ? "Creating..." : "Create and Upload"}
          </button>
        </form>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Projects</p>
              <h2>Recent Work</h2>
            </div>
          </div>
          <div className="project-list">
            {projects.length ? (
              projects.map((project) => (
                <div className="project-row" key={project.id}>
                  <Link
                    className="project-row-link"
                    to={`/projects/${project.id}`}
                  >
                    <div className="project-row-content">
                      <strong>{project.title}</strong>
                      <span>
                        {project.source_language_name || project.source_language} to{" "}
                        {project.target_language_name || project.target_language}
                      </span>
                    </div>
                    <StatusPill status={project.status} />
                  </Link>
                  <div className="project-row-actions">
                    <button
                      aria-label={`Delete ${project.title}`}
                      className="project-delete-button"
                      disabled={deletingProjectId === project.id}
                      onClick={() => handleDeleteProject(project)}
                      title={`Delete ${project.title}`}
                      type="button"
                    >
                      {"\u00D7"}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">No projects yet.</div>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

function TranslationSetting({ label, name, min, max, step, values, setValues }) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={values[name]}
        onChange={(event) => setValues((current) => ({
          ...current,
          [name]: event.target.value
        }))}
      />
    </label>
  );
}
