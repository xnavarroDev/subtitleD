# SubtitleD

SubtitleD is an MVP subtitle translation web app. It extracts aligned WhisperX words, uses deterministic readable caption boundaries, lets each project choose a translation engine, keeps the raw transcript visible for auditing, and produces editable subtitles, SRT exports, and rendered video. Supported local engines are HY-MT2 through KoboldCpp, NLLB through CTranslate2, and LibreTranslate.

## Tech Stack

- Frontend: React, JavaScript, Vite
- Backend: Flask, SQLAlchemy, REST blueprints
- Database: PostgreSQL
- Background jobs: Celery with Redis
- Speech-to-text: WhisperX with alignment and optional speaker diarization
- Video processing: FFmpeg
- Local development: Docker Compose

## Quick Start

1. Copy the example environment file if you want to customize values:

   ```bash
   cp .env.example .env
   ```

2. Start the full stack:

   ```bash
   docker compose up --build
   ```

3. To use the KoboldCpp engine, load `tencent/Hy-MT2-7B-GGUF` in a current KoboldCpp build on host port
   `5002`. The Q4_K_M and Q6_K variants are practical local defaults. SubtitleD
   sends translation prompts and per-project sampling settings to its
   OpenAI-compatible `/v1/chat/completions` endpoint.

4. To use the local NLLB engine, install it explicitly. This downloads and
   converts the pinned 600M checkpoint to CTranslate2 INT8 and stores it in the
   persistent model directory:

   ```bash
   docker compose exec backend flask --app run setup-local-translation
   docker compose restart worker
   ```

   Until this is run, SubtitleD remains usable through its local
   LibreTranslate fallback and displays a readiness warning.

5. Open the app:

   - Frontend: http://localhost:5173
   - Backend health check: http://localhost:5000/health
   - Runtime diagnostics: http://localhost:5000/api/diagnostics

The backend automatically creates development tables on startup. Uploaded and generated files are stored under `backend/storage`.

## Docker Development Workflow

Use `--build` when you need Docker to rebuild the images. For everyday code changes,
start the already-built containers without rebuilding.

First run, or after dependency/Dockerfile changes:

```bash
docker compose up --build
```

WhisperX is installed by default. If speaker diarization is enabled, set `HF_TOKEN`
before starting the backend and worker:

```bash
HF_TOKEN=your-hugging-face-token docker compose up --build backend worker
```

In PowerShell, set that environment variable with `$env:HF_TOKEN=...` before running `docker compose up --build backend worker`.

### Hugging Face Token For Diarization

Speaker diarization uses the gated pyannote Community-1 model from Hugging Face. When a project
enables speaker detection, `HF_TOKEN` must be a Hugging Face
User Access Token with read access. A standard `read` token is enough for local
development; a fine-grained token also works if it can read the required pyannote
model repository. A `write` token is not needed.

Before starting the worker, use the same Hugging Face account to accept the model's
user conditions:

- [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)

Then add the token to `.env`:

```bash
HF_TOKEN=hf_your_read_token_here
```

If you do not need speaker labels, set `WHISPERX_DIARIZE=false` and leave
`HF_TOKEN` empty. WhisperX transcription and timestamp alignment can still run
without the token; diarization is the part that needs gated model access.

Normal development:

```bash
docker compose up
```

What updates automatically:

- Frontend changes under `frontend/` are picked up by Vite hot reload.
- Backend API changes under `backend/` reload the Flask server because it runs in debug mode.
- Uploaded videos, generated audio, renders, exports, and downloaded models stay in `backend/storage`.

What needs a manual action:

- Worker code changes: `docker compose restart worker`
- Backend dependency changes in `backend/requirements.txt`: `docker compose up --build backend worker`
- Frontend dependency changes in `frontend/package.json` or `frontend/package-lock.json`: `docker compose up --build frontend`
- Dockerfile or Compose changes: `docker compose up --build`

If rebuilds are slow, check that you are using `docker compose up` for normal edits.
The Compose file mounts the source code into the containers, so recompiling the full
image on every change is usually unnecessary.

## CI Pipeline

