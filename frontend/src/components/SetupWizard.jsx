import { useEffect, useState } from "react";
import { createSetupConfig, SETUP_STEPS, setupReadiness, sourceArchiveUrl } from "../setup";
import { companionLink, companionDownloadUrl } from "../companion";

const TOOLS = [
  ["transcribe", "Transcription", "WhisperX listens to the video and saves aligned words."],
  ["translate", "Translation", "KoboldCpp translates the saved transcript with your local model."],
  ["render", "Video export", "FFmpeg burns your reviewed subtitles into a video."]
];

export default function SetupWizard({ address, setAddress, code, setCode, connected, busy, report, checking, error, onConnect, onCheck, onDisconnect, onFinish }) {
  const [step, setStep] = useState(code ? 2 : 0);
  const [model, setModel] = useState("small");
  const [port, setPort] = useState("5000");
  const [koboldPort, setKoboldPort] = useState("5002");
  const [feedback, setFeedback] = useState("");
  const [manual, setManual] = useState(false);
  const origin = window.location.origin;
  const readiness = setupReadiness(report);

  useEffect(() => {
    setStep(connected ? 3 : code ? 2 : 0);
    setFeedback("");
  }, [connected]);

  async function copyCommand() {
    try {
      const settings = createSetupConfig(origin, model, port, koboldPort);
      await navigator.clipboard.writeText(`python local_connector.py start --origin ${settings.origin} --whisper-model ${model} --port ${settings.connector_port}`);
      setFeedback("Launch command copied.");
    } catch (caught) {
      setFeedback(caught.message || "Select and copy the command below.");
    }
  }

  function downloadSettings() {
    try {
      const settings = createSetupConfig(origin, model, port, koboldPort);
      const url = URL.createObjectURL(new Blob([JSON.stringify(settings, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "subtitled-setup.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setAddress(`http://localhost:${settings.connector_port}/api`);
      setFeedback("Put subtitled-setup.json inside the extracted SubtitleD folder, beside Start-SubtitleD.cmd.");
    } catch (caught) {
      setFeedback(caught.message);
    }
  }

  return (
    <div className="setup-wizard">
      {!connected && !manual ? <section className="companion-setup" aria-label="Connect with SubtitleD Companion">
        <p className="eyebrow">Your device, connected</p>
        <h2>One companion for local processing</h2>
        <p>Open SubtitleD Companion, then choose <strong>Start and connect</strong>. It starts the local tools and connects this website without copying codes.</p>
        <div className="companion-steps"><article><span>1</span><div><h3>Install once</h3><p>The Windows companion includes its own Python runtime. Docker Desktop is still required for this preview.</p>{companionDownloadUrl() ? <a className="button-link" href={companionDownloadUrl()}>Download for Windows</a> : <small>The packaged download will appear here when a companion release is available.</small>}</div></article><article><span>2</span><div><h3>Open and approve</h3><p>Approve <strong>{origin}</strong> in the companion. It opens a connected workspace when ready.</p><a className="button-link primary" href={companionLink(origin)} onClick={() => setFeedback("Accept your browser's prompt to open SubtitleD Companion. If nothing opens, install the companion first, or use manual setup below.")}>Open Companion</a></div></article></div>
        <p className="connection-help">Models download on first use. You can start with transcription and add KoboldCpp translation later.</p>
        <div className="setup-footer"><button onClick={() => { setManual(true); setStep(2); }}>I already have the connector</button><button className="ghost-button" onClick={() => { setManual(true); setStep(0); }}>Manual setup / other systems</button></div>
      </section> : null}
      {manual || connected ? <>
      {!connected ? <button className="ghost-button" onClick={() => setManual(false)}>← Back to Companion setup</button> : null}
      <nav className="setup-stepper" aria-label="Device setup steps">
        {SETUP_STEPS.map((label, index) => <button type="button" key={label} aria-current={step === index ? "step" : undefined} onClick={() => { setStep(index); setFeedback(""); }} disabled={index === 3 && !connected}><span>{index + 1}</span>{label}</button>)}
      </nav>
      {step === 0 ? <section aria-label="Install prerequisites">
        <p className="eyebrow">Step 1 of 4</p><h2>Get your device ready</h2>
        <p>You install the processing tools once. SubtitleD then keeps videos, models, transcripts, and exports on this computer.</p>
        <div className="setup-install-grid">
          <article><h3>Python 3.10 or later</h3><p>Runs the small launcher. Enable Python's PATH option during installation.</p><a href="https://www.python.org/downloads/" target="_blank" rel="noreferrer">Get Python</a></article>
          <article><h3>Docker Desktop</h3><p>Runs WhisperX, FFmpeg, and the connector. Open Docker Desktop and use Linux containers.</p><a href="https://www.docker.com/products/docker-desktop/" target="_blank" rel="noreferrer">Get Docker Desktop</a></article>
          <article><h3>SubtitleD connector files</h3><p>Download the source ZIP and extract it to a normal folder. Keep the full folder together.</p><a href={sourceArchiveUrl()} target="_blank" rel="noreferrer">Download SubtitleD ZIP</a></article>
        </div>
        {origin.startsWith("http:") ? <p className="connection-help">For this local website mode, also install <a href="https://nodejs.org/en/download" target="_blank" rel="noreferrer">Node.js 20 or later</a>. A hosted HTTPS website does not need Node.js on your device.</p> : null}
        <p className="connection-help">The first setup downloads substantial dependencies. Leave room for models, your source video, and a rendered copy. GPU setup is not automatic in this release.</p>
        <div className="setup-footer"><button className="primary-action" onClick={() => setStep(1)}>Next: start local processing</button><button onClick={() => setStep(2)}>I already have the connector</button></div>
      </section> : null}
      {step === 1 ? <section aria-label="Start local processing">
        <p className="eyebrow">Step 2 of 4</p><h2>Start local processing</h2>
        <p>Choose your transcription model, then give the launcher this website's settings.</p>
        <label>Transcription model<select value={model} onChange={(event) => setModel(event.target.value)}><option value="base">Base — faster CPU transcription</option><option value="small">Small — balanced default</option><option value="medium">Medium — slower, more memory</option><option value="large-v3">Large v3 — most demanding</option></select></label>
        <details className="advanced-settings"><summary>Advanced: local ports</summary><div className="form-row"><label>Connector port<input type="number" min="1024" max="65535" value={port} onChange={(event) => setPort(event.target.value)} /></label><label>KoboldCpp port<input type="number" min="1024" max="65535" value={koboldPort} onChange={(event) => setKoboldPort(event.target.value)} /></label></div></details>
        <ol className="setup-steps"><li><button onClick={downloadSettings}>Download setup settings</button> Put the downloaded <code>subtitled-setup.json</code> inside the extracted SubtitleD folder.</li><li>On Windows, double-click <strong>Start-SubtitleD.cmd</strong>. It checks prerequisites, starts local processing, waits for the connector, and opens this website.</li><li>Keep the launcher's pairing code handy. The first build can take a while. WhisperX downloads its model on first transcription.</li></ol>
        <details className="advanced-settings"><summary>Terminal setup / macOS / Linux</summary><p>Run from the extracted folder:</p><pre><code>{`python local_connector.py start --setup-file subtitled-setup.json`}</code></pre><p>Or use this command for the default KoboldCpp port:</p><pre><code>{`python local_connector.py start --origin ${origin} --whisper-model ${model} --port ${port}`}</code></pre><button onClick={copyCommand}>Copy launch command</button></details>
        <div className="setup-footer"><button onClick={() => setStep(0)}>Back</button><button className="primary-action" onClick={() => { try { const settings = createSetupConfig(origin, model, port, koboldPort); setAddress(`http://localhost:${settings.connector_port}/api`); setStep(2); } catch (caught) { setFeedback(caught.message); } }}>Next: connect my device</button></div>
      </section> : null}
      {step === 2 ? <section aria-label="Pair local connector">
        <p className="eyebrow">Step 3 of 4</p><h2>Connect your device</h2>
        <p>Paste the pairing code printed by the launcher. When your browser asks, allow this website to access your local device.</p>
        <form onSubmit={onConnect} className="connection-form">
          <label>Local connector address<input required type="url" value={address} onChange={(event) => setAddress(event.target.value)} placeholder="http://localhost:5000/api" /></label>
          <label>Pairing code<input type="password" autoComplete="off" value={code} onChange={(event) => setCode(event.target.value)} placeholder="Code from the local launcher" /></label>
          <button className="primary-action" disabled={busy}>{busy ? "Connecting..." : "Connect my device"}</button>
          <small>The address is remembered on this browser. The code stays in this tab's session. An unprotected connector is accepted only by a local development website.</small>
        </form>
        <details className="advanced-settings"><summary>Connection troubleshooting</summary><ul><li>Confirm Docker Desktop and the connector are running.</li><li>The trusted website must be exactly <strong>{origin}</strong>. Rerun setup after changing website addresses.</li><li>Allow local-device access in browser site settings.</li><li>Recover your code with <code>python local_connector.py code</code>.</li><li>Run <code>python local_connector.py doctor</code> for local checks, or <code>python local_connector.py logs</code> for startup messages.</li><li>If port 5000 is occupied, restart with <code>--port 5001</code> and update the address above.</li></ul></details>
        <div className="setup-footer"><button onClick={() => setStep(1)}>Back</button></div>
      </section> : null}
      {step === 3 && connected ? <section aria-label="Check local tools">
        <p className="eyebrow">Step 4 of 4</p><h2>Check your local tools</h2>
        <p>{checking ? "Checking your local services..." : "Each step checks its own tools. You can transcribe before setting up translation."}</p>
        <div className="setup-tools">{TOOLS.map(([id, title, description]) => <article key={id} className={readiness[id] ? "is-ready" : "needs-attention"}><h3>{title}</h3><strong>{!report ? "Waiting for checks" : readiness[id] ? "Ready to start" : "Needs attention"}</strong><p>{description}</p></article>)}</div>
        <details className="advanced-settings" open={report && !readiness.translate}><summary>Set up local translation with KoboldCpp</summary><ol><li><a href="https://github.com/LostRuins/koboldcpp/releases" target="_blank" rel="noreferrer">Download KoboldCpp</a> for your device.</li><li><a href="https://huggingface.co/tencent/Hy-MT2-7B-GGUF/tree/main" target="_blank" rel="noreferrer">Download an HY-MT2 GGUF</a> supported by your hardware, then select it in KoboldCpp.</li><li>Set KoboldCpp's port to <strong>{koboldPort}</strong> (or your configured port) and start it. Loading the model can take a while.</li><li>The Docker connector must be able to reach KoboldCpp through <code>host.docker.internal</code>. Check its bind settings and your firewall if translation remains unavailable. Keep the API private.</li><li>Click <strong>Check readiness</strong> below. Select HY-MT2 when creating your project.</li></ol><p>WhisperX is already included in the connector; it does not need a separate installation. Optional speaker detection needs a Hugging Face token and model access; leave it off for your first test.</p></details>
        <details className="advanced-settings"><summary>Install the single backup translator</summary><p>NLLB 600M runs locally on CPU without KoboldCpp. In the companion, choose <strong>Set up translation → Yes</strong>. The model downloads only when you choose to install it. Allow several GB for downloading and conversion; the final model uses INT8.</p><p>The <a href="https://huggingface.co/facebook/nllb-200-distilled-600M" target="_blank" rel="noreferrer">model license is CC-BY-NC 4.0 (non-commercial)</a>. Once installed, HY-MT2 can fall back to NLLB, or you can select NLLB directly in project settings. No LibreTranslate service is required.</p><pre><code>python local_connector.py prepare-translation</code></pre><p>Check readiness again after installation. NLLB translates the combined passage; surrounding conversation context is supported by HY-MT2.</p></details>
        <details className="advanced-settings"><summary>Prepare transcription models before uploading</summary><p>To download and check the selected WhisperX model in advance, run:</p><pre><code>python local_connector.py prepare</code></pre><p>This may download large files. Language alignment models can still download during the first transcription. The launcher uses CPU transcription in this release.</p></details>
        {report ? <details className="device-checks"><summary>Detailed diagnostics</summary><ul>{report.checks.map((check) => <li key={check.name} className={`device-check ${check.status}`}><strong>{check.name}: {check.status}</strong><span>{check.message}</span></li>)}</ul></details> : null}
        <div className="setup-footer"><button disabled={checking} onClick={onCheck}>{checking ? "Checking..." : "Check readiness"}</button><button onClick={onDisconnect}>Disconnect</button><button className="primary-action" onClick={onFinish}>Open local workspace</button></div>
        <small>Readiness checks confirm configuration and dependencies. A short test video is still needed to verify actual model processing. Closing the website does not stop local jobs.</small>
      </section> : null}
      </> : null}
      {feedback ? <p role="status" className="notice">{feedback}</p> : null}
      {error ? <div className="notice error" role="alert">{error}</div> : null}
    </div>
  );
}
