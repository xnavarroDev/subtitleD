import assert from "node:assert/strict";
import { test } from "node:test";
import { adjacentSelection, splitDraft } from "../src/captionEditing.js";

test("splitting a merged passage restores original timings and translations", () => {
  const merge_parts = [{ start_time: 0, end_time: 2, original_text: "你不是说", translated_text: "Didn't you say" }, { start_time: 3, end_time: 5, original_text: "他走了吗", translated_text: "he left?" }];
  assert.deepEqual(splitDraft({ merge_parts, translated_text: "Didn't you say he left?" }), merge_parts);
  const edited = splitDraft({ merge_parts, translated_text: "Didn't you say he had already left?" });
  assert.equal(edited[0].translated_text, "Didn't you say he had already left?");
  assert.equal(edited[1].translated_text, "");
  assert.equal(edited[1].start_time, 3);
});

test("custom splits handle Mandarin without spaces and preserve Unicode characters", () => {
  const original_text = "他😀昨天已经走了吗";
  const parts = splitDraft({ original_text, translated_text: "Did he leave yesterday?", start_time: 0, end_time: 6 }, 2);
  assert.equal(parts[0].original_text + parts[1].original_text, original_text);
  assert.equal(parts[0].end_time, 2);
  assert.equal(parts[1].start_time, 2);
  assert.equal(adjacentSelection([{id:"a"},{id:"b"},{id:"c"}], ["a","c"]), false);
  assert.equal(adjacentSelection([{id:"a"},{id:"b"},{id:"c"}], ["b","a"]), true);
});