GitHub Actions runs the CI workflow on pull requests and pushes to `main`.
The workflow builds the Vite frontend, installs backend dependencies, compiles
and tests the Flask code, runs `pip check`, validates the Docker Compose file,
builds the backend and frontend images, verifies live diagnostics with and
without a worker, and scans the repository for committed secrets.

A separate weekly/manual deep diagnostics workflow loads the WhisperX and
pyannote models using the `HF_TOKEN` repository secret. It skips cleanly when
that secret is not configured and does not run on every pull request.

## Deployment Status

This repository is ready for local MVP development with Docker Compose, but it is
not production-hardened yet. Before deploying publicly, add production database
migrations, authentication, HTTPS and trusted host/CORS settings, secret
management, persistent storage/backups for uploads and generated media, and a
production web server setup for the Flask API and built frontend assets.

## Environment Variables

The Docker Compose file provides sensible defaults. You can override these in `.env`.

- `DATABASE_URL`: SQLAlchemy database URL
- `POSTGRES_DB`: PostgreSQL database name
- `POSTGRES_USER`: PostgreSQL user
- `POSTGRES_PASSWORD`: PostgreSQL password
- `REDIS_URL`: Redis URL
- `CELERY_BROKER_URL`: Celery broker URL
- `CELERY_RESULT_BACKEND`: Celery result backend URL
- `STORAGE_DIR`: Backend storage directory
- `CORS_ORIGINS`: Comma-separated frontend origins allowed by Flask
- `VITE_API_BASE_URL`: Frontend API base URL
- `WHISPER_MODEL_SIZE`: WhisperX model size, such as `tiny`, `base`, or `small`
- `ASR_QUALITY_PRESET`: `fast`, `balanced`, `accurate`, or `gpu-accurate`; used when `WHISPER_MODEL_SIZE` is not explicitly set
- `WHISPER_DEVICE`: Whisper runtime device, default `cpu`
- `WHISPER_COMPUTE_TYPE`: Whisper compute type, default `int8`
- `WHISPER_MODEL_DIR`: Persistent model download/cache directory
- `WHISPERX_BATCH_SIZE`: WhisperX transcription batch size, default `16`
- `WHISPERX_DIARIZE`: Legacy/global WhisperX diarization default; projects now opt in and default to `false`
- `WHISPERX_DIARIZATION_OUTPUT`: `exclusive` (default) uses Community-1's non-overlapping timeline for transcript speaker assignment; `regular` is a rollback option
- `WHISPER_MODEL_CACHE_SIZE`: Maximum full Whisper models retained by a worker, default `1`
- `WHISPERX_JA_ALIGN_MODEL`: Japanese CTC alignment model repository
- `WHISPERX_JA_ALIGN_REVISION`: Pinned Japanese model revision containing Safetensors weights
- `WHISPERX_JA_REQUIRE_SAFETENSORS`: Refuse legacy pickle weights for Japanese alignment, default `true`
- `WHISPERX_ALIGNMENT_FAILURE_MODE`: `fallback` uses estimated timing if the Japanese model cannot load; `fail` stops processing
- `HF_HOME`: Persistent Hugging Face cache directory, default `/app/storage/models/huggingface`
- `TORCH_HOME`: Persistent PyTorch cache directory, default `/app/storage/models/torch`
- `XDG_CACHE_HOME`: Persistent cache directory, default `/app/storage/models/cache`
- `HF_TOKEN`: Hugging Face `read` token used by WhisperX diarization; the token account must have accepted the Community-1 model conditions
- `TRANSLATION_PROVIDER`: Server-level provider mode for legacy/default checks; `routed`, `nllb-ct2`, `libretranslate`, `hy-mt2`, or `mock`
- `TRANSLATION_DEFAULT_PROVIDER`: Default project translation engine and routed-provider fallback, default `hy-mt2`
- `TRANSLATION_ROUTE_OVERRIDES`: Optional comma-separated routes such as `ja>en=libretranslate`
- `LIBRETRANSLATE_URL`: LibreTranslate API base URL, default Docker service URL
- `LIBRETRANSLATE_API_KEY`: Optional API key for protected LibreTranslate instances
- `LIBRETRANSLATE_UPDATE_MODELS`: Whether LibreTranslate should download missing models
- `LIBRETRANSLATE_START_PERIOD`: Health-check grace period while language models load, default `30m`
- `TRANSLATION_TIMEOUT_SECONDS`: Translation API timeout
- `LOCAL_MT_MODEL`, `LOCAL_MT_MODEL_REVISION`: Pinned Hugging Face NLLB model and Safetensors revision
- `LOCAL_MT_REQUIRE_SAFETENSORS`: Refuse unsafe legacy pickle checkpoints during local model setup
- `LOCAL_MT_MODEL_DIR`, `LOCAL_MT_TOKENIZER_DIR`: Persistent converted model and tokenizer directories
- `LOCAL_MT_DEVICE`, `LOCAL_MT_COMPUTE_TYPE`: CTranslate2 device and precision, default `cpu` and `int8`
- `LOCAL_MT_BATCH_SIZE`, `LOCAL_MT_BEAM_SIZE`, `LOCAL_MT_MAX_INPUT_TOKENS`: Local translation inference controls
- `LOCAL_MT_TOKENIZER_CACHE_SIZE`: Bounded source-language tokenizer cache; the full NLLB translator is shared
- `HY_MT_BASE_URL`, `HY_MT_API_KEY`, `HY_MT_MODEL`: KoboldCpp endpoint and loaded HY-MT2 model identity
- `HY_MT_TIMEOUT_SECONDS`, `HY_MT_RETRIES`: HY-MT2 request resilience controls
- `HY_MT_TEMPERATURE`, `HY_MT_TOP_P`, `HY_MT_TOP_K`, `HY_MT_REPETITION_PENALTY`: Default generation settings; projects can override them
- `HY_MT_MAX_TOKENS`: Maximum translation response budget, default `256`
- `HY_MT_CONTEXT_CAPTIONS`: Neighboring semantic units supplied as read-only background context, default `2`
- `LLM_BASE_URL`: OpenAI-compatible API URL, e.g. `http://host.docker.internal:5002/v1` for KoboldCpp
- `LLM_MODEL`: Model identifier sent to the chat-completions endpoint
- `LLM_TIMEOUT_SECONDS`, `LLM_TEMPERATURE`, `LLM_RETRIES`: Reserved local-LLM request controls for future features
- `LLM_JSON_MODE`: Request OpenAI-style JSON response mode when supported by the server
- `TRANSLATION_UNIT_MAX_SECONDS`: Maximum duration translated as one semantic unit before fitting it back to caption timestamps
- `smooth_speaker_fragments` project option: Repair suspicious short diarization fragments in the effective translation stream; default `false`
- `SOURCE_RECONSTRUCTION_MAX_GAP_SECONDS`, `SOURCE_RECONSTRUCTION_MAX_FRAGMENT_CHARS`: Conservative reconstruction limits
- `SOURCE_REVIEW_CONFIDENCE_THRESHOLD`: Confidence below which subtitle rows show a source-review warning
- `CAPTION_MAX_DURATION_SECONDS`, `CAPTION_MAX_CHARS`, `CAPTION_LINE_CHARS`, `CAPTION_PAUSE_SECONDS`: Subtitle readability controls
- `DIAGNOSTICS_TIMEOUT_SECONDS`: Timeout for Redis and FFmpeg readiness checks, default `2`
- `DIAGNOSTICS_DEEP_CACHE_TTL_SECONDS`: Seconds to reuse a deep diagnostic report, default `300`
- `WORKER_PING_TIMEOUT_SECONDS`: Timeout for the Celery worker readiness ping, default `2`
- `WORKER_HEARTBEAT_INTERVAL_SECONDS`: Seconds between worker heartbeat updates, default `5`
- `WORKER_HEARTBEAT_TTL_SECONDS`: Seconds before a missing heartbeat marks a worker unavailable, default `15`
- `WORKER_HEARTBEAT_KEY_PREFIX`: Redis key prefix for worker heartbeat records
- `MIN_FREE_STORAGE_BYTES`: Free-space threshold that produces a storage warning, default `1073741824`

