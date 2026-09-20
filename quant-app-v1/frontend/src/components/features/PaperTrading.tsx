import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

interface Position {
  instrument_id: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

interface Order {
  id: string;
  portfolio_id: string;
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
  open_orders: Order[];
  recent_fills: Fill[];
}

interface OrderRequest {
  instrument: string;
  side: "buy" | "sell";
  order_type: "market" | "limit" | "stop";
  quantity: number;
  limit_price?: number;
  stop_price?: number;
}

const API_BASE = "/api/v1";

async function fetchPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${API_BASE}/portfolio`);
  if (!res.ok) throw new Error("Failed to fetch portfolio");
  return res.json();
}

async function submitOrder(order: OrderRequest): Promise<{ order_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/portfolio/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(order),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Order failed");
  }
  return res.json();
}

export function PaperTrading() {
  const queryClient = useQueryClient();
  const [useWebSocket, setUseWebSocket] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const [wsError, setWsError] = useState<string | null>(null);

  const { data: portfolio, isLoading, error, refetch } = useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: useWebSocket ? false : 2000,
  });

  const orderMutation = useMutation({
    mutationFn: submitOrder,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (err: Error) => {
      alert(`Order failed: ${err.message}`);
    },
  });

  const [orderForm, setOrderForm] = useState<OrderRequest>({
    instrument: "",
    side: "buy",
    order_type: "market",
    quantity: 1,
    limit_price: undefined,
    stop_price: undefined,
  });

  useEffect(() => {
    if (!useWebSocket) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}${API_BASE}/portfolio/stream`);

    ws.onopen = () => {
      setWsError(null);
      console.log("Portfolio WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "portfolio_update") {
          queryClient.setQueryData(["portfolio"], msg.data);
        }
      } catch (e) {
        console.error("WS parse error", e);
      }
    };

    ws.onerror = () => {
      setWsError("WebSocket connection error");
    };

    ws.onclose = () => {
      console.log("Portfolio WebSocket disconnected");
      setTimeout(() => {
        if (useWebSocket && wsRef.current === ws) {
          setUseWebSocket(true);
        }
      }, 2000);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [useWebSocket, queryClient]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    orderMutation.mutate(orderForm);
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
  };

  const formatNumber = (value: number) => {
    return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  };

  const getPnlColor = (value: number) => (value >= 0 ? "text-green-600" : "text-red-600");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-red-600">
        Error loading portfolio: {(error as Error).message}
        <button onClick={() => refetch()} className="ml-2 px-3 py-1 bg-blue-500 text-white rounded">
          Retry
        </button>
      </div>
    );
  }

  const p = portfolio!;

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Paper Trading Portfolio</h1>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={useWebSocket}
            onChange={(e) => setUseWebSocket(e.target.checked)}
            className="w-4 h-4"
          />
          Real-time updates
        </label>
      </div>

      {wsError && (
        <div className="text-yellow-600 text-sm">⚠ {wsError} - falling back to polling</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg shadow p-4 border-l-4 border-blue-500">
          <div className="text-sm text-gray-500">Cash</div>
          <div className="text-2xl font-bold">{formatCurrency(p.cash)}</div>
        </div>
        <div className="bg-white rounded-lg shadow p-4 border-l-4 border-green-500">
          <div className="text-sm text-gray-500">Equity</div>
          <div className="text-2xl font-bold">{formatCurrency(p.equity)}</div>
        </div>
        <div className="bg-white rounded-lg shadow p-4 border-l-4 border-purple-500">
          <div className="text-sm text-gray-500">Buying Power</div>
          <div className="text-2xl font-bold">{formatCurrency(p.buying_power)}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-white rounded-lg shadow">
          <div className="px-4 py-3 border-b flex items-center justify-between">
            <h2 className="text-lg font-semibold">Positions</h2>
            <span className="text-sm text-gray-500">{p.positions.length} positions</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Avg Cost</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Market Value</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Unrealized P&L</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Realized P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {p.positions.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-gray-500">No positions</td>
                  </tr>
                ) : (
                  p.positions.map((pos) => (
                    <tr key={pos.instrument_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-sm">{pos.instrument_id}</td>
                      <td className="px-4 py-3 text-sm">{formatNumber(pos.quantity)}</td>
                      <td className="px-4 py-3 text-sm">{formatCurrency(pos.avg_cost)}</td>
                      <td className="px-4 py-3 text-sm">{formatCurrency(pos.market_value)}</td>
                      <td className={`px-4 py-3 text-sm font-medium ${getPnlColor(pos.unrealized_pnl)}`}>
                        {formatCurrency(pos.unrealized_pnl)}
                      </td>
                      <td className={`px-4 py-3 text-sm font-medium ${getPnlColor(pos.realized_pnl)}`}>
                        {formatCurrency(pos.realized_pnl)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="bg-white rounded-lg shadow">
          <div className="px-4 py-3 border-b flex items-center justify-between">
            <h2 className="text-lg font-semibold">Open Orders</h2>
            <span className="text-sm text-gray-500">{p.open_orders.length} orders</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Limit</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Filled</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {p.open_orders.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-500">No open orders</td>
                  </tr>
                ) : (
                  p.open_orders.map((order) => (
                    <tr key={order.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-xs font-mono">{order.id.slice(0, 8)}...</td>
                      <td className="px-4 py-2 text-sm font-mono">{order.instrument_id}</td>
                      <td className="px-4 py-2 text-sm">
                        <span className={`px-2 py-0.5 rounded text-xs ${order.side === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                          {order.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm">{order.type.toUpperCase()}</td>
                      <td className="px-4 py-2 text-sm">{formatNumber(order.qty)}</td>
                      <td className="px-4 py-2 text-sm">{order.limit_price ? formatCurrency(order.limit_price) : "-"}</td>
                      <td className="px-4 py-2 text-sm">
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          order.status === "filled" ? "bg-green-100 text-green-700" :
                          order.status === "cancelled" ? "bg-gray-100 text-gray-700" :
                          order.status === "rejected" ? "bg-red-100 text-red-700" :
                          "bg-yellow-100 text-yellow-700"
                        }`}>
                          {order.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm">{formatNumber(order.filled_qty)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="bg-white rounded-lg shadow">
        <div className="px-4 py-3 border-b">
          <h2 className="text-lg font-semibold">Place Order</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Symbol</label>
              <input
                type="text"
                value={orderForm.instrument}
                onChange={(e) => setOrderForm({ ...orderForm, instrument: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Side</label>
              <select
                value={orderForm.side}
                onChange={(e) => setOrderForm({ ...orderForm, side: e.target.value as "buy" | "sell" })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Order Type</label>
              <select
                value={orderForm.order_type}
                onChange={(e) => setOrderForm({ ...orderForm, order_type: e.target.value as "market" | "limit" | "stop" })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="market">Market</option>
                <option value="limit">Limit</option>
                <option value="stop">Stop</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Quantity</label>
              <input
                type="number"
                min="1"
                step="1"
                value={orderForm.quantity}
                onChange={(e) => setOrderForm({ ...orderForm, quantity: parseFloat(e.target.value) || 1 })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>
            {(orderForm.order_type === "limit" || orderForm.order_type === "stop") && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {orderForm.order_type === "limit" ? "Limit Price" : "Stop Price"}
                </label>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={orderForm.limit_price ?? orderForm.stop_price ?? ""}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    if (orderForm.order_type === "limit") {
                      setOrderForm({ ...orderForm, limit_price: val });
                    } else {
                      setOrderForm({ ...orderForm, stop_price: val });
                    }
                  }}
                  placeholder="Price"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={orderMutation.isPending}
            className="w-full md:w-auto px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {orderMutation.isPending ? "Submitting..." : "Submit Order"}
          </button>
          {orderMutation.isError && (
            <div className="text-red-600 text-sm">
              {(orderMutation.error as Error).message}
            </div>
          )}
        </form>
      </section>

      <section className="bg-white rounded-lg shadow">
        <div className="px-4 py-3 border-b">
          <h2 className="text-lg font-semibold">Recent Fills</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Price</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Commission</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Liquidity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {p.recent_fills.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">No recent fills</td>
                </tr>
              ) : (
                p.recent_fills.slice(0, 20).map((fill) => (
                  <tr key={fill.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm">
                      {new Date(fill.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2 text-sm font-mono">{fill.instrument_id}</td>
                    <td className="px-4 py-2 text-sm">
                      <span className={`px-2 py-0.5 rounded text-xs ${fill.side === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                        {fill.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-sm">{formatNumber(fill.qty)}</td>
                    <td className="px-4 py-2 text-sm">{formatCurrency(fill.price)}</td>
                    <td className="px-4 py-2 text-sm">{formatCurrency(fill.commission)}</td>
                    <td className="px-4 py-2 text-sm text-gray-500">{fill.liquidity || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default PaperTrading;