import { useEffect, useRef, useState } from "react";

import { API_BASE } from "../../lib/constants";
import type { QuoteRow } from "../../types/market";

const DEFAULT_SYMBOLS = [
  "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
  "SPY", "QQQ", "JPM", "BTC-USD", "ETH-USD",
];

const REFRESH_MS = 45_000;

interface SymbolTickerProps {
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
  contextView: string;
}

/**
 * Horizontally scrollable strip of live quotes (issue #9). Each chip shows
 * ▲/▼ colored green/red with last price and % change. Data comes from the
 * backend's batch /quotes endpoint (yfinance-backed, server-cached).
 */
export function SymbolTicker({ selectedSymbol, onSelect, contextView }: SymbolTickerProps) {
  const [quotes, setQuotes] = useState<QuoteRow[]>([]);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [lastUpdate, setLastUpdate] = useState<number>(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/quotes?symbols=${encodeURIComponent(DEFAULT_SYMBOLS.join(","))}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const payload = (await res.json()) as { quotes?: QuoteRow[] };
        if (cancelled || !mountedRef.current) return;
        setQuotes(Array.isArray(payload.quotes) ? payload.quotes : []);
        setStatus(payload.quotes && payload.quotes.length > 0 ? "ok" : "error");
        setLastUpdate(Date.now());
      } catch {
        if (!cancelled && mountedRef.current) setStatus("error");
      }
    };

    void load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const formatPrice = (value: number) =>
    value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : value.toFixed(2);

  return (
    <div className="symbol-ticker" role="marquee" aria-label="Market ticker">
      {status === "loading" && <span className="ticker-status">Loading quotes…</span>}
      {status === "error" && (
        <span className="ticker-status ticker-error" title="Quote feed unavailable — market closed or feed unreachable">
          Feed unavailable
        </span>
      )}
      {status === "ok" && (
        <div className="ticker-track">
          {quotes.map((q) => {
            const up = q.change >= 0;
            const selected = q.symbol === selectedSymbol;
            return (
              <button
                key={q.symbol}
                className={`ticker-chip ${selected ? "selected" : ""} ${up ? "up" : "down"}`}
                onClick={() => onSelect(q.symbol)}
                title={`${q.symbol} — ${up ? "+" : ""}${q.change.toFixed(2)} today${lastUpdate ? ` · updated ${new Date(lastUpdate).toLocaleTimeString()}` : ""} · click to chart in ${contextView}`}
              >
                <span className="ticker-symbol">{q.symbol}</span>
                <span className="ticker-arrow" aria-hidden="true">{up ? "▲" : "▼"}</span>
                <span className="ticker-price">{formatPrice(q.price)}</span>
                <span className="ticker-change">
                  {up ? "+" : ""}
                  {q.change_pct.toFixed(2)}%
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
