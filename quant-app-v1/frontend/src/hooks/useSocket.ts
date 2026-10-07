import { useEffect, useState } from "react";

import { openTradingSocket } from "../lib/tradingSocket";
import type { HistoryCandle, TradingWsPayload } from "../types/market";

/** Live candle “tick”: server sends last trade price; approximate OHLC to that close. */
function priceToTickCandle(price: number, bucketSec = 60): HistoryCandle {
  const now = Math.floor(Date.now() / 1000);
  const aligned = bucketSec > 1 ? Math.floor(now / bucketSec) * bucketSec : now;
  const p = Number(price);
  return {
    time: aligned,
    open: p,
    high: p,
    low: p,
    close: p,
  };
}

export interface LiveTradingUpdate {
  priceData: HistoryCandle;
  rsi: number;
  pattern_detected: boolean;
  time: number;
  pattern_label?: string;
}

export function useSocket(ticker: string): LiveTradingUpdate | null {
  const [liveUpdate, setLiveUpdate] = useState<LiveTradingUpdate | null>(null);

  useEffect(() => {
    const sym = ticker?.trim()?.toUpperCase();
    if (!sym) {
      setLiveUpdate(null);
      return;
    }

    // Authenticated + subscribed + auto-reconnecting: the server rejects
    // anonymous handshakes, only broadcasts to explicit subscriptions, and
    // Vercel closes sockets at the function max duration.
    const dispose = openTradingSocket({
      subscribe: { symbol: sym, tf: "1m" },
      onMessage: (raw) => {
        const msg = raw as unknown as TradingWsPayload;
        if (typeof msg.price !== "number") return; // acks/control frames
        if (msg.symbol?.toUpperCase() !== sym) return;

        const priceData = priceToTickCandle(msg.price, 60);
        const patternDetected = Boolean(msg.pattern_detected);
        const patternLabel = msg.pattern_label || "";
        const patternTime =
          typeof msg.pattern_time === "number" ? msg.pattern_time : priceData.time;

        setLiveUpdate({
          priceData,
          rsi: typeof msg.rsi === "number" ? msg.rsi : 0,
          pattern_detected: patternDetected,
          time: patternTime,
          pattern_label: patternLabel,
        });
      },
    });

    return dispose;
  }, [ticker]);

  return liveUpdate;
}
