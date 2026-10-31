import { createContext, useEffect, useState } from "react";
import { connectDevice, forgetConnection, getDiagnostics, savedConnection, pairWithCompanion } from "../api";
import { consumeCompanionHandoff } from "../companion";
import "./DeviceConnection.css";
import SetupWizard from "./SetupWizard";

export const DeviceSessionContext = createContext({ connected: false });

// Read once, before React StrictMode remounts effects; ticket redemption is single-use.
let startupConnection;
function initialConnection() {
  if (!startupConnection) {
    startupConnection = (async () => {
      const handoff = consumeCompanionHandoff(window.location, window.history);
      if (handoff) return { address: handoff.address, code: await pairWithCompanion(handoff.address, handoff.ticket) };
      const saved = savedConnection();
      if (!saved.code) return null;
      await connectDevice(saved.address, saved.code);
      return saved;
    })();
  }
  return startupConnection;
}

export default function DeviceConnection({ children }) {
  const saved = savedConnection();
  const [address, setAddress] = useState(saved.address);
  const [code, setCode] = useState(saved.code);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const [checking, setChecking] = useState(false);
  const [sessionRevision, setSessionRevision] = useState(0);
  const [showSetup, setShowSetup] = useState(false);
  const [workspaceDirty, setWorkspaceDirty] = useState(false);

  useEffect(() => {
    let active = true;
    function complete(session) {
      if (!active || !session) return;
      setAddress(session.address);
      setCode(session.code);
      setConnected(true);
      setSessionRevision((value) => value + 1);
      checkReadiness();
    }
    function failed(caught) {
      if (!active) return;
      setError(caught.message);
      setShowSetup(true);
    }
    async function handoffChanged() {
      try {
        const handoff = consumeCompanionHandoff(window.location, window.history);
        if (!handoff) return;
        setBusy(true);
        const code = await pairWithCompanion(handoff.address, handoff.ticket);
        complete({ address: handoff.address, code });
      } catch (caught) {
        failed(caught);
      } finally {
        if (active) setBusy(false);
      }
    }
    initialConnection().then(complete).catch(failed);
    window.addEventListener("hashchange", handoffChanged);
    return () => { active = false; window.removeEventListener("hashchange", handoffChanged); };
  }, []);

  async function checkReadiness() {
    setChecking(true);
    try {
      setReport(await getDiagnostics());
      setError(null);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setChecking(false);
    }
  }

  async function connect(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await connectDevice(address, code);
      setSessionRevision((value) => value + 1);
      setConnected(true);
      await checkReadiness();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  // Renew read-only media access while the interface stays open. Long-running
  // processing stays in the local worker even when this browser tab is closed.
  useEffect(() => {
    if (!connected) return undefined;
    const timer = setInterval(async () => {
      try {
        await connectDevice(address, code);
        setSessionRevision((value) => value + 1);
        setReport(null);
        await checkReadiness();
      } catch (caught) {
        setError(caught.message);
        setConnected(false);
        setShowSetup(true);
      }
    }, 6 * 60 * 60 * 1000);
    return () => clearInterval(timer);
  }, [connected, address, code]);

  function disconnect() {
    forgetConnection();
    setConnected(false);
    setReport(null);
    setCode("");
    setError(null);
    setShowSetup(true);
  }

  return (
    <DeviceSessionContext.Provider value={{
      connected, sessionRevision, workspaceDirty, setWorkspaceDirty,
      openSetup: () => setShowSetup(true),
      setupPanel: showSetup ? (
        <section className="device-panel panel" aria-label="Device setup">
          <div className="connection-panel-heading"><span>{connected ? report && !report.ready ? "Connected · some tools need attention" : "Connected to your device" : "Connect your device to SubtitleD"}</span><button onClick={() => setShowSetup(false)} aria-label="Close device setup">Close</button></div>
          <SetupWizard address={address} setAddress={setAddress} code={code} setCode={setCode} connected={connected} busy={busy} report={report} checking={checking} error={error} onConnect={connect} onCheck={checkReadiness} onDisconnect={disconnect} onFinish={() => setShowSetup(false)} />
        </section>
      ) : null,
    }}>{children}</DeviceSessionContext.Provider>
  );
}
