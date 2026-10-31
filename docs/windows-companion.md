# Windows Companion preview

The companion packages the Python launcher into a Windows application. Users do
not need Python, Node.js, a source checkout, a downloaded settings file, or copied
pairing codes when using the hosted website. Docker Desktop remains required.

## User flow

1. Install SubtitleD Companion using the Windows installer.
2. On the website, choose **Connect device → Open Companion** and accept the
   browser's request to open it.
3. Approve the exact website in the companion and choose **Start and connect**.
   Docker Desktop is opened if installed. The companion waits for it, starts the
   connector, and opens a connected website tab.
4. Add a video and transcribe. The transcription model downloads on first use;
   **Prepare transcription** can download/check it ahead of time.
5. HY-MT2 through KoboldCpp remains recommended. **Set up translation** offers
   one optional backup: NLLB 600M in CPU INT8 mode. Choosing Yes explicitly
   downloads, converts, and tests it, repairing an incomplete install when needed.
   It runs without KoboldCpp. Choosing No opens KoboldCpp downloads instead.
   NLLB's model license is CC-BY-NC 4.0 (non-commercial). There is no automatic
   LibreTranslate fallback or extra translation service in the companion.

Closing the window hides it in the system tray when tray support is available.
The tray's Quit action leaves Docker services running. **Stop processing** asks
before interrupting active work and preserves stored projects and models.
The companion does not start on Windows login automatically.

Data lives in `%LOCALAPPDATA%\SubtitleD\runtime\backend\storage`, with pairing
configuration in `%LOCALAPPDATA%\SubtitleD\.env.connector`. Updates copy only
shipped runtime files. Uninstalling the app preserves this data. Existing source
launcher data is not automatically migrated; stop that connector before using
the companion if you want to free its port. The companion uses its own Docker
project (`subtitled-companion`) and automatically chooses a free port when the
saved/default port is occupied. The website connection link includes this port;
users do not need to edit the website's address. KoboldCpp's port is skipped.

## Build and test

On Windows with Python 3.12 or later:

```powershell
python -m pip install -r packaging/companion-requirements.txt
python packaging/build_companion.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Without `--iscc`, the build produces a portable ZIP. Its included
`Install-Companion.cmd` registers the URL handler for the current user; leave the
extracted folder in a permanent location. The standard installer additionally
provides a Start menu entry and Windows uninstall support. Neither requires
administrator privileges.

Outputs are under `dist/companion`: installer, portable ZIP, checksums, and the
unpacked application. No private settings, videos, models, database files, or
repository test fixtures are bundled. The build uses PyInstaller's documented
[bundled runtime paths](https://pyinstaller.org/en/stable/runtime-information.html)
and Inno Setup's [registry entries](https://jrsoftware.org/ishelp/topic_registrysection.htm)
for a per-user `subtitled://` handler.

`--home <temporary-folder> --self-test` on the built EXE checks bundled sources
and Tcl without starting Docker or modifying the normal user data directory.

The manual **Build Windows companion preview** GitHub Actions workflow builds
reviewable artifacts. Its optional prebuilt-processing input publishes an image
to GHCR and packages the exact image digest. Make that image publicly pullable
before distributing the app. A release package downloads this image rather
than installing/building backend dependencies on the user's computer. Without
an image digest, development builds retain the source-build fallback.

After publishing a tested installer, configure the website build:

```dotenv
VITE_COMPANION_DOWNLOAD_URL=https://your-release-host/SubtitleD-Companion-Setup.exe
```

The wizard does not advertise a nonexistent installer download when that setting
is absent. Local development still needs its website server running separately.
Builds are currently unsigned; signing, a public installer/image release, clean
machine testing, and HTTPS-to-local browser permission testing remain release
gates. Native GPU/runtime packaging and managed KoboldCpp/model downloads remain
future work.

## Pairing

The URL handler accepts only a validated HTTPS website origin (or loopback HTTP
for development). It cannot request arbitrary commands, file paths, ports, or
models. Each website handoff asks for approval in the companion. Command-line
options cannot be mixed into a website URL invocation.

Once authenticated local startup succeeds, the companion requests a random
two-minute pairing ticket. The connector stores its hash and binds it to the
approved origin. The companion opens the website with this ticket in the URL
fragment; the long-lived connector secret is never put in a link. The website
immediately removes the fragment, redeems the ticket once, and keeps credentials
in the tab's session storage. Reloading that tab reconnects without another
approval. Closing its session requires another companion handoff or manual code.

Host validation, exact Origin validation, and existing bearer protection still
apply. Redemption needs the browser's matching Origin header and is the only
new unauthenticated API route; issuance requires the existing bearer credential.
Tickets expire, cannot be replayed, and are cleared by connector restart.
