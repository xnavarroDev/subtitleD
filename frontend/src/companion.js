export function companionLink(origin) {
  return `subtitled://connect?${new URLSearchParams({ origin })}`;
}

export function companionDownloadUrl() {
  // Set only after a built, tested installer has been published.
  return import.meta.env?.VITE_COMPANION_DOWNLOAD_URL || null;
}

export function consumeCompanionHandoff(location, history) {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.has("companion_ticket")) return null;
  // Strip the short-lived ticket before fetching, rendering, or analytics.
  history.replaceState(null, "", location.pathname + location.search);
  const ticket = params.get("companion_ticket");
  const address = params.get("connector");
  if (!ticket || !/^[A-Za-z0-9_-]{32,128}$/.test(ticket)) throw new Error("Invalid connection link. Open SubtitleD from the companion again.");
  return { ticket, address };
}
