import assert from "node:assert/strict";
import { test } from "node:test";
import { companionLink, consumeCompanionHandoff } from "../src/companion.js";

test("companion links pass only the website origin", () => {
  const link = new URL(companionLink("https://subtitles.example"));
  assert.equal(link.protocol, "subtitled:");
  assert.equal(link.hostname, "connect");
  assert.equal(link.searchParams.get("origin"), "https://subtitles.example");
});

test("one-time handoff is removed from the address before connection starts", () => {
  const ticket = "x".repeat(43);
  const calls = [];
  const result = consumeCompanionHandoff({ pathname: "/", search: "", hash: `#companion_ticket=${ticket}&connector=http%3A%2F%2Flocalhost%3A5000%2Fapi` }, { replaceState: (...args) => calls.push(args) });
  assert.deepEqual(result, { ticket, address: "http://localhost:5000/api" });
  assert.deepEqual(calls, [[null, "", "/"]]);
  assert.equal(consumeCompanionHandoff({ hash: "#other" }, {}), null);
  assert.throws(() => consumeCompanionHandoff({ pathname: "/", search: "", hash: "#companion_ticket=invalid" }, { replaceState() {} }));
});
