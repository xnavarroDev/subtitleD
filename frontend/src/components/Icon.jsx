const shapes = {
  warning: <><path d="m12 3 10 18H2zM12 9v5" /><path d="M12 17h.01" /></>,
  projects: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  captions: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M6 10h4m4 0h4M6 14h7m3 0h2" /></>,
  settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="2" /><circle cx="15" cy="17" r="2" /></>,
  device: <><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 9h6v6H9zM9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3" /></>,
  play: <path d="m8 5 11 7-11 7z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  previous: <path d="M5 5v14m14-14L8 12l11 7z" />,
  next: <path d="M19 5v14M5 5l11 7-11 7z" />,
  replay: <><path d="M3 11a9 9 0 1 1 3 8M3 4v7h7" /></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  export: <><path d="M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6" /></>,
  save: <><path d="M5 3h12l4 4v14H3V3zM7 3v6h10V3M7 21v-7h10v7" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  timeline: <path d="M4 5v14M9 8v8m5-12v16m5-12v8" />,
  fullscreen: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />,
  volume: <><path d="m11 4-6 5H2v6h3l6 5zM15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" /></>,
};

export default function Icon({ name, size = 16 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{shapes[name] || shapes.captions}</svg>;
}
