# Hosted SubtitleD, local processing

## User setup

Requirements: Docker Desktop running Linux containers, Python 3.10 or later for
the launcher, enough disk space for videos and models, and KoboldCpp with an HY-MT2
GGUF for translation. The launcher itself uses only Python's standard library.
WhisperX, FFmpeg, and the Python application dependencies run inside Docker.

1. Open the website's four-step setup wizard. Install Python and Docker Desktop,
   download the SubtitleD ZIP, and extract it to a normal folder.
2. Start Docker Desktop with Linux containers. On the wizard's Start step, select
   the CPU transcription model and download `subtitled-setup.json`.
3. Move that settings file into the extracted SubtitleD folder. On Windows,
   double-click `Start-SubtitleD.cmd`. It keeps its window open so you can read
   errors and copy the pairing code. On macOS/Linux run
   `python local_connector.py setup --setup-file subtitled-setup.json`.
4. The launcher checks prerequisites, starts processing, waits for authenticated
   readiness, and opens the configured website. The first image build installs
   substantial ML dependencies. Later starts reuse it; backend source changes
   automatically trigger a rebuild. `--rebuild` forces one explicitly.
5. On the Connect step, enter `http://localhost:5000/api` (or the selected port)
   and the printed pairing code. Accept the browser's local-device permission.
   Check the tools, then click **Open local workspace**. A missing translator
   does not prevent you from opening the workspace or transcribing.
6. Create a project, select a video, then choose **Transcribe with WhisperX**.
   On first use, WhisperX downloads its selected model. Review the generated
   original transcript in the caption editor.
7. Launch KoboldCpp with your HY-MT2 model on port `5002`. Keep its API accessible
   from Docker Desktop through `host.docker.internal`. Choose **Translate transcript**.
8. Edit translated captions, create/download an SRT, or render/download a subtitled MP4.

Without the downloaded settings file, double-clicking the Windows launcher or
running `python local_connector.py` opens an interactive setup. Choose the website,
transcription model, connector port, and KoboldCpp port. Existing pairing is retained.
You can also keep using the direct startup command:

```bash
python local_connector.py start --origin https://your-subtitled-site.example
```

Keep an existing local website running separately by adding `--no-browser`. Otherwise
an HTTP localhost website address selects local website mode: install Node.js 20 or
later, then the launcher installs missing frontend dependencies, starts Vite, and
opens the browser. Keep the launcher window open for this mode. Ctrl+C closes its
Vite process while leaving the Docker processing services running. Hosted HTTPS
website mode does not need Node.js on the user's computer.

The website does not start native software itself. Docker Desktop and the local
connector must be running whenever you use local projects. Browser selection sends
the video to your own local connector, not to the website's host. Closing the tab
does not stop an already queued job; reconnect and reopen the project to see status.
The original transcript is read-only; edits to translated caption timing or wording
are replaced when you translate again. Re-transcribing replaces the transcript and
requires a fresh translation. A new video upload clears the previous transcript,
captions, and exports to prevent mixing results from different videos.

Useful commands:

```bash
python local_connector.py code
python local_connector.py logs
python local_connector.py stop
python local_connector.py start
python local_connector.py doctor
python local_connector.py prepare
python local_connector.py start --rebuild
python local_connector.py start --port 5001 --no-browser
```

`stop` preserves local videos, models, database, and Redis data. The dedicated
Compose project is `subtitled-local`. Its SQLite database is
`backend/storage/connector.db`; it is separate from the development database.
Only the chosen API port (5000 by default) is published, bound to `127.0.0.1`.
Redis is internal to Docker. Do not use the same port for this stack and the old
development backend simultaneously. A detected conflict explains how to use
`--port 5001`; update the website connector address to match.

`doctor` checks Docker/Compose, Linux-container mode, free storage, and the saved
connector connection. `prepare` explicitly downloads and checks the selected
WhisperX transcription model in an isolated CLI process. It does not require
KoboldCpp or download speaker models; language alignment may still download on
first use. Avoid preparing models concurrently with a long processing job on a
memory-constrained machine. This first release guides installation of Docker,
Python, and KoboldCpp rather than installing those applications automatically.

## Translation and optional features

The local connector initially uses CPU WhisperX with the `small` model and INT8
compute. It does not configure GPU passthrough. CPU processing may take a long time
for large videos; the HY-MT2 model also needs adequate memory on the host device.

The launcher creates a git-ignored `.env.connector`. To change KoboldCpp's port or
model name, add entries there and run `python local_connector.py start` again:

