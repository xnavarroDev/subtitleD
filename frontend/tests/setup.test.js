import assert from "node:assert/strict";
import { test } from "node:test";
import { createSetupConfig, setupReadiness, sourceArchiveUrl } from "../src/setup.js";

test("setup download pins the website, model, and ports without credentials", () => {
  assert.deepEqual(createSetupConfig("https://subtitles.example", "base", "5001", "5003"), {
    version: 1, origin: "https://subtitles.example", whisper_model: "base", connector_port: 5001, kobold_port: 5003
  });
  assert.ok(!JSON.stringify(createSetupConfig("http://localhost:5173")).includes("TOKEN"));
});

test("setup rejects insecure websites, unsupported models, and invalid ports", () => {
  for (const origin of ["http://public.example", "https://example.com/page", "https://user:pass@example.com"]) {
    assert.throws(() => createSetupConfig(origin));
  }
  assert.throws(() => createSetupConfig("https://example.com", "unknown"));
  for (const port of [0, 5000.5, "bad", 65536]) assert.throws(() => createSetupConfig("https://example.com", "small", port));
});

test("transcription readiness does not depend on translation", () => {
  const report = { checks: ["database", "redis", "worker", "storage", "ffmpeg", "transcription"].map((name) => ({ name, status: "pass" })) };
  report.checks.push({ name: "translation", status: "fail" });
  assert.deepEqual(setupReadiness(report), { transcribe: true, translate: false, render: true });
  report.checks.find((check) => check.name === "worker").status = "fail";
  assert.deepEqual(setupReadiness(report), { transcribe: false, translate: false, render: false });
  assert.deepEqual(setupReadiness(null), { transcribe: false, translate: false, render: false });
});

test("source download uses main by default and can select a preview branch", () => {
  assert.match(sourceArchiveUrl(), /heads\/main\.zip$/);
  assert.match(sourceArchiveUrl("dev"), /heads\/dev\.zip$/);
});
