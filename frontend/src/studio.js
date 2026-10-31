export function formatTimestamp(value, milliseconds = true) {
  const total = Math.round(Math.max(0, Number(value) || 0) * 1000);
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor(total / 60000) % 60;
  const seconds = Math.floor(total / 1000) % 60;
  const pad = (number) => String(number).padStart(2, "0");
  return `${hours ? `${pad(hours)}:` : ""}${pad(minutes)}:${pad(seconds)}${milliseconds ? `.${String(total % 1000).padStart(3, "0")}` : ""}`;
}

export function parseTimestamp(value) {
  const input = String(value).trim();
  if (!/^\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?$/.test(input)) return null;
  const parts = input.split(":").map(Number);
  if (parts.length > 1 && parts.slice(1).some((part) => part >= 60)) return null;
  const seconds = parts.reduce((total, part) => total * 60 + part, 0);
  return Number.isFinite(seconds) ? seconds : null;
}

export function segmentDraft(segment) {
  return {
    start_time: formatTimestamp(segment.start_time), end_time: formatTimestamp(segment.end_time),
    translated_text: segment.translated_text || "", speaker_label: segment.speaker_label || "",
  };
}

export function sameDraft(a, b) {
  return Boolean(a && b && ["start_time", "end_time", "translated_text", "speaker_label"].every((key) => a[key] === b[key]));
}

export function timelineLayout(segments, start, end) {
  if (!(end > start)) return [];
  const lanes = [];
  return segments.filter((segment) => segment.end_time > start && segment.start_time < end)
    .sort((a, b) => a.start_time - b.start_time)
    .map((segment) => {
      let lane = lanes.findIndex((boundary) => boundary <= segment.start_time);
      if (lane === -1) lane = lanes.length;
      lanes[lane] = segment.end_time;
      return {
        segment, lane,
        left: Math.max(0, (segment.start_time - start) / (end - start) * 100),
        width: (Math.min(end, segment.end_time) - Math.max(start, segment.start_time)) / (end - start) * 100,
      };
    });
}