```dotenv
HY_MT_BASE_URL=http://host.docker.internal:5002/v1
HY_MT_MODEL=Hy-MT2-7B
WHISPER_MODEL_SIZE=small
```

KoboldCpp's bind configuration and host firewall must permit the Docker backend to
reach it. Do not expose its API publicly. The browser only talks to the SubtitleD
connector, so KoboldCpp does not need the website's CORS configuration.

Speaker detection is optional. If enabled for a project, accept the required
Hugging Face pyannote model conditions and add `HF_TOKEN` to `.env.connector`.
Keep that file private. Ordinary transcription does not need the diarization token.

The minimal local stack does not start LibreTranslate or automatically download
NLLB. HY-MT2 is recommended, with NLLB 600M INT8 as the single backup. Install it
explicitly through the companion's **Set up translation** control or
`python local_connector.py prepare-translation`. The command installs/repairs
the model and tests an actual translation. If neither translator is ready, the
job reports a setup error while preserving the saved transcript.

## Hosting the frontend

Deploy only the `frontend` directory to a static HTTPS host:

```bash
npm ci
npm test
npm run build
```

Publish `frontend/dist` (or `dist` when the host's project root is `frontend`).
No hosted Flask API, Redis, database, GPU, or media storage is required. The
connection screen lets each user select their local connector at runtime; do not
set `VITE_API_BASE_URL` to your hosted server for this mode.

The wizard's source ZIP link defaults to branch `main`. For a dev preview, set
`VITE_CONNECTOR_REF=dev` at build time and push the matching launcher changes to
that branch before testing downloads. The downloaded settings are versioned JSON
containing only website, model, and ports; they contain no pairing code. The
launcher imports only those supported fields and creates its own local secret.
See [initial deployment readiness](initial-deployment.md) for the merge checklist.

React Router uses browser paths. Configure the host to serve `index.html` for
application paths such as `/projects/<id>` while serving assets normally.
`frontend/public/_redirects` supplies this rule for Netlify/compatible hosts;
`frontend/vercel.json` supplies it for Vercel when `frontend` is the project root.
Other hosts need their equivalent SPA fallback. The public `_headers` and Vercel
configuration also set `Referrer-Policy: no-referrer`.

If you add a Content Security Policy, allow the loopback connector in `connect-src`
and `media-src`. Do not apply cross-origin isolation or embed this app in an iframe
without checking how those headers affect local media and device permissions.

## Connection security and compatibility

The dedicated stack uses Waitress instead of the Flask debug server. Connector
mode requires a randomly generated pairing secret and an explicit trusted website
origin. It validates Host and Origin and requires bearer authorization for API
requests. Browser CORS preflights do not require the secret. Pairing does not expose
the secret to the hosting server; it is kept in the tab's session storage.

Video elements and ordinary download links use a separate signed, read-only media
token valid for 12 hours. It authorizes media/download GET and HEAD routes only,
not project listing or mutations. The interface renews it every six hours while
open. Treat signed URLs as private; they can be used to read local media until they
expire. Disconnect clears the browser's credentials but does not revoke previously
issued media URLs. Rotate `CONNECTOR_TOKEN` in `.env.connector` and restart to revoke
all existing pairing and media credentials.

HTTPS websites accessing loopback services are subject to browser-specific
local-device permissions, CORS, mixed-content, and media policies. Use the real
deployed origin to verify the complete connect/upload/playback/download flow in
every browser you support. The first request is initiated by the **Connect my
device** button so permission prompts have a user action. No browser security flags,
public tunnels, or router port forwarding should be required. If a browser blocks
the flow, use the local development frontend while investigating compatibility.

This implementation assumes the browser and processing connector run on the same
computer. A phone accessing a desktop connector over the LAN is not supported by
the loopback-only connection screen. The Windows installer is available as a preview;
automatic GPU configuration, job cancellation, and recovery from an interrupted
worker/container remain future work. Failed queue submission releases the project's busy state; an abruptly killed
worker can leave a project marked active and currently needs operator recovery.

## Verification before public rollout

Run backend tests and frontend tests/build. Validate the dedicated Compose file
with a nonsecret placeholder `CONNECTOR_TOKEN` and a trusted test origin, then
perform a real model smoke test from the deployed HTTPS website: connect, upload a
short clip, transcribe with KoboldCpp stopped, start KoboldCpp, translate, edit,
export SRT, render, download, and reconnect after closing the tab. Confirm an
untrusted website and an invalid pairing code cannot read projects or start jobs.