LibreTranslate is left without `LT_LOAD_ONLY`, so it installs all available
language models. The first startup can therefore take substantially longer and
use more disk space. The project form reads the selected provider's `/languages`
catalog and only displays models that are actually available. The web app starts
while LibreTranslate is loading; project processing remains unavailable until
the translation service is ready.

## Runtime Diagnostics

`GET /api/diagnostics` runs quick checks for the database, Redis, Celery worker,
storage, FFmpeg, WhisperX configuration, and the required translation provider.
It returns HTTP `200` when ready and `503` when a required subsystem fails.

Use `deep=true` to validate WhisperX package compatibility, gated diarization access,
and the pinned Japanese Safetensors revision.
The expensive deep transcription result is cached briefly while database,
worker, storage, FFmpeg, and translation checks are rerun on every request.
Add `refresh=true` to force a fresh provider result:

```text
GET /api/diagnostics?deep=true&refresh=true
```

The same checks are available from Docker through the Flask CLI:

```bash
docker compose run --rm backend flask --app run diagnostics
docker compose run --rm backend flask --app run diagnostics --deep --refresh
docker compose run --rm backend flask --app run diagnostics --load-models
docker compose run --rm backend flask --app run diagnostics --json-output
```

The API deep check validates package compatibility and remote model access without
loading large models into the Flask web process. Use the CLI-only `--load-models`
option for full model initialization in an isolated container process.

