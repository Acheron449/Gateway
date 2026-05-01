import { useEffect, useState } from "react";
import { wsManager } from "../lib/wsmanager";
import type { TradingWsPayload } from "../types/market";

export function useLivePrice(ticker: string) {
  const [price, setPrice] = useState<number | null>(null);
  const [change, setChange] = useState<number | null>(null);

  useEffect(() => {
    const sym = ticker?.trim()?.toUpperCase();

    if (!sym) {
      setPrice(null);
      setChange(null);
      return;
    }

    const handler = (data: TradingWsPayload) => {
      const newPrice = Number(data.price);

      // prevent unnecessary re-renders
      setPrice((prev) => (prev !== newPrice ? newPrice : prev));

      if ("change" in data) {
        const newChange = Number((data as any).change);
        setChange((prev) => (prev !== newChange ? newChange : prev));
      }
    };

    wsManager.subscribe(sym, handler);

    return () => {
      wsManager.unsubscribe(sym, handler);
    };
  }, [ticker]);

  return { price, change };
}