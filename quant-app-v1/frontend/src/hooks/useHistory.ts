import { useEffect, useRef, useState } from "react";

import { API_BASE } from "../lib/constants";
import type { HistoryCandle } from "../types/market";

export const HISTORY_TFS = ["1h", "1d", "1wk"] as const;
export type HistoryTf = (typeof HISTORY_TFS)[number];

/**
 * Fetches historical market data for a given ticker symbol from the REST API.
 * @param ticker    The stock ticker symbol (e.g., "AAPL").
 * @param tf        Requested timeframe; the backend resamples ("1m" | "5m" | "5h" | "1h" | "1d" | "1wk" …).
 * @param limit     Optional max bar count (range-style chips like 1M/3M/1Y pass a slice size).
 * @param provider  Data provider id from GET /history/providers ("yahoo" by default).
 * @param refreshMs Optional poll interval — refetches the bars this often so
 *                  the selected provider keeps the chart current (0 = one-shot).
 * @returns An object containing the fetched data, loading state, and any error encountered.
 */
export function useHistory(
  ticker: string,
  tf: string = "1h",
  limit = 500,
  provider: string = "yahoo",
  refreshMs = 0,
) {
  const [data, setData] = useState<HistoryCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const loadedRef = useRef(false);
  const keyRef = useRef<string | null>(null);

  // Background polling: bump a tick to re-run the fetch effect. The spinner
  // only shows on the first load so refreshes don't flash the chart.
  useEffect(() => {
    if (!refreshMs || refreshMs < 1000) return undefined;
    const id = window.setInterval(() => setTick((t) => t + 1), refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs]);

  useEffect(() => {
    const sym = ticker?.trim()?.toUpperCase();
    if (!sym) {
      setData([]);
      setLoading(false);
      setError(null);
      return;
    }

    const ac = new AbortController();
    // Show the spinner on symbol/timeframe changes, but not on silent polls.
    const queryKey = `${sym}|${tf}|${limit}|${provider}`;
    if (queryKey !== keyRef.current) {
      keyRef.current = queryKey;
      loadedRef.current = false;
    }
    if (!loadedRef.current) setLoading(true);
    setError(null);

    fetch(
      `${API_BASE}/history/${encodeURIComponent(sym)}?tf=${encodeURIComponent(tf)}&limit=${encodeURIComponent(limit)}&provider=${encodeURIComponent(provider)}`,
      { signal: ac.signal },
    )
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `${res.status} ${res.statusText}`);
        }
        return res.json() as Promise<HistoryCandle[]>;
      })
      .then((rows) => {
        const formatted: HistoryCandle[] = rows.map((item) => ({
          time: typeof item.time === "number" ? item.time : Math.floor(Number(item.time)),
          open: Number(item.open),
          high: Number(item.high),
          low: Number(item.low),
          close: Number(item.close),
          volume: item.volume !== undefined ? Number(item.volume) : undefined,
        }));
        formatted.sort((a, b) => a.time - b.time);
        setData(formatted);
        loadedRef.current = true;
      })
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Failed to load history");
        setData([]);
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, tf, limit, provider, tick]);

  return { data, loading, error };
}
