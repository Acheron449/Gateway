import { useEffect, useState } from "react";

import { API_BASE } from "../lib/constants";
import type { HistoryCandle } from "../types/market";

export const HISTORY_TFS = ["1h", "1d", "1wk"] as const;
export type HistoryTf = (typeof HISTORY_TFS)[number];

/**
 * Fetches historical market data for a given ticker symbol from the REST API.
 * @param ticker   The stock ticker symbol (e.g., "AAPL").
 * @param tf       Requested timeframe; the backend resamples ("1m" | "5m" | "5h" | "1h" | "1d" | "1wk" …).
 * @param limit    Optional max bar count (range-style chips like 1M/3M/1Y pass a slice size).
 * @param provider Data provider id from GET /history/providers ("yahoo" by default).
 * @returns An object containing the fetched data, loading state, and any error encountered.
 */
export function useHistory(ticker: string, tf: string = "1h", limit = 500, provider: string = "yahoo") {
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
      })
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Failed to load history");
        setData([]);
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
  }, [ticker, tf, limit, provider]);

  return { data, loading, error };
}
