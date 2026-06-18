# SubtitleD

SubtitleD is an MVP subtitle translation web app. It lets you create a project, upload a video, run a background processing job that extracts audio, creates aligned WhisperX transcript segments, translates them, edit the translated subtitles, export SRT, burn subtitles into the video with FFmpeg, and download the rendered MP4.

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

3. Open the app:

   - Frontend: http://localhost:5173
   - Backend health check: http://localhost:5000/health

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

Speaker diarization uses gated pyannote models from Hugging Face. When
`WHISPERX_DIARIZE=true`, which is the default, `HF_TOKEN` must be a Hugging Face
User Access Token with read access. A standard `read` token is enough for local
development; a fine-grained token also works if it can read the required pyannote
model repositories. A `write` token is not needed.

Before starting the worker, use the same Hugging Face account to accept the user
conditions for both required model repositories:

- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

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
and tests the Flask code, validates the Docker Compose file, builds the backend
and frontend images, and scans the repository for committed secrets.

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
- `WHISPER_DEVICE`: Whisper runtime device, default `cpu`
- `WHISPER_COMPUTE_TYPE`: Whisper compute type, default `int8`
- `WHISPER_MODEL_DIR`: Persistent model download/cache directory
- `WHISPERX_BATCH_SIZE`: WhisperX transcription batch size, default `16`
- `WHISPERX_DIARIZE`: Whether WhisperX should run speaker diarization, default `true`
- `HF_HOME`: Persistent Hugging Face cache directory, default `/app/storage/models/huggingface`
- `TORCH_HOME`: Persistent PyTorch cache directory, default `/app/storage/models/torch`
- `XDG_CACHE_HOME`: Persistent cache directory, default `/app/storage/models/cache`
- `HF_TOKEN`: Hugging Face `read` token used by WhisperX diarization; the token account must have accepted the pyannote model conditions
- `TRANSLATION_PROVIDER`: `mock` or `libretranslate`
- `LIBRETRANSLATE_URL`: LibreTranslate API base URL, default Docker service URL
- `LIBRETRANSLATE_API_KEY`: Optional API key for protected LibreTranslate instances
- `LIBRETRANSLATE_LOAD_ONLY`: Comma-separated LibreTranslate languages to install/load, defaulting to common MVP targets including Japanese
- `LIBRETRANSLATE_UPDATE_MODELS`: Whether LibreTranslate should download missing models
- `TRANSLATION_TIMEOUT_SECONDS`: Translation API timeout

## API Endpoints

- `POST /api/projects`: Create a project
- `GET /api/projects`: List projects
- `GET /api/projects/<project_id>`: Get project metadata
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

- Transcription uses WhisperX for aligned timestamps and speaker labels. The first run may download the selected model into `backend/storage/models`.
- Set `HF_TOKEN` to a Hugging Face read token when `WHISPERX_DIARIZE=true`, which is the default.
- Mock translation prefixes visible language labels and applies a tiny dictionary for common demo languages.
- `TRANSLATION_PROVIDER=libretranslate` sends subtitle text to the self-hosted LibreTranslate service for actual target-language translation.

Whisper is used for transcription only. Subtitle translation is handled separately because Whisper's built-in translation mode translates speech to English rather than arbitrary target languages.

WhisperX is required for transcription and is installed by the default backend image from `backend/requirements.txt`.
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
- WhisperX speaker diarization requires a Hugging Face token with access to the pyannote diarization model
- No progress percentages
- Subtitle styling is limited to FFmpeg's default SRT rendering
- Render quality depends on local FFmpeg support and source video codecs
- Automatic table creation is intended for local MVP development, not production migrations

## Future Improvements

- Transcription progress and model selection controls
- GPU-specific WhisperX worker tuning
- Additional translation providers
- Subtitle styling with ASS files
- User accounts
- Progress percentages
- Subtitle timing quality checker