Processing and rendering endpoints run cheap job-specific preflights before
queueing. They return HTTP `503` with a structured `diagnostics` report when a
required provider, file, worker, storage path, or native dependency is not ready.
Workers repeat the same checks before doing expensive work to catch environment
drift between the API and worker containers.

The public diagnostics API returns statuses and actionable messages without
exposing worker hostnames, package versions, exact disk capacity, or language
inventories. The CLI JSON output retains those details for local operators.

Worker readiness uses a Redis heartbeat published from a background thread, so a
`solo` Celery worker remains visible while it is busy with a long WhisperX task.
Celery control ping remains as a startup and backward-compatibility fallback.

## API Endpoints

- `GET /api/diagnostics`: Check runtime subsystem readiness; supports `deep` and `refresh`
- `GET /api/languages`: Get languages for the configured provider; accepts `provider=hy-mt2-kobold`, `provider=nllb-ct2`, or `provider=libretranslate`
- `GET /api/translation/settings`: Get provider options and default HY-MT2 sampling settings
- `POST /api/projects`: Create a project
- `GET /api/projects`: List projects
- `GET /api/projects/<project_id>`: Get project metadata
- `PATCH /api/projects/<project_id>`: Update project options, including an atomic `translation_provider` and `target_language` selection
- `POST /api/projects/<project_id>/video`: Upload a video file
- `POST /api/projects/<project_id>/process`: Start transcription and translation
- `GET /api/projects/<project_id>/segments`: List subtitle segments
- `PATCH /api/segments/<segment_id>`: Update subtitle text or timing
- `POST /api/projects/<project_id>/export/srt`: Generate an SRT file
- `GET /api/projects/<project_id>/export/srt/download`: Download generated SRT
- `POST /api/projects/<project_id>/render`: Start FFmpeg subtitle burn-in
- `GET /api/projects/<project_id>/download`: Download rendered MP4
- `GET /api/projects/<project_id>/status`: Get project status
- `GET /api/projects/<project_id>/media/source`: Preview uploaded video
- `GET /api/projects/<project_id>/media/rendered`: Preview rendered video

## Development Notes

The app keeps transcription and translation behind small interfaces so provider internals can evolve without changing the REST API:

- Transcription uses WhisperX for aligned timestamps. Speaker detection is an opt-in project setting because Pyannote adds substantial compute. The first run may download the selected model into `backend/storage/models`.
- Japanese uses a separately pinned Safetensors alignment revision. If that model cannot
  load and `WHISPERX_ALIGNMENT_FAILURE_MODE=fallback`, processing continues with
  proportional estimated timing, displays an `Estimated timing` marker, and records a
  non-fatal warning. Other alignment errors remain fatal.
- Set `HF_TOKEN` to a Hugging Face read token for projects that enable speaker detection.
- Mock translation prefixes visible language labels and applies a tiny dictionary for common demo languages.
- Projects store a `translation_provider` value of `hy-mt2-kobold`, `nllb-ct2`, or `libretranslate`; the selected engine is used the next time the project is processed.
- Changing a processed project's translation engine or target language preserves its existing captions for review, invalidates generated exports, and requires reprocessing before export or rendering.
- `TRANSLATION_PROVIDER=hy-mt2` or the default routed provider sends semantic source units to HY-MT2 through KoboldCpp when no per-project provider is available.

