function halves(text) {
  const characters = Array.from(text);
  const middle = Math.floor(characters.length / 2);
  let boundary = middle;
  for (let distance = 0; distance < middle; distance++) {
    const candidate = [middle + distance, middle - distance].find(index => /\s/.test(characters[index] || ""));
    if (candidate !== undefined) { boundary = candidate; break; }
  }
  return [characters.slice(0, boundary).join("").trim(), characters.slice(boundary).join("").trim()];
}

export function splitDraft(segment, playhead) {
  if (segment.merge_parts?.length) {
    const unchanged = segment.translated_text === segment.merge_parts.map(part => part.translated_text.trim()).join(" ");
    return segment.merge_parts.map((part, index) => ({ ...part, translated_text: unchanged ? part.translated_text : index === 0 ? segment.translated_text : "" }));
  }
  const boundary = playhead > segment.start_time + .05 && playhead < segment.end_time - .05
    ? playhead : (segment.start_time + segment.end_time) / 2;
  const sources = halves(segment.original_text);
  const translations = halves(segment.translated_text);
  return sources.map((source, index) => ({ original_text: source, translated_text: translations[index], start_time: index ? boundary : segment.start_time, end_time: index ? segment.end_time : boundary }));
}

export function adjacentSelection(segments, ids) {
  const indices = segments.map((segment, index) => ids.includes(segment.id) ? index : -1).filter(index => index >= 0);
  return indices.length >= 2 && indices.length === ids.length && indices.at(-1) - indices[0] + 1 === indices.length;
}
