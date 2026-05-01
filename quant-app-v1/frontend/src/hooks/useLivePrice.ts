import { useEffect, useState } from "react";

import { WS_BASE } from "../lib/constants";
import type { TradingWsPayload } from "../types/market";

/** Last trade price from the same stream as `/ws/trading`. */
export function useLivePrice(ticker: string): number | null {
  const [price, setPrice] = useState<number | null>(null);

  useEffect(() => {
    const sym = ticker?.trim()?.toUpperCase();
    if (!sym) {
      setPrice(null);
      return;
    }

    const socket = new WebSocket(`${WS_BASE}/ws/trading`);

    socket.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as TradingWsPayload;
        if (data.symbol?.toUpperCase() === sym) setPrice(Number(data.price));
      } catch {
        /* ignore */
      }
    };

    return () => socket.close();
  }, [ticker]);

  return price;
}
