import assert from "node:assert/strict";
import { test } from "node:test";
import { formatTimestamp, parseTimestamp, timelineLayout } from "../src/studio.js";

test("timestamps round across minute/hour boundaries and preserve milliseconds", () => {
  assert.equal(formatTimestamp(59.9996), "01:00.000");
  assert.equal(formatTimestamp(3661.125), "01:01:01.125");
  assert.equal(formatTimestamp(12.4, false), "00:12");
  assert.equal(parseTimestamp("01:01:01.125"), 3661.125);
  assert.equal(parseTimestamp("00:12.400"), 12.4);
  assert.equal(parseTimestamp("12.4"), 12.4);
  assert.equal(parseTimestamp("00:00"), 0);
});

test("invalid timing is rejected rather than silently converted", () => {
  for (const value of ["", "-1", "00:60", "1:90:00", "1:2:3:4", "NaN", "1e3", "12.1234", "00:no"]) {
    assert.equal(parseTimestamp(value), null, value);
  }
});

test("timeline clips actual boundaries and gives overlapping captions separate lanes", () => {
  const segments = [
    { id: "second", start_time: 12, end_time: 16 },
    { id: "first", start_time: 8, end_time: 14 },
    { id: "after", start_time: 16, end_time: 22 },
    { id: "outside", start_time: 25, end_time: 30 },
  ];
  const result = timelineLayout(segments, 10, 20);
  assert.deepEqual(result.map((clip) => [clip.segment.id, clip.lane]), [["first", 0], ["second", 1], ["after", 0]]);
  assert.equal(result[0].left, 0);
  assert.equal(result[0].width, 40);
  assert.equal(result[2].left, 60);
  assert.equal(result[2].width, 40);
  assert.equal(segments[0].id, "second", "Layout must not reorder project records");
  assert.deepEqual(timelineLayout(segments, 20, 20), []);
});
