import { useEffect, useState } from "react";

import { openTradingSocket } from "../lib/tradingSocket";
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

    // Authenticated + subscribed + auto-reconnecting (the server rejects
    // anonymous handshakes and only broadcasts to explicit subscriptions).
    const dispose = openTradingSocket({
      subscribe: { symbol: sym, tf: "1m" },
      onMessage: (msg) => {
        const data = msg as unknown as TradingWsPayload;
        if (typeof data.price !== "number") return; // acks/control frames
        if (data.symbol?.toUpperCase() === sym) setPrice(Number(data.price));
      },
    });

    return dispose;
  }, [ticker]);

  return price;
}
