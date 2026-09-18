import { useEffect, useState } from "react";

import { API_BASE } from "../lib/constants";
import type { HistoryCandle } from "../types/market";

/**
 * Fetches historical market data for a given ticker symbol from the REST API.
 * @param ticker The stock ticker symbol (e.g., "AAPL").
 * @returns An object containing the fetched data, loading state, and any error encountered.
 */
export function useHistory(ticker: string) {
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

    fetch(`${API_BASE}/history/${encodeURIComponent(sym)}`, { signal: ac.signal })
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
  }, [ticker]);

  return { data, loading, error };
}