Whisper is used for transcription only. Subtitle translation is handled separately because Whisper's built-in translation mode translates speech to English rather than arbitrary target languages.

Raw WhisperX words remain immutable and auditable. A separate effective stream
may reassign suspicious one- or two-character diarization fragments when they
touch a longer low-confidence phrase; this changes boundary selection, not the
stored recognition. Deterministic punctuation, pause, speaker, duration, and
character rules choose every caption boundary. Adjacent boundaries are grouped
into short semantic units for local translation, then target wording is fitted
back onto the original timestamps. The LLM never controls timestamps or caption
coverage.

The recommended translator is HY-MT2-7B running as a GGUF through KoboldCpp.
Neighboring source units and project glossary terms may be supplied as read-only
context, but HY-MT2 never controls timestamps. Empty, untranslated, repetitive,
explanatory, or unreasonably long responses are rejected. SubtitleD then falls
back to the revision-pinned NLLB-200 distilled 600M CTranslate2 model and finally
LibreTranslate. This is a conservative quality gate, not a semantic quality
score. Projects that select NLLB use the same local NLLB primary with
LibreTranslate fallback, while projects that select LibreTranslate call
LibreTranslate directly. Each API segment exposes
translator/model provenance, reconstruction provenance, translation-unit ID,
timing quality, and low-confidence warnings.

NLLB-200 is licensed CC-BY-NC-4.0. This local configuration is intended for
noncommercial use; replace or re-evaluate the model license before commercial
deployment. The future provider interface can also host an Apache-2.0 MADLAD
checkpoint on hardware capable of running its larger 3B+ models.

Projects can provide a glossary of expected names and technical terms. SubtitleD passes it to WhisperX as recognition hints and HY-MT2 as terminology guidance, while persisting the untouched aligned words and confidence scores for auditing. Speaker-fragment smoothing is a separate project option, disabled by default, so diarization can remain enabled without changing brief speaker assignments. Temperature, top-p, top-k, repetition penalty, output tokens, and context depth can be adjusted per project.

WhisperX is required for transcription and is installed by the default backend image from `backend/requirements.txt`.
Speaker diarization uses WhisperX 3.8 with pyannote.audio 4 and the Community-1 pipeline. SubtitleD uses Community-1's exclusive speaker timeline by default to reduce ambiguous word assignment during overlapping turns. It cannot recover an interruption when diarization fails to detect or correctly cluster the speaker. Set `WHISPERX_DIARIZATION_OUTPUT=regular` only to compare or roll back assignment behavior. Keep **Smooth short speaker fragments** disabled when genuine short interjections must retain their speaker. Caches from the legacy 3.1 pipeline are ignored and may be removed separately if disk space is needed.
Model caches are directed into `/app/storage/models`, which is bind-mounted to `backend/storage/models`, so repeated `docker compose up` and image rebuilds should not re-download the same Hugging Face, Torch, or Whisper model files. The backend Dockerfile also uses a BuildKit pip cache to speed up dependency rebuilds.

## Troubleshooting

If a transcription dependency fails with an error like `libctranslate2... cannot enable executable stack`, rebuild the backend and worker images. The Dockerfile clears that native library flag during image build:

```bash
docker compose build backend
docker compose up -d backend worker
```

## Known Limitations

- No authentication or user accounts yet
- Translation quality depends on the configured LibreTranslate language models
- WhisperX speaker diarization requires a Hugging Face token with access to the pyannote Community-1 model
- Processing progress is word-based; WhisperX itself does not yet expose fine-grained progress
- Subtitle styling is limited to FFmpeg's default SRT rendering
- Render quality depends on local FFmpeg support and source video codecs
- Automatic table creation is intended for local MVP development, not production migrations

## Future Improvements

- Transcription progress and model selection controls
- GPU-specific WhisperX worker tuning
- Additional translation providers
- Subtitle styling with ASS files
- User accounts
- Subtitle timing quality checker
