# SubtitleD

SubtitleD is an MVP subtitle translation web app. It lets you create a project, upload a video, run a background processing job that extracts audio, creates timestamped transcript segments with local faster-whisper, translates them, edit the translated subtitles, export SRT, burn subtitles into the video with FFmpeg, and download the rendered MP4.

## Tech Stack

- Frontend: React, JavaScript, Vite
- Backend: Flask, SQLAlchemy, REST blueprints
- Database: PostgreSQL
- Background jobs: Celery with Redis
- Speech-to-text: faster-whisper, with WhisperX planned as an optional future provider
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
- `TRANSCRIPTION_PROVIDER`: `faster_whisper` or `whisperx`; `whisperx` currently falls back to faster-whisper
- `WHISPER_MODEL_SIZE`: Local faster-whisper model, such as `tiny`, `base`, or `small`
- `WHISPER_DEVICE`: Whisper runtime device, default `cpu`
- `WHISPER_COMPUTE_TYPE`: Whisper compute type, default `int8`
- `WHISPER_BEAM_SIZE`: Whisper decode beam size
- `WHISPER_VAD_FILTER`: Whether faster-whisper should filter nonspeech audio
- `WHISPER_MODEL_DIR`: Persistent model download/cache directory
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

The app keeps provider selection behind small interfaces so you can swap real services in without changing the REST API:

- `TRANSCRIPTION_PROVIDER=faster_whisper` uses local faster-whisper speech-to-text. The first run may download the selected model into `backend/storage/models`.
- `TRANSCRIPTION_PROVIDER=whisperx` is accepted as a future provider name, but this build logs that WhisperX is unavailable and falls back to faster-whisper.
- Mock translation prefixes visible language labels and applies a tiny dictionary for common demo languages.
- `TRANSLATION_PROVIDER=libretranslate` sends subtitle text to the self-hosted LibreTranslate service for actual target-language translation.

Whisper is used for transcription only. Subtitle translation is handled separately because Whisper's built-in translation mode translates speech to English rather than arbitrary target languages.

WhisperX diarization is planned for a later implementation pass. Optional dependency notes live in `backend/requirements-whisperx.txt`, but the current app does not require WhisperX to run.

## Troubleshooting

If faster-whisper fails with an error like `libctranslate2... cannot enable executable stack`, rebuild the backend and worker images. The Dockerfile clears that native library flag during image build:

```bash
docker compose build backend
docker compose up -d backend worker
```

## Known Limitations

- No authentication or user accounts yet
- Translation quality depends on the configured LibreTranslate language models
- Speaker diarization is reserved for the future WhisperX provider
- No progress percentages
- Subtitle styling is limited to FFmpeg's default SRT rendering
- Render quality depends on local FFmpeg support and source video codecs
- Automatic table creation is intended for local MVP development, not production migrations

## Future Improvements

- Transcription progress and model selection controls
- WhisperX diarization with a GPU-accelerated worker profile
- Additional translation providers
- Subtitle styling with ASS files
- User accounts
- Progress percentages
- Subtitle timing quality checker
