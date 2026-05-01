// /lib/wsManager.ts

import { WS_BASE } from "./constants";
import type { TradingWsPayload } from "../types/market";

type Callback = (data: TradingWsPayload) => void;

class WSManager {
  private socket: WebSocket | null = null;
  private subscribers: Map<string, Set<Callback>> = new Map();

  connect() {
    if (this.socket) return;

    this.socket = new WebSocket(`${WS_BASE}/ws/trading`);

    this.socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as TradingWsPayload;
        const sym = data.symbol?.toUpperCase();

        if (!sym) return;

        const subs = this.subscribers.get(sym);
        subs?.forEach((cb) => cb(data));
      } catch {
        /* ignore */
      }
    };

    this.socket.onclose = () => {
      this.socket = null;
      // optional: auto-reconnect
      setTimeout(() => this.connect(), 2000);
    };
  }

  subscribe(symbol: string, cb: Callback) {
    const sym = symbol.toUpperCase();

    if (!this.subscribers.has(sym)) {
      this.subscribers.set(sym, new Set());
    }

    this.subscribers.get(sym)!.add(cb);

    this.connect(); // ensure connection
  }

  unsubscribe(symbol: string, cb: Callback) {
    const sym = symbol.toUpperCase();

    const subs = this.subscribers.get(sym);
    if (!subs) return;

    subs.delete(cb);

    if (subs.size === 0) {
      this.subscribers.delete(sym);
    }
  }
}

export const wsManager = new WSManager();