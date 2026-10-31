export const SETUP_STEPS = ["Install", "Start", "Connect", "Check tools"];

export function createSetupConfig(origin, whisperModel = "small", connectorPort = 5000, koboldPort = 5002) {
  const url = new URL(origin);
  if (url.origin !== origin || !["https:", "http:"].includes(url.protocol)
      || (url.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) {
    throw new Error("Setup requires an HTTPS website or a local development website.");
  }
  if (!["base", "small", "medium", "large-v3"].includes(whisperModel)) throw new Error("Choose a supported transcription model.");
  for (const port of [connectorPort, koboldPort]) {
    if (!Number.isInteger(Number(port)) || Number(port) < 1024 || Number(port) > 65535) throw new Error("Ports must be between 1024 and 65535.");
  }
  return { version: 1, origin, whisper_model: whisperModel, connector_port: Number(connectorPort), kobold_port: Number(koboldPort) };
}

export function setupReadiness(report) {
  const checks = new Map((report?.checks || []).map((check) => [check.name, check]));
  const ready = (names) => names.every((name) => ["pass", "warn"].includes(checks.get(name)?.status));
  const shared = ["database", "redis", "worker", "storage"];
  return {
    transcribe: ready([...shared, "ffmpeg", "transcription"]),
    translate: ready([...shared, "translation"]),
    render: ready([...shared, "ffmpeg"])
  };
}

export function sourceArchiveUrl(ref = import.meta.env?.VITE_CONNECTOR_REF || "main") {
  return `https://github.com/xnavarroDev/subtitleD/archive/refs/heads/${encodeURIComponent(ref)}.zip`;
}
