import assert from "node:assert/strict";
import { test } from "node:test";

function storage() {
  const data = new Map();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key)
  };
}
globalThis.localStorage = storage();
globalThis.sessionStorage = storage();
globalThis.window = { location: { hostname: "subtitles.example" } };
const api = await import("../src/api.js");

test("paired requests carry credentials; media URLs use only the read-only ticket", async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify(url.endsWith("/connector/session") ? {
      protocol_version: 1, capabilities: ["transcribe", "translate"], protected: true, media_token: "read-only-ticket"
    } : []));
  };
  await api.connectDevice("http://localhost:5000", "pairing-secret");
  await api.transcribeProject("project");
  await api.translateProject("project");
  await api.deleteProject("project");
  for (const { options } of requests) {
    assert.equal(options.headers.get("Authorization"), "Bearer pairing-secret");
    assert.equal(options.credentials, "omit");
  }
  assert.equal(requests[1].url, "http://localhost:5000/api/projects/project/transcribe");
  assert.equal(requests[2].url, "http://localhost:5000/api/projects/project/translate");
  assert.equal(requests[3].options.method, "DELETE");
  const media = api.absoluteFileUrl("/api/projects/project/media/source");
  assert.match(media, /media_token=read-only-ticket/);
  assert.ok(!media.includes("pairing-secret"));
  assert.equal(api.absoluteFileUrl("https://other.example/file"), "https://other.example/file");
  api.forgetConnection();
  assert.ok(!api.absoluteFileUrl("/api/projects/project/media/source").includes("media_token"));
  assert.equal(api.savedConnection().code, "");
});

test("hosted interface rejects an unprotected or incompatible local service", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({
    protocol_version: 1, capabilities: ["transcribe", "translate"], protected: false
  }));
  await assert.rejects(api.connectDevice("http://localhost:5000/api", "code"), /protected local connector/);
  globalThis.fetch = async () => new Response(JSON.stringify({ protocol_version: 2 }));
  await assert.rejects(api.connectDevice("http://localhost:5000/api", "code"), /compatible/);
  assert.equal(api.savedConnection().code, "");
});

test("connection only accepts loopback addresses without embedded credentials", async () => {
  for (const address of ["https://attacker.example/api", "http://localhost:5000/api?key=secret", "http://name:secret@localhost:5000", "http://localhost:5000/other"]) {
    await assert.rejects(api.connectDevice(address, "code"), /local connector address/);
  }
});

test("readiness failures still display structured tool checks", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ ready: false, checks: [{ name: "translation", status: "fail" }] }), { status: 503 });
  const report = await api.getDiagnostics();
  assert.equal(report.ready, false);
  assert.equal(report.checks[0].name, "translation");
});

test("pairing errors are actionable and uploads preserve multipart boundaries", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ error: "Enter the pairing code" }), { status: 401 });
  await assert.rejects(api.connectDevice("http://localhost:5000/api", "wrong"), /pairing code/);
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.headers.has("Content-Type"), false);
    assert.ok(options.body instanceof FormData);
    return new Response(JSON.stringify({ id: "project" }));
  };
  await api.uploadProjectVideo("project", new Blob(["video"]));
});
