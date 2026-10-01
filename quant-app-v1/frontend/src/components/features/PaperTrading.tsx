import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, WS_BASE } from "../../lib/constants";

interface Position {
  instrument_id: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

interface PaperOrder {
  id: string;
  instrument_id: string;
  side: string;
  type: string;
  qty: number;
  limit_price: number | null;
  stop_price: number | null;
  status: string;
  filled_qty: number;
  avg_fill_price: number | null;
  created_at: string;
}

interface Fill {
  id: string;
  order_id: string;
  instrument_id: string;
  side: string;
  qty: number;
  price: number;
  commission: number;
  timestamp: string;
  liquidity: string | null;
}

interface Portfolio {
  portfolio_id: string;
  cash: number;
  equity: number;
  buying_power: number;
  positions: Position[];
  open_orders: PaperOrder[];
  recent_fills: Fill[];
}

interface OrderRequest {
  instrument: string;
  side: "buy" | "sell";
  order_type: "market" | "limit" | "stop";
  quantity: number;
  limit_price?: number | null;
  stop_price?: number | null;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${API_BASE}/portfolio`, { headers: authHeaders() });
  if (!res.ok) throw new Error((await res.text()) || "Failed to fetch portfolio");
  return res.json();
}

async function submitOrder(order: OrderRequest): Promise<{ order_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/portfolio/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(order),
  });
  if (!res.ok) {
    let detail = `Order failed (${res.status})`;
    try {
      const payload = await res.json();
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return res.json();
}

async function simulateFill(orderId: string): Promise<{ filled: boolean; price?: number }> {
  const res = await fetch(`${API_BASE}/portfolio/orders/${encodeURIComponent(orderId)}/simulate-fill`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Fill simulation failed");
  return res.json();
}

const money = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

/**
 * Paper trading desk: live account summary, order ticket, positions,
 * open orders (with one-click fill simulation), and recent fills.
 * State streams over the authenticated /portfolio/stream WebSocket with a
 * REST polling fallback.
 */
export function PaperTrading({ selectedSymbol }: { selectedSymbol?: string }) {
  const queryClient = useQueryClient();
  const [orderForm, setOrderForm] = useState<OrderRequest>({
    instrument: selectedSymbol ?? "AAPL",
    side: "buy",
    order_type: "market",
    quantity: 10,
    limit_price: null,
    stop_price: null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  const [fillBusyId, setFillBusyId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: portfolio, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: live ? false : 5000,
  });

  // Keep the ticket's symbol in sync when the user changes it elsewhere.
  useEffect(() => {
    if (selectedSymbol) {
      setOrderForm((form) => ({ ...form, instrument: selectedSymbol }));
    }
  }, [selectedSymbol]);

  // Market session badge.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/portfolio/market-status`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setMarketOpen(Boolean(data.is_open));
      } catch {
        /* badge is decoration */
      }
    };
    void load();
    const id = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Authenticated live stream: server pushes portfolio state each second and
  // auto-fills accepted orders while connected.
  useEffect(() => {
    const token = localStorage.getItem("gateway_auth_token");
    if (!token) return undefined;

    let closed = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;

    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(`${WS_BASE}/portfolio/stream?token=${encodeURIComponent(token)}`);
      } catch {
        return;
      }
      wsRef.current = socket;
      socket.onopen = () => setLive(true);
      socket.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string) as { type?: string; data?: Portfolio };
          if (msg.type === "portfolio_update" && msg.data) {
            queryClient.setQueryData(["portfolio"], msg.data);
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setLive(false);
        if (!closed) retryTimer = window.setTimeout(connect, 4000);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      socket?.close();
      wsRef.current = null;
      setLive(false);
    };
  }, [queryClient]);

  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio]);
  const openOrders = useMemo(() => portfolio?.open_orders ?? [], [portfolio]);
  const recentFills = useMemo(() => portfolio?.recent_fills ?? [], [portfolio]);

  const estimatedCost = useMemo(() => {
    const last = recentFills.find((f) => f.instrument_id === orderForm.instrument.toUpperCase())?.price;
    return last ? last * orderForm.quantity : null;
  }, [recentFills, orderForm.instrument, orderForm.quantity]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const result = await submitOrder({
        instrument: orderForm.instrument.trim().toUpperCase(),
        side: orderForm.side,
        order_type: orderForm.order_type,
        quantity: Number(orderForm.quantity),
        limit_price: orderForm.order_type === "limit" ? Number(orderForm.limit_price) : undefined,
        stop_price: orderForm.order_type === "stop" ? Number(orderForm.stop_price) : undefined,
      });
      setNotice(`${result.message} — order ${result.order_id.slice(0, 8)}`);
      void refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSimulateFill = async (orderId: string) => {
    setFillBusyId(orderId);
    setError(null);
    setNotice(null);
    try {
      const result = await simulateFill(orderId);
      setNotice(result.filled ? `Order filled at ${money(result.price)}` : "Order not fillable yet (no quote or market closed)");
      void refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fill failed");
    } finally {
      setFillBusyId(null);
    }
  };

  if (isLoading) {
    return <div className="paper-loading">Loading paper portfolio…</div>;
  }

  if (loadError) {
    return (
      <div className="paper-error" role="alert">
        Paper portfolio unavailable: {loadError instanceof Error ? loadError.message : "unknown error"}
        <button className="btn-secondary" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="paper-trading">
      <div className="paper-summary">
        <div className="paper-metrics">
          <div className="paper-metric">
            <span className="paper-metric-label">Equity</span>
            <span className="paper-metric-value">${money(portfolio?.equity)}</span>
          </div>
          <div className="paper-metric">
            <span className="paper-metric-label">Cash</span>
            <span className="paper-metric-value">${money(portfolio?.cash)}</span>
          </div>
          <div className="paper-metric">
            <span className="paper-metric-label">Buying power</span>
            <span className="paper-metric-value">${money(portfolio?.buying_power)}</span>
          </div>
          <div className="paper-metric">
            <span className="paper-metric-label">Positions</span>
            <span className="paper-metric-value">{positions.length}</span>
          </div>
        </div>
        <div className="paper-status">
          <span className={`paper-live ${live ? "on" : ""}`}>{live ? "Live stream" : "Polling"}</span>
          <span className={`paper-session ${marketOpen ? "open" : "closed"}`}>
            {marketOpen === null ? "Market status…" : marketOpen ? "Market open" : "Market closed"}
          </span>
          <span className="mode-badge paper">Paper</span>
        </div>
      </div>

      {(notice || error) && (
        <div className={error ? "paper-alert error" : "paper-alert"} role="status">
          <span>{error ?? notice}</span>
          <button className="btn-ghost" onClick={() => { setNotice(null); setError(null); }}>
            Dismiss
          </button>
        </div>
      )}

      <div className="paper-grid">
        <section className="paper-card order-ticket">
          <h3>Order ticket</h3>
          <form onSubmit={handleSubmit} className="paper-order-form">
            <div className="paper-form-row">
              <label className="paper-field">
                <span>Symbol</span>
                <input
                  type="text"
                  value={orderForm.instrument}
                  onChange={(e) => setOrderForm({ ...orderForm, instrument: e.target.value.toUpperCase() })}
                  required
                  spellCheck={false}
                />
              </label>
              <label className="paper-field">
                <span>Quantity</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={orderForm.quantity}
                  onChange={(e) => setOrderForm({ ...orderForm, quantity: Number(e.target.value) || 1 })}
                  required
                />
              </label>
            </div>

            <div className="paper-side-toggle" role="group" aria-label="Order side">
              <button
                type="button"
                className={`side-buy ${orderForm.side === "buy" ? "active" : ""}`}
                onClick={() => setOrderForm({ ...orderForm, side: "buy" })}
              >
                Buy
              </button>
              <button
                type="button"
                className={`side-sell ${orderForm.side === "sell" ? "active" : ""}`}
                onClick={() => setOrderForm({ ...orderForm, side: "sell" })}
              >
                Sell
              </button>
            </div>

            <div className="paper-form-row">
              <label className="paper-field">
                <span>Type</span>
                <select
                  value={orderForm.order_type}
                  onChange={(e) => setOrderForm({ ...orderForm, order_type: e.target.value as OrderRequest["order_type"] })}
                >
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                  <option value="stop">Stop</option>
                </select>
              </label>
              {orderForm.order_type === "limit" && (
                <label className="paper-field">
                  <span>Limit price</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={orderForm.limit_price ?? ""}
                    onChange={(e) => setOrderForm({ ...orderForm, limit_price: e.target.value ? Number(e.target.value) : null })}
                    required
                  />
                </label>
              )}
              {orderForm.order_type === "stop" && (
                <label className="paper-field">
                  <span>Stop price</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={orderForm.stop_price ?? ""}
                    onChange={(e) => setOrderForm({ ...orderForm, stop_price: e.target.value ? Number(e.target.value) : null })}
                    required
                  />
                </label>
              )}
            </div>

            <div className="paper-order-foot">
              {estimatedCost !== null && (
                <span className="paper-est">Est. cost ≈ ${money(estimatedCost)}</span>
              )}
              <button
                type="submit"
                className={`btn-primary paper-submit ${orderForm.side}`}
                disabled={submitting || !orderForm.instrument.trim() || orderForm.quantity < 1}
              >
                {submitting ? "Submitting…" : `${orderForm.side === "buy" ? "Buy" : "Sell"} ${orderForm.quantity} ${orderForm.instrument.toUpperCase() || "—"}`}
              </button>
            </div>
          </form>
        </section>

        <section className="paper-card">
          <h3>Positions</h3>
          {positions.length === 0 ? (
            <p className="paper-empty">No open positions — place your first order on the ticket.</p>
          ) : (
            <table className="paper-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Avg cost</th>
                  <th>Market value</th>
                  <th>Unrealized PnL</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.instrument_id}>
                    <td className="paper-symbol">{p.instrument_id}</td>
                    <td>{p.quantity}</td>
                    <td>{money(p.avg_cost)}</td>
                    <td>{money(p.market_value)}</td>
                    <td className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}
                      {money(p.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="paper-card">
          <h3>Open orders</h3>
          {openOrders.length === 0 ? (
            <p className="paper-empty">No working orders.</p>
          ) : (
            <table className="paper-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {openOrders.map((o) => (
                  <tr key={o.id}>
                    <td className="paper-symbol">{o.instrument_id}</td>
                    <td>
                      <span className={`side-badge ${o.side}`}>{o.side === "buy" ? "Buy" : "Sell"}</span>
                    </td>
                    <td>{o.type}</td>
                    <td>{o.qty}</td>
                    <td>{o.limit_price ? money(o.limit_price) : o.stop_price ? money(o.stop_price) : "—"}</td>
                    <td>{o.status}</td>
                    <td>
                      <button
                        className="btn-secondary paper-fill-btn"
                        onClick={() => void handleSimulateFill(o.id)}
                        disabled={fillBusyId === o.id}
                      >
                        {fillBusyId === o.id ? "…" : "Simulate fill"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="paper-card">
          <h3>Recent fills</h3>
          {recentFills.length === 0 ? (
            <p className="paper-empty">No fills yet.</p>
          ) : (
            <table className="paper-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Comm.</th>
                </tr>
              </thead>
              <tbody>
                {recentFills.map((f) => (
                  <tr key={f.id}>
                    <td>{new Date(f.timestamp).toLocaleTimeString()}</td>
                    <td className="paper-symbol">{f.instrument_id}</td>
                    <td>
                      <span className={`side-badge ${f.side}`}>{f.side === "buy" ? "Buy" : "Sell"}</span>
                    </td>
                    <td>{f.qty}</td>
                    <td>{money(f.price)}</td>
                    <td>{money(f.commission)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
