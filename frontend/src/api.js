/**
 * @typedef {Object} Project
 * @property {string} id
 * @property {string} title
 * @property {string|null} source_video_path
 * @property {string|null} extracted_audio_path
 * @property {string|null} output_video_path
 * @property {string|null} srt_path
 * @property {string} status
 * @property {string} source_language
 * @property {string} target_language
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
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api"
).replace(/\/$/, "");

const API_ORIGIN = API_BASE.replace(/\/api$/, "");

/**
 * Shared JSON request helper.
 *
 * It intentionally leaves FormData headers alone so the browser can attach the
 * upload boundary for video files, while JSON requests get a default
 * Content-Type.
 */
async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // Keep the generic message when the response is not JSON.
    }
    throw new Error(message);
  }

  return response.json();
}

/** Convert backend-relative media/download paths into browser-ready URLs. */
export function absoluteFileUrl(path) {
  if (!path) {
    return null;
  }
  return path.startsWith("http") ? path : `${API_ORIGIN}${path}`;
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

/** Load project metadata, including status and media URLs. */
export function getProject(projectId) {
  return apiRequest(`/projects/${projectId}`);
}

/** Upload a source video using the API's multipart `video` form field. */
export function uploadProjectVideo(projectId, file) {
  const form = new FormData();
  form.append("video", file);
  return apiRequest(`/projects/${projectId}/video`, {
    method: "POST",
    body: form
  });
}

/** Queue the Celery transcription and translation workflow. */
export function processProject(projectId) {
  return apiRequest(`/projects/${projectId}/process`, {
    method: "POST"
  });
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
