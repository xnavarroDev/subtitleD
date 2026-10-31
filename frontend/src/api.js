/**
 * @typedef {Object} Project
 * @property {string} id
 * @property {string} title
 * @property {string|null} source_video_path
 * @property {string|null} extracted_audio_path
 * @property {string|null} output_video_path
 * @property {string|null} srt_path
 * @property {string} status
 * @property {string|null} processing_stage
 * @property {string|null} processing_warning
 * @property {{completed:number,total:number}} translation_progress
 * @property {string} glossary
 * @property {string} translation_provider
 * @property {boolean} translation_needs_reprocessing
 * @property {{temperature:number,top_p:number,top_k:number,repetition_penalty:number,max_tokens:number,context_captions:number}} translation_settings
 * @property {boolean} detect_speakers
 * @property {boolean} smooth_speaker_fragments
 * @property {string} source_language
 * @property {string} target_language
 * @property {string|null} detected_source_language
 * @property {string} source_language_name
 * @property {string} target_language_name
 * @property {number|null} min_speakers
 * @property {number|null} max_speakers
 * @property {string|null} error_message
 * @property {string} created_at
 * @property {string} updated_at
 * @property {string|null} source_video_url
 * @property {string|null} rendered_video_url
 * @property {string|null} download_url
 * @property {string|null} srt_download_url
 */

/**
 * @typedef {Object} SubtitleSegment
 * @property {string} id
 * @property {string} project_id
 * @property {number} start_time
 * @property {number} end_time
 * @property {string} original_text
 * @property {string} translated_text
 * @property {string|null} speaker_label
 * @property {number|null} transcription_confidence
 * @property {string} translation_method
 * @property {string} timing_quality
 * @property {string} translation_provider
 * @property {string|null} translation_model
 * @property {string} source_reconstruction_method
 * @property {boolean} source_was_reconstructed
 * @property {string|null} translation_unit_id
 * @property {string|null} translation_confidence_warning
 * @property {number} segment_index
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * Base REST endpoint for the Flask API.
 *
 * Docker Compose injects this value for the frontend container. The localhost
 * fallback keeps local Vite runs convenient when the backend is started outside
 * Docker.
 */
const CONNECTION_KEY = "subtitled.connection";
const ADDRESS_KEY = "subtitled.connectorAddress";
export let API_BASE = (
  localStorage.getItem(ADDRESS_KEY) || import.meta.env?.VITE_API_BASE_URL || "http://localhost:5000/api"
).replace(/\/$/, "");
let pairingCode = "";
let mediaToken = null;

export function savedConnection() {
  try {
    return JSON.parse(sessionStorage.getItem(CONNECTION_KEY)) || { address: API_BASE, code: "" };
  } catch {
    return { address: API_BASE, code: "" };
  }
}

export function forgetConnection() {
  pairingCode = "";
  mediaToken = null;
  sessionStorage.removeItem(CONNECTION_KEY);
}

export async function connectDevice(address, code) {
  const url = connectorUrl(address);
  forgetConnection();
  API_BASE = `${url.origin}/api`;
  pairingCode = code.trim();
  try {
    const session = await apiRequest("/connector/session", { method: "POST", timeout: 10000 });
    if (session.protocol_version !== 1 || !session.capabilities?.includes("transcribe")
        || !session.capabilities?.includes("translate")) {
      throw new Error("Update your local connector to a compatible SubtitleD version.");
    }
    if (!session.protected && !['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)) {
      throw new Error("Start the protected local connector with local_connector.py before connecting this website.");
    }
    mediaToken = session.media_token;
    localStorage.setItem(ADDRESS_KEY, API_BASE);
    sessionStorage.setItem(CONNECTION_KEY, JSON.stringify({ address: API_BASE, code: pairingCode }));
    return session;
  } catch (error) {
    forgetConnection();
    throw error;
  }
}

function connectorUrl(address) {
  const url = new URL(address);
  if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || !['http:', 'https:'].includes(url.protocol) || url.username || url.password
      || url.search || url.hash || !['', '/', '/api', '/api/'].includes(url.pathname)) {
    throw new Error("Use a local connector address such as http://localhost:5000/api.");
  }
  return url;
}

export async function pairWithCompanion(address, ticket) {
  const url = connectorUrl(address);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`${url.origin}/api/connector/pair`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticket }), credentials: "omit", cache: "no-store", signal: controller.signal,
    });
    const payload = await response.json();
    if (!response.ok || typeof payload.code !== "string") throw new Error(payload.error || "Open SubtitleD from the companion to connect again.");
    await connectDevice(address, payload.code);
    return payload.code;
  } catch (error) {
    throw new Error(error.name === "AbortError" || error instanceof TypeError
      ? "Cannot reach the companion. Start it and allow local device access in your browser."
      : error.message);
  } finally {
    clearTimeout(timer);
  }
}

export function getDiagnostics() {
  return apiRequest("/diagnostics", { allowUnavailable: true, timeout: 45000 });
}

