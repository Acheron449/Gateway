/**
 * Shared chart preferences: data provider, active indicators, favourites.
 *
 * Two independent toolbars render these controls (markets/overview chart and
 * the paper-trading desk chart), so state lives in localStorage and syncs
 * across instances via a window CustomEvent.
 */
import { useEffect, useState } from "react";

export const CHART_PROVIDER_KEY = "gateway_ui_chart_provider";
export const CHART_INDICATORS_KEY = "gateway_ui_chart_indicators";
export const CHART_FAVORITES_KEY = "gateway_ui_chart_indicator_favs";

const CHANGE_EVENT = "gateway:chart-prefs-changed";

export interface ChartPrefs {
  /** Provider id as returned by GET /history/providers ("yahoo" by default). */
  provider: string;
  /** Active indicator ids rendered on the chart, in overlay order. */
  indicators: string[];
  /** Favourited indicator ids (starred in the indicator panel). */
  favorites: string[];
}

function readList(key: string): string[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is string => typeof value === "string");
  } catch {
    return [];
  }
}

function readProvider(): string {
  try {
    return localStorage.getItem(CHART_PROVIDER_KEY) || "yahoo";
  } catch {
    return "yahoo";
  }
}

export function readChartPrefs(): ChartPrefs {
  return {
    provider: readProvider(),
    indicators: readList(CHART_INDICATORS_KEY),
    favorites: readList(CHART_FAVORITES_KEY),
  };
}

function writeChartPrefs(update: Partial<ChartPrefs>): ChartPrefs {
  const next: ChartPrefs = { ...readChartPrefs(), ...update };
  try {
    if (update.provider !== undefined) localStorage.setItem(CHART_PROVIDER_KEY, next.provider);
    if (update.indicators !== undefined) {
      localStorage.setItem(CHART_INDICATORS_KEY, JSON.stringify(next.indicators));
    }
    if (update.favorites !== undefined) {
      localStorage.setItem(CHART_FAVORITES_KEY, JSON.stringify(next.favorites));
    }
  } catch {
    // Storage unavailable (private mode) — in-memory state still works.
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
  return next;
}

export interface ChartPrefsActions {
  setProvider: (id: string) => void;
  toggleIndicator: (id: string) => void;
  toggleFavorite: (id: string) => void;
}

/** React hook over the shared chart preferences. */
export function useChartPrefs(): [ChartPrefs, ChartPrefsActions] {
  const [prefs, setPrefs] = useState<ChartPrefs>(() => readChartPrefs());

  useEffect(() => {
    const onChange = (): void => setPrefs(readChartPrefs());
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);

  const actions: ChartPrefsActions = {
    setProvider: (id) => setPrefs(writeChartPrefs({ provider: id })),
    toggleIndicator: (id) =>
      setPrefs(
        writeChartPrefs({
          indicators: prefs.indicators.includes(id)
            ? prefs.indicators.filter((value) => value !== id)
            : [...prefs.indicators, id],
        }),
      ),
    toggleFavorite: (id) =>
      setPrefs(
        writeChartPrefs({
          favorites: prefs.favorites.includes(id)
            ? prefs.favorites.filter((value) => value !== id)
            : [...prefs.favorites, id],
        }),
      ),
  };

  return [prefs, actions];
}
