SubtitleD Companion - Windows preview

If you have the Setup installer, run it. Otherwise extract the full ZIP to a
permanent folder and double-click Install-Companion.cmd once. It registers the
website's Open Companion button for your Windows user. No administrator access
or separate Python installation is required. Keep the full folder together.

Install Docker Desktop if needed, then click Open Companion on the SubtitleD
website. Approve the website and choose Start and connect. The companion starts
processing and opens a connected workspace without a pairing code.

The source-build preview builds its processing image on first startup. Release
packages can include a published image digest to download it instead.
Transcription models download on first use. Prepare transcription downloads and
checks the model ahead of time. KoboldCpp translation is optional and currently
configured separately. GPU setup and automatic translator downloads are not yet
included. The local development website must already be running; production
users visit the hosted website and need neither Node.js nor this repository.

Closing the window keeps the companion in the system tray when available.
Stop processing interrupts running work but preserves files. Quitting the tray
app leaves Docker processing running. Project data, models, and settings live
under %LOCALAPPDATA%\SubtitleD and survive companion updates/uninstallation.

Portable preview cleanup: delete HKCU\Software\Classes\subtitled only if its
open command still points at this companion, then remove the extracted folder.
Use the Setup installer's normal Windows uninstall entry when available.