export const DEFAULT_TRANSLATION_PROVIDERS = [
  {
    id: "hy-mt2-kobold",
    label: "Local KoboldCpp / HY-MT2",
    supports_generation_settings: true
  },
  {
    id: "nllb-ct2",
    label: "Local NLLB",
    supports_generation_settings: false
  }
];

/**
 * Shared JSON request helper.
 *
 * It intentionally leaves FormData headers alone so the browser can attach the
 * upload boundary for video files, while JSON requests get a default
 * Content-Type.
 */
async function apiRequest(path, options = {}) {
  const { timeout = 30000, allowUnavailable = false, ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers);
  if (pairingCode) headers.set("Authorization", `Bearer ${pairingCode}`);
  if (requestOptions.body && !(requestOptions.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const controller = new AbortController();
  const timer = timeout ? setTimeout(() => controller.abort(), timeout) : null;
  let response;
  let payload;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...requestOptions, headers, signal: controller.signal, credentials: "omit", cache: "no-store"
    });
    payload = response.status === 204 ? null : await response.json();
  } catch (error) {
    throw new Error(error.name === "AbortError"
      ? "The local connector took too long to respond. Check that it is running."
      : "Cannot reach the local connector. Start it, allow local device access in your browser, and check the trusted website address.");
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!response.ok && !(allowUnavailable && response.status === 503 && payload?.checks)) {
    throw new Error(payload?.error || `Request failed with ${response.status}`);
  }

  return payload;
}

/** Convert backend-relative media/download paths into browser-ready URLs. */
export function absoluteFileUrl(path) {
  if (!path) {
    return null;
  }
  const url = new URL(path, API_BASE.replace(/\/api$/, ""));
  if (mediaToken && url.origin === new URL(API_BASE).origin) url.searchParams.set("media_token", mediaToken);
  return url.toString();
}

/** Create the database project record before uploading the media file. */
export function createProject(payload) {
  return apiRequest("/projects", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

/** Return the dashboard's recent project list. */
export function listProjects() {
  return apiRequest("/projects");
}

/** Permanently delete a project and its generated artifacts. */
export async function deleteProject(projectId) {
  return apiRequest(`/projects/${projectId}`, { method: "DELETE" });
}

/** Return languages currently available from the configured translation provider. */
export function listLanguages(provider) {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return apiRequest(`/languages${query}`);
}

/** Return server defaults for per-project HY-MT2 generation settings. */
export function getTranslationSettings() {
  return apiRequest("/translation/settings");
}

/** Load project metadata, including status and media URLs. */
export function getProject(projectId) {
  return apiRequest(`/projects/${projectId}`);
}

/** Update processing options that can be changed before reprocessing. */
export function updateProject(projectId, payload) {
  return apiRequest(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

/** Upload a source video using the API's multipart `video` form field. */
export function uploadProjectVideo(projectId, file) {
  const form = new FormData();
  form.append("video", file);
  return apiRequest(`/projects/${projectId}/video`, {
    method: "POST",
    body: form,
    timeout: 0
  });
}

/** Queue the Celery transcription and translation workflow. */
export function processProject(projectId) {
  return apiRequest(`/projects/${projectId}/process`, {
    method: "POST"
  });
}

export function transcribeProject(projectId) {
  return apiRequest(`/projects/${projectId}/transcribe`, { method: "POST" });
}

export function translateProject(projectId) {
  return apiRequest(`/projects/${projectId}/translate`, { method: "POST" });
}

/** Queue the Celery FFmpeg render workflow. */
export function renderProject(projectId) {
  return apiRequest(`/projects/${projectId}/render`, {
    method: "POST"
  });
}

/** Generate an SRT export from the latest translated subtitle segments. */
export function exportProjectSrt(projectId) {
  return apiRequest(`/projects/${projectId}/export/srt`, {
    method: "POST"
  });
}

/** Fetch the lightweight polling status payload. */
export function getProjectStatus(projectId) {
  return apiRequest(`/projects/${projectId}/status`);
}

/** Load subtitle rows in playback order for the editor table. */
export function listSegments(projectId) {
  return apiRequest(`/projects/${projectId}/segments`);
}

/** Persist one subtitle edit without forcing the user to save the whole table. */
export function updateSegment(segmentId, payload) {
  return apiRequest(`/segments/${segmentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function mergeSegments(projectId, segmentIds, revisions) {
  return apiRequest(`/projects/${projectId}/segments/merge`, { method: "POST", body: JSON.stringify({ segment_ids: segmentIds, revisions }) });
}

export function splitSegment(segmentId, parts, revision) {
  return apiRequest(`/segments/${segmentId}/split`, { method: "POST", body: JSON.stringify({ parts, revision }) });
}

export function translateSegment(segmentId) {
  return apiRequest(`/segments/${segmentId}/translate`, { method: "POST", timeout: 180000 });
}
