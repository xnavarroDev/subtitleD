# Initial deployment readiness

The first deployment is a tester-facing static website connected to processing
on the user's device. The Windows companion and manual source launcher are
available; final frontend design and broader installation automation will follow.

## Included in this checkpoint

- A browseable workspace with device status and optional setup instructions.
- Windows installer/tray companion, Python included, automatic port selection,
  an isolated Compose project, and single-use website pairing links.
- Manual Python launcher for other systems and advanced setup.
- Loopback API, exact trusted origins, bearer protection, expiring read-only media
  access, and authenticated startup checks.
- Separate transcription and translation, retained transcripts after translation
  failure, bilingual editing, passage retranslation, and reversible merge/split.
- HY-MT2 as the recommended translator and explicitly installed NLLB 600M INT8
  as the only backup. No automatic LibreTranslate fallback.
- Manual artifact/image build workflow; published processing images are pinned
  by digest. No website deployment or installer release runs automatically.

See [companion packaging](windows-companion.md), [manual connection and hosting](local-connector.md),
and [caption editing](caption-editing.md) for the detailed workflows.

## Before merging into main and inviting hosted testers

1. Push the dev checkpoint, review its complete diff, and require CI to pass.
2. Build and test the matching companion installer. Sign and publish the installer;
   if using a prebuilt processing image, ensure it is publicly pullable.
3. Deploy an HTTPS preview from `frontend` (`npm run build`, publish `dist`) with
   SPA fallback. Set `VITE_CONNECTOR_REF=dev` for preview source downloads and
   `VITE_COMPANION_DOWNLOAD_URL` to the tested installer. Use the exact preview
   origin for pairing. Local installer binaries/settings are not committed.
4. Test installation on a clean Windows device: missing/stopped Docker, first
   startup, occupied ports, repeated launch, pairing, update, and uninstall.
   Confirm updates/uninstall preserve projects, models, and pairing settings.
5. Exercise HTTPS-to-local access in supported browsers: permission prompts,
   pairing, upload, source seeking, caption save/merge/split, SRT/MP4 download,
   rendered playback, and reconnect. Local browser tests do not prove this path.
6. Run a short real video through transcription, HY-MT2 translation, editing,
   export, and rendering. Repeat translation with KoboldCpp stopped and the NLLB
   backup installed. Check failure recovery and project data preservation.
7. Verify protections from the hosted preview: wrong code/origin/Host rejected,
   expired/replayed pairing links rejected, media tokens cannot change projects,
   and only the loopback API port is published.

## Verification available at this checkpoint

- Backend suite: 206 passed, one Windows-only test skipped in Linux.
- Frontend: 16 tests passed; production build passed.
- Windows launcher/companion tests, packaged runtime startup, and installer build passed.
- Browser checks covered disconnected browsing, pairing, seeking, drafts, saving,
  merge/retranslate/split, export controls, and desktop/mobile layout.
- A real Mandarin-to-English NLLB translation passed offline with KoboldCpp
  unavailable. Backup setup also verified the existing model offline without
  downloading another copy.

These checks do not replace clean-device installation, a full real-video
pipeline, or deployed HTTPS/browser testing. CI provides the authoritative
results for the pushed revision.

## Follow-up work

- Frontend polish and simpler model/setup management.
- Signed public companion releases and managed KoboldCpp/model downloads.
- GPU selection, native runtime packaging, and removal of the Docker requirement.
- Worker cancellation, interrupted-job recovery, and broader platform support.

Current limitations: CPU WhisperX by default; substantial first downloads;
optional speaker detection needs model access; NLLB is non-commercial licensed;
retranscribing/retranslating a whole project replaces its manual caption edits;
an interrupted worker may need operator recovery.
