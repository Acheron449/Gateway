import { useEffect, useRef, useState } from "react";

/**
 * "Last updated" indicator: shows a wall-clock time plus how long ago the
 * data refreshed. Pass `at` (epoch ms) when a page knows its last fetch time;
 * otherwise it uses the moment this component first mounted (≈ page load).
 * Re-renders every 10s so the "ago" value stays live.
 */
export function LastUpdated({ at, label = "Updated" }: { at?: number; label?: string }) {
  const mountRef = useRef<number>(Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(id);
  }, []);

  const stamp = at ?? mountRef.current;
  const elapsed = Math.max(0, Math.floor((now - stamp) / 1000));

  let ago: string;
  if (elapsed < 5) ago = "just now";
  else if (elapsed < 60) ago = `${elapsed}s ago`;
  else if (elapsed < 3600) ago = `${Math.floor(elapsed / 60)}m ago`;
  else ago = `${Math.floor(elapsed / 3600)}h ago`;

  const time = new Date(stamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <span className="last-updated" title={`${label} at ${time}`}>
      <span className="last-updated-dot" aria-hidden="true" />
      {label} {time} · {ago}
    </span>
  );
}
