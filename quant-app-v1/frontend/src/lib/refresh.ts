import { useEffect, useState } from "react";

/**
 * User-selectable data refresh rate for the trading views.
 *
 * The desk quotes, chart candles and statistics all refetch on this interval
 * so the user-selected non-AI provider is queried as often as the user wants
 * (Fast = every 5s).
 */
const STORAGE_KEY = "gateway_ui_refresh_ms";

export const REFRESH_OPTIONS = [
  { value: 5000, label: "Fast · 5s" },
  { value: 15000, label: "Normal · 15s" },
  { value: 30000, label: "Relaxed · 30s" },
] as const;

export const DEFAULT_REFRESH_MS = 5000;

const CHANGE_EVENT = "gateway-refresh-change";

export function getRefreshMs(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const value = raw === null ? DEFAULT_REFRESH_MS : Number(raw);
    return Number.isFinite(value) && value >= 1000 ? value : DEFAULT_REFRESH_MS;
  } catch {
    return DEFAULT_REFRESH_MS;
  }
}

export function setRefreshMs(ms: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(ms));
  } catch {
    /* private mode — keep the session default */
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

/** Reactive read of the current refresh interval (re-renders on change). */
export function useRefreshMs(): number {
  const [value, setValue] = useState(getRefreshMs);
  useEffect(() => {
    const onChange = () => setValue(getRefreshMs());
    window.addEventListener(CHANGE_EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);
  return value;
}
