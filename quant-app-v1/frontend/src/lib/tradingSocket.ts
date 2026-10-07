import { WS_BASE } from "./constants";

/**
 * Shared client for the `/ws/trading` stream.
 *
 * Three things every caller needs and none of them should re-invent:
 *
 * 1. **Token auth** — the endpoint rejects unauthenticated handshakes
 *    (close 4001), so the current session token rides in the query string.
 *    It is re-read on every (re)connect so a refreshed Supabase token is
 *    picked up instead of retrying forever with a stale one.
 * 2. **Subscribe** — the server only broadcasts to `(symbol, tf)` pairs the
 *    client explicitly subscribed to; connecting alone yields silence.
 * 3. **Reconnect** — Vercel closes WebSocket connections when the function
 *    reaches its max duration, so a closed socket is normal traffic, not an
 *    error. Reconnect with capped backoff and resubscribe on open.
 *
 * Returns a disposer that stops reconnecting and closes the socket.
 */
export interface TradingSocketOptions {
  onMessage: (data: Record<string, unknown>) => void;
  /** Sent as `{"action":"subscribe", ...}` on every successful open. */
  subscribe?: { symbol: string; tf?: string };
}

const TOKEN_KEY = "gateway_auth_token";

export function openTradingSocket(options: TradingSocketOptions): () => void {
  let disposed = false;
  let socket: WebSocket | null = null;
  let retryTimer: number | null = null;
  let delay = 1000;

  const connect = () => {
    if (disposed) return;
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return; // signed out — nothing to authenticate with, stop trying
    try {
      socket = new WebSocket(`${WS_BASE}/ws/trading?token=${encodeURIComponent(token)}`);
    } catch {
      retryTimer = window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30_000);
      return;
    }
    const current = socket;
    current.onopen = () => {
      delay = 1000;
      if (options.subscribe) {
        current.send(
          JSON.stringify({
            action: "subscribe",
            symbol: options.subscribe.symbol,
            tf: options.subscribe.tf ?? "1m",
          }),
        );
      }
    };
    current.onmessage = (event: MessageEvent) => {
      try {
        options.onMessage(JSON.parse(event.data as string) as Record<string, unknown>);
      } catch {
        /* ignore malformed frames */
      }
    };
    current.onclose = () => {
      if (disposed) return;
      retryTimer = window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30_000);
    };
    current.onerror = () => current.close();
  };

  connect();

  return () => {
    disposed = true;
    if (retryTimer !== null) window.clearTimeout(retryTimer);
    socket?.close();
  };
}
