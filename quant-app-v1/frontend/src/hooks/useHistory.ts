import { useEffect, useState } from "react";

import { API_BASE } from "../lib/constants";
import type { HistoryCandle } from "../types/market";

export const HISTORY_TFS = ["1h", "1d", "1wk"] as const;
export type HistoryTf = (typeof HISTORY_TFS)[number];

/**
 * Fetches historical market data for a given ticker symbol from the REST API.
 * @param ticker The stock ticker symbol (e.g., "AAPL").
 * @param tf     Requested timeframe ("1h" | "1d" | "1wk"); the backend resamples.
 * @returns An object containing the fetched data, loading state, and any error encountered.
 */
export function useHistory(ticker: string, tf: HistoryTf = "1h") {
  const [data, setData] = useState<HistoryCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sym = ticker?.trim()?.toUpperCase();
    if (!sym) {
      setData([]);
      setLoading(false);
      setError(null);
      return;
    }

    const ac = new AbortController();
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/history/${encodeURIComponent(sym)}?tf=${encodeURIComponent(tf)}`, { signal: ac.signal })
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
      })
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Failed to load history");
        setData([]);
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
  }, [ticker, tf]);

  return { data, loading, error };
}
