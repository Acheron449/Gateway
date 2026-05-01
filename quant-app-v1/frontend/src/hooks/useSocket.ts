import { useEffect, useState } from "react";

import { WS_BASE } from "../lib/constants";
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

    const url = `${WS_BASE}/ws/trading`;
    const socket = new WebSocket(url);

    socket.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as TradingWsPayload;
        if (msg.symbol?.toUpperCase() !== sym) return;

        const priceData = priceToTickCandle(msg.price, 60);
        const pattern = Boolean(msg.pattern_detected);
        const patternTime =
          typeof msg.pattern_time === "number" ? msg.pattern_time : priceData.time;

        setLiveUpdate({
          priceData,
          rsi: typeof msg.rsi === "number" ? msg.rsi : 0,
          pattern_detected: pattern,
          time: patternTime,
          pattern_label: msg.pattern_label,
        });
      } catch {
        /* ignore malformed payloads */
      }
    };

    return () => socket.close();
  }, [ticker]);

  return liveUpdate;
}
