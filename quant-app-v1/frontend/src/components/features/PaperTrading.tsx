import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, WS_BASE } from "../../lib/constants";
import { useHistory } from "../../hooks/useHistory";
import { useSocket } from "../../hooks/useSocket";
import { useChartPrefs } from "../../lib/chartPrefs";
import { useRefreshMs } from "../../lib/refresh";
import { MainChart } from "../charts/MainChart";
import { IndicatorsButton } from "../charts/IndicatorPanel";
import { ProviderSelect } from "../charts/ProviderSelect";
import { ResizeHandle } from "../layout/ResizeHandle";
import { RightInspector } from "../layout/RightInspector";

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

interface QuoteRow {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
}

interface DeskStats {
  change5m: number | null;
  change1h: number | null;
  change1d: number | null;
  sellRate: number | null;
  ranges: { label: string; low: number; high: number; marker: number | null }[];
}

interface NewsItem {
  id: string;
  headline: string;
  url?: string;
  source?: string;
  published_at?: string;
}

interface AnalysisData {
  ticker?: string;
  direction?: string;
  overall_confidence?: number;
  rsi?: number;
}

/** Icon + friendly name per instrument (fallback: ticker itself). */
const INSTRUMENT_META: Record<string, { name: string; icon: string; tint: string }> = {
  "GC=F": { name: "Gold", icon: "🥇", tint: "#eab308" },
  "SI=F": { name: "Silver", icon: "🥈", tint: "#94a3b8" },
  "EURUSD=X": { name: "EUR/USD", icon: "🇪🇺", tint: "#2563eb" },
  "AUDUSD=X": { name: "AUD/USD", icon: "🇦🇺", tint: "#16a34a" },
  "USDJPY=X": { name: "USD/JPY", icon: "🇯🇵", tint: "#dc2626" },
  "GBPUSD=X": { name: "GBP/USD", icon: "🇬🇧", tint: "#7c3aed" },
  "^AXJO": { name: "ASX 200", icon: "🇦🇺", tint: "#0ea5e9" },
  "BTC-USD": { name: "Bitcoin", icon: "₿", tint: "#f7931a" },
  "ETH-USD": { name: "Ethereum", icon: "Ξ", tint: "#627eea" },
  "SOL-USD": { name: "Solana", icon: "◎", tint: "#14b8a6" },
  "XRP-USD": { name: "XRP", icon: "✕", tint: "#64748b" },
  AAPL: { name: "Apple", icon: "", tint: "#a3a3a3" },
  MSFT: { name: "Microsoft", icon: "🪟", tint: "#3b82f6" },
  NVDA: { name: "Nvidia", icon: "🅷", tint: "#76b900" },
  TSLA: { name: "Tesla", icon: "⚡", tint: "#ef4444" },
  AMZN: { name: "Amazon", icon: "📦", tint: "#f59e0b" },
  GOOGL: { name: "Alphabet", icon: "G", tint: "#ea4335" },
  META: { name: "Meta", icon: "∞", tint: "#06b6d4" },
  AMD: { name: "AMD", icon: "▲", tint: "#dc2626" },
  SPY: { name: "S&P 500", icon: "🇺🇸", tint: "#22c55e" },
  QQQ: { name: "Nasdaq 100", icon: "📊", tint: "#0ea5e9" },
  JPM: { name: "JPMorgan", icon: "🏦", tint: "#1d4ed8" },
};

const POPULAR_SYMBOLS = [
  "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
  "SPY", "QQQ", "JPM", "BTC-USD", "ETH-USD", "GC=F", "EURUSD=X", "USDJPY=X",
];

interface WatchGroup {
  id: string;
  label: string;
  section: "popular" | "mine";
  symbols: string[];
}

const WATCHLIST_GROUPS: WatchGroup[] = [
  { id: "all", label: "All Popular", section: "popular", symbols: POPULAR_SYMBOLS },
  {
    id: "spotlight",
    label: "Spotlight",
    section: "popular",
    symbols: ["NVDA", "TSLA", "BTC-USD", "GC=F", "SPY", "MSFT", "ETH-USD"],
  },
  {
    id: "options",
    label: "Popular Options",
    section: "popular",
    symbols: ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "MSFT", "AMD", "AMZN"],
  },
  { id: "movers", label: "Risers & Fallers", section: "popular", symbols: POPULAR_SYMBOLS },
  {
    id: "tech",
    label: "Tech",
    section: "mine",
    symbols: ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMD"],
  },
  { id: "fx", label: "FX", section: "mine", symbols: ["EURUSD=X", "AUDUSD=X", "USDJPY=X", "GBPUSD=X"] },
  { id: "crypto", label: "Crypto", section: "mine", symbols: ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"] },
];

/** Chart chips → backend tf (+ optional bar limit for range-style chips). */
const TF_CHIPS: { label: string; tf: string; limit?: number }[] = [
  { label: "5m", tf: "5m" },
  { label: "1H", tf: "1h" },
  { label: "5H", tf: "5h" },
  { label: "1D", tf: "1d" },
  { label: "1W", tf: "1wk" },
  { label: "1M", tf: "1d", limit: 22 },
  { label: "3M", tf: "1d", limit: 66 },
  { label: "1Y", tf: "1d", limit: 252 },
  { label: "Max", tf: "1d", limit: 2000 },
];

type DeskTicketTab = "overview" | "trade" | "info" | "insights";

const TICKET_TABS: { id: DeskTicketTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "trade", label: "Trade" },
  { id: "info", label: "Info" },
  { id: "insights", label: "+Insights" },
];

type DeskSection = "trade" | "positions" | "orders" | "closed" | "insights" | "funds";

/** Restorable column widths for the desk grid (null → responsive CSS default). */
const DESK_WIDTH_KEYS = {
  rail: "gateway_ui_desk_rail_w",
  watchlist: "gateway_ui_desk_watchlist_w",
  ticket: "gateway_ui_desk_ticket_w",
} as const;

const DESK_DEFAULTS = { rail: 76, watchlist: 224, ticket: 340 };
const DESK_LIMITS = {
  rail: { min: 56, max: 160 },
  watchlist: { min: 150, max: 420 },
  ticket: { min: 260, max: 560 },
};

/** Quote-list height (the panel above the chart) — dragged vertically. */
const DESK_QUOTES_H_KEY = "gateway_ui_desk_quotes_h";
const QUOTES_H_MIN = 160;
const quotesHMax = () => Math.max(QUOTES_H_MIN + 80, Math.floor(window.innerHeight * 0.7));
const quotesHDefault = () => Math.floor(window.innerHeight * 0.4);

function readDeskWidth(key: string, min: number, max: number): number | null {
  try {
    const raw = localStorage.getItem(key);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) && value >= min && value <= max ? value : null;
  } catch {
    return null;
  }
}

const DEFAULT_GROUP: WatchGroup = WATCHLIST_GROUPS[0] ?? {
  id: "all",
  label: "All Popular",
  section: "popular",
  symbols: [],
};
const DEFAULT_TF = TF_CHIPS.find((c) => c.label === "1D") ?? { label: "1D", tf: "1d" };

const RAIL_ITEMS: { id: DeskSection; label: string; icon: string }[] = [
  { id: "trade", label: "Trade", icon: "📈" },
  { id: "positions", label: "Open Positions", icon: " ↔" },
  { id: "orders", label: "Orders", icon: "🏷️" },
  { id: "closed", label: "Closed Positions", icon: "🕘" },
  { id: "insights", label: "+Insights", icon: "✨" },
  { id: "funds", label: "Funds", icon: "🏦" },
];

/** Price → display string with sensible precision (FX keeps 5 decimals). */
function fmtPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) < 2) return value.toFixed(5);
  if (Math.abs(value) < 100) return value.toFixed(3);
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "" : ""}${value.toFixed(2)}%`;
}

const money = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function meta(symbol: string): { name: string; icon: string; tint: string } {
  return INSTRUMENT_META[symbol] ?? { name: symbol, icon: symbol.slice(0, 1), tint: "#64748b" };
}

/** Indicative two-way price from last (matches backend half-spread default). */
function twoWay(price: number): { sell: number; buy: number } {
  const half = price * 0.0005;
  return { sell: price - half, buy: price + half };
}

async function fetchPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${API_BASE}/portfolio`, { headers: authHeaders() });
  if (!res.ok) throw new Error((await res.text()) || "Failed to fetch portfolio");
  return res.json();
}

// --- Live (broker) desk helpers -------------------------------------------

async function readLiveError(res: Response): Promise<string> {
  try {
    const payload = await res.json();
    if (typeof payload?.detail === "string") return payload.detail;
  } catch {
    /* fall through */
  }
  return `Live account unavailable (${res.status})`;
}

interface LiveAccount {
  account_number?: string;
  status?: string;
  cash?: number;
  equity?: number;
  buying_power?: number;
}

interface LivePositionRow {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
}

interface LiveOrderRow {
  id: string;
  symbol: string;
  side: string;
  order_type: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  limit_price: number | null;
  stop_price: number | null;
  status: string;
  created_at: string;
}

interface LiveActivityRow {
  id: string;
  symbol?: string;
  side?: string;
  qty?: string | number;
  price?: string | number;
  transaction_time?: string;
  type?: string;
}

const LIVE_TERMINAL_STATUSES = new Set(["filled", "canceled", "expired", "rejected", "replaced", "done_for_day"]);

/** Normalize the broker account/positions/orders into the desk's Portfolio shape. */
async function fetchLivePortfolio(): Promise<Portfolio> {
  const [acctRes, posRes, ordRes, actRes] = await Promise.all([
    fetch(`${API_BASE}/live/account`),
    fetch(`${API_BASE}/live/positions`),
    fetch(`${API_BASE}/live/orders?status=open&limit=100`),
    fetch(`${API_BASE}/live/activities?activity_type=FILL&page_size=25`),
  ]);
  if (!acctRes.ok) throw new Error(await readLiveError(acctRes));

  const account = (await acctRes.json()) as LiveAccount;
  const positions = posRes.ok ? ((await posRes.json()) as LivePositionRow[]) : [];
  const orders = ordRes.ok ? ((await ordRes.json()) as LiveOrderRow[]) : [];
  const activities = actRes.ok ? ((await actRes.json()) as LiveActivityRow[]) : [];

  return {
    portfolio_id: `live:${account.account_number ?? "account"}`,
    cash: account.cash ?? 0,
    equity: account.equity ?? 0,
    buying_power: account.buying_power ?? 0,
    positions: positions.map((p) => ({
      instrument_id: p.symbol,
      quantity: Number(p.qty),
      avg_cost: Number(p.avg_entry_price),
      market_value: Number(p.market_value),
      unrealized_pnl: Number(p.unrealized_pl),
      realized_pnl: 0,
    })),
    open_orders: orders
      .filter((o) => !LIVE_TERMINAL_STATUSES.has(o.status))
      .map((o) => ({
        id: o.id,
        instrument_id: o.symbol,
        side: o.side,
        type: o.order_type,
        qty: Number(o.qty),
        limit_price: o.limit_price,
        stop_price: o.stop_price,
        status: o.status,
        filled_qty: Number(o.filled_qty),
        avg_fill_price: o.filled_avg_price,
        created_at: o.created_at,
      })),
    recent_fills: activities
      .filter((a) => a.symbol)
      .map((a) => ({
        id: a.id,
        order_id: a.id,
        instrument_id: a.symbol ?? "",
        side: String(a.side ?? "buy").toLowerCase(),
        qty: Number(a.qty ?? 0),
        price: Number(a.price ?? 0),
        commission: 0,
        timestamp: a.transaction_time ?? new Date().toISOString(),
        liquidity: null,
      })),
  };
}

/** Place a real order through the broker (Live Trading section). */
async function submitLiveOrder(
  order: OrderRequest,
): Promise<{ order_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/live/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: order.instrument,
      qty: order.quantity,
      side: order.side,
      order_type: order.order_type,
      time_in_force: "day",
      limit_price: order.limit_price ?? undefined,
      stop_price: order.stop_price ?? undefined,
    }),
  });
  if (!res.ok) throw new Error(await readLiveError(res));
  const payload = (await res.json()) as { id: string; status: string };
  return {
    order_id: payload.id,
    status: payload.status,
    message: `Live order ${payload.status}`,
  };
}

async function cancelLiveOrder(orderId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/live/orders/${encodeURIComponent(orderId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readLiveError(res));
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

/**
 * Broker-style paper trading desk: left section rail, watchlist, quote list,
 * candle chart, and a right-hand trade ticket with live statistics.
 */
export function PaperTrading({
  selectedSymbol,
  mode = "paper",
}: {
  selectedSymbol?: string;
  /** "paper" = simulated desk (default); "live" = real broker account (Alpaca). */
  mode?: "paper" | "live";
}) {
  const queryClient = useQueryClient();
  const isLive = mode === "live";
  // User-selected poll rate (Settings → Data refresh): quotes, statistics and
  // chart candles all refetch this often so the selected provider stays fresh.
  const refreshMs = useRefreshMs();

  const [section, setSection] = useState<DeskSection>("trade");
  const [groupId, setGroupId] = useState("all");
  const [symbol, setSymbol] = useState((selectedSymbol ?? "AAPL").toUpperCase());
  const [ticketTab, setTicketTab] = useState<DeskTicketTab>("overview");
  const [tfIndex, setTfIndex] = useState(3); // 1D default
  // Bumped by the desk "Now" button → MainChart recenters on the latest candle.
  const [nowSignal, setNowSignal] = useState(0);
  const [sortKey, setSortKey] = useState<"name" | "change">("name");

  const [orderForm, setOrderForm] = useState({
    side: "buy" as "buy" | "sell",
    order_type: "market" as "market" | "limit" | "stop",
    quantity: 10,
    limit_price: null as number | null,
    stop_price: null as number | null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  const [fillBusyId, setFillBusyId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Draggable column widths (drag a section's edge; double-click resets).
  const [railW, setRailW] = useState<number | null>(() =>
    readDeskWidth(DESK_WIDTH_KEYS.rail, DESK_LIMITS.rail.min, DESK_LIMITS.rail.max),
  );
  const [watchlistW, setWatchlistW] = useState<number | null>(() =>
    readDeskWidth(DESK_WIDTH_KEYS.watchlist, DESK_LIMITS.watchlist.min, DESK_LIMITS.watchlist.max),
  );
  const [ticketW, setTicketW] = useState<number | null>(() =>
    readDeskWidth(DESK_WIDTH_KEYS.ticket, DESK_LIMITS.ticket.min, DESK_LIMITS.ticket.max),
  );
  // Quote-list height: null → responsive CSS default (40vh).
  const [quotesH, setQuotesH] = useState<number | null>(() => {
    const stored = readDeskWidth(DESK_QUOTES_H_KEY, QUOTES_H_MIN, 4000);
    return stored === null ? null : Math.min(stored, quotesHMax());
  });

  const deskRef = useRef<HTMLDivElement | null>(null);
  const railRef = useRef<HTMLElement | null>(null);
  const watchlistRef = useRef<HTMLElement | null>(null);
  const ticketRef = useRef<HTMLElement | null>(null);
  const quotesRef = useRef<HTMLElement | null>(null);

  const deskStyle = {
    "--desk-rail-w": railW !== null ? `${railW}px` : undefined,
    "--desk-watchlist-w": watchlistW !== null ? `${watchlistW}px` : undefined,
    "--desk-ticket-w": ticketW !== null ? `${ticketW}px` : undefined,
  } as React.CSSProperties;

  const MIN_CENTER = 360;

  /** Apply the clamp, store the width, and persist it (drag or double-click). */
  const setDeskWidth = (
    kind: keyof typeof DESK_LIMITS,
    value: number,
    setter: (w: number) => void,
  ) => {
    const clamped = clampDeskWidth(kind, value);
    setter(clamped);
    try {
      localStorage.setItem(DESK_WIDTH_KEYS[kind], String(clamped));
    } catch {
      /* private mode — ignore */
    }
  };

  /** Quote-list height: viewport-relative bounds, persisted. */
  const applyQuotesHeight = (value: number) => {
    const clamped = Math.min(quotesHMax(), Math.max(QUOTES_H_MIN, value));
    setQuotesH(clamped);
    try {
      localStorage.setItem(DESK_QUOTES_H_KEY, String(clamped));
    } catch {
      /* private mode — ignore */
    }
  };

  // Re-clamp the quote list when the window resizes (bounds are vh-based).
  useEffect(() => {
    const onResize = () =>
      setQuotesH((h) => (h === null ? h : Math.min(quotesHMax(), Math.max(QUOTES_H_MIN, h))));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  /**
   * Clamp a dragged column so the fluid center keeps at least MIN_CENTER px.
   * The other columns are measured live (hidden ones count as 0).
   */
  const clampDeskWidth = (kind: keyof typeof DESK_LIMITS, next: number): number => {
    const { min, max } = DESK_LIMITS[kind];
    let value = Math.min(max, Math.max(min, next));
    const desk = deskRef.current;
    if (desk) {
      const gap = parseFloat(getComputedStyle(desk).columnGap) || 14;
      const refs = { rail: railRef, watchlist: watchlistRef, ticket: ticketRef };
      let others = 0;
      let items = 2; // center + the dragged section
      for (const key of ["rail", "watchlist", "ticket"] as const) {
        if (key === kind) continue;
        const rect = refs[key].current?.getBoundingClientRect();
        if (rect && rect.width > 0) {
          others += rect.width;
          items += 1;
        }
      }
      const room = desk.clientWidth - others - gap * (items - 1) - MIN_CENTER;
      value = Math.max(min, Math.min(value, room));
    }
    return value;
  };

  // Follow the global symbol picker (top bar / command palette).
  useEffect(() => {
    if (selectedSymbol) setSymbol(selectedSymbol.toUpperCase());
  }, [selectedSymbol]);

  const group = WATCHLIST_GROUPS.find((g) => g.id === groupId) ?? DEFAULT_GROUP;
  const tf = TF_CHIPS.find((_, i) => i === tfIndex) ?? DEFAULT_TF;

  const { data: portfolio, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["portfolio", mode],
    queryFn: isLive ? fetchLivePortfolio : fetchPortfolio,
    // Live: poll at the user's refresh rate. Paper: the authenticated
    // WebSocket streams updates (and auto-fills) while connected.
    refetchInterval: isLive ? refreshMs : live ? false : 5000,
  });

  // Batch quotes for the active watchlist (server caches per symbol).
  const { data: quotes = [] } = useQuery({
    queryKey: ["desk-quotes", group.id],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE}/quotes?symbols=${encodeURIComponent(group.symbols.join(","))}`,
      );
      if (!res.ok) throw new Error(`${res.status}`);
      const payload = (await res.json()) as { quotes?: QuoteRow[] };
      return payload.quotes ?? [];
    },
    refetchInterval: refreshMs,
    staleTime: Math.floor(refreshMs / 2),
  });

  // Intraday bars power the Live Statistics block (5m/1h changes + ranges).
  const { data: statBars = [] } = useQuery({
    queryKey: ["desk-stat-bars", symbol],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/history/${encodeURIComponent(symbol)}?tf=5m&limit=300`);
      if (!res.ok) throw new Error(`${res.status}`);
      return (await res.json()) as { time: number; open: number; high: number; low: number; close: number }[];
    },
    refetchInterval: refreshMs,
    staleTime: Math.floor(refreshMs / 2),
  });

  const { data: newsItems = [] } = useQuery({
    queryKey: ["desk-news", symbol],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/news?symbol=${encodeURIComponent(symbol)}&limit=3`);
      if (!res.ok) throw new Error(`${res.status}`);
      const payload = (await res.json()) as { items?: Record<string, unknown>[] };
      return (payload.items ?? []).map((item): NewsItem => ({
        id: String(item.id ?? ""),
        headline: String(item.headline ?? ""),
        url: typeof item.url === "string" ? item.url : undefined,
        source: typeof item.source === "string" ? item.source : undefined,
        published_at: typeof item.published_at === "string" ? item.published_at : undefined,
      }));
    },
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  // Analysis is only needed for the Info/+Insights tabs.
  const { data: analysis } = useQuery({
    queryKey: ["desk-analysis", symbol],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/analysis/${encodeURIComponent(symbol)}`);
      if (!res.ok) throw new Error(`${res.status}`);
      return (await res.json()) as AnalysisData;
    },
    enabled: ticketTab !== "trade",
    staleTime: 300_000,
    retry: 1,
  });

  const [{ provider: chartProvider, indicators: chartIndicators }] = useChartPrefs();
  const { data: chartBars = [], loading: chartLoading } = useHistory(
    symbol,
    tf.tf,
    tf.limit ?? 500,
    chartProvider,
    refreshMs,
  );
  const liveUpdate = useSocket(symbol);

  const quote = quotes.find((q) => q.symbol === symbol) ?? null;
  const fallbackPrice = statBars.length ? (statBars[statBars.length - 1]?.close ?? null) : null;
  const lastPrice = quote?.price ?? fallbackPrice;
  const two = lastPrice !== null ? twoWay(lastPrice) : null;
  const changePct = quote?.change_pct ?? null;

  const stats: DeskStats = useMemo(() => {
    const n = statBars.length;
    const last = n ? statBars[n - 1] : null;
    const prev = n > 1 ? statBars[n - 2] : null;
    const hourAgo = n > 12 ? statBars[n - 13] : null;
    const pct = (a: number, b: number) => (b ? ((a - b) / b) * 100 : null);

    const sliceRange = (bars: typeof statBars) => {
      if (!bars.length) return null;
      let low = Infinity;
      let high = -Infinity;
      for (const b of bars) {
        if (b.low < low) low = b.low;
        if (b.high > high) high = b.high;
      }
      return { low, high };
    };

    const range5 = last ? sliceRange([last]) : null;
    const range1h = sliceRange(n >= 12 ? statBars.slice(n - 12) : statBars);
    const range1d = sliceRange(statBars);
    const sell = lastPrice !== null ? twoWay(lastPrice).sell : null;
    const marker = (r: { low: number; high: number } | null) => {
      if (!r || sell === null || r.high <= r.low) return null;
      return Math.min(1, Math.max(0, (sell - r.low) / (r.high - r.low)));
    };

    return {
      change5m: last && prev ? pct(last.close, prev.close) : null,
      change1h: last && hourAgo ? pct(last.close, hourAgo.close) : null,
      change1d: changePct,
      sellRate: sell,
      ranges: [
        { label: "5 Minutes", low: range5?.low ?? 0, high: range5?.high ?? 0, marker: marker(range5) },
        { label: "1 Hour", low: range1h?.low ?? 0, high: range1h?.high ?? 0, marker: marker(range1h) },
        { label: "1 Day", low: range1d?.low ?? 0, high: range1d?.high ?? 0, marker: marker(range1d) },
      ],
    };
  }, [statBars, changePct, lastPrice]);

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

  // Authenticated live stream (paper desk only): server pushes portfolio
  // state each second and auto-fills accepted orders while connected.
  useEffect(() => {
    if (isLive) return undefined;
    if (!localStorage.getItem("gateway_auth_token")) return undefined;

    let closed = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;

    const connect = () => {
      if (closed) return;
      // Read the token per attempt (not once per effect): after a Supabase
      // token refresh the stored value changes, and a retry loop pinned to a
      // stale token would be rejected forever.
      const token = localStorage.getItem("gateway_auth_token");
      if (!token) return;
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
            queryClient.setQueryData(["portfolio", "paper"], msg.data);
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
  }, [queryClient, isLive]);

  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio]);
  const openOrders = useMemo(() => portfolio?.open_orders ?? [], [portfolio]);
  const recentFills = useMemo(() => portfolio?.recent_fills ?? [], [portfolio]);

  // Open position for the instrument currently shown in the trade ticket.
  const activePosition = useMemo(
    () => positions.find((p) => p.instrument_id === symbol) ?? null,
    [positions, symbol],
  );

  const rows = useMemo(() => {
    const mapped = group.symbols.map((sym) => {
      const q = quotes.find((row) => row.symbol === sym);
      const price = q?.price ?? null;
      return {
        symbol: sym,
        meta: meta(sym),
        price,
        changePct: q?.change_pct ?? null,
        two: price !== null ? twoWay(price) : null,
      };
    });
    const sorted = [...mapped];
    if (group.id === "movers") {
      sorted.sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0));
    } else if (sortKey === "change") {
      sorted.sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0));
    } else {
      sorted.sort((a, b) => a.meta.name.localeCompare(b.meta.name));
    }
    return sorted;
  }, [group, quotes, sortKey]);

  const pickSymbol = (sym: string) => {
    setSymbol(sym.toUpperCase());
    window.dispatchEvent(new CustomEvent("symbol-select", { detail: sym.toUpperCase() }));
  };

  const quoteTrade = (sym: string, side: "buy" | "sell") => {
    pickSymbol(sym);
    setOrderForm((form) => ({ ...form, side }));
    setTicketTab("trade");
  };

  const estimatedCost = useMemo(() => {
    if (lastPrice === null) return null;
    const px = orderForm.side === "buy" ? (two?.buy ?? lastPrice) : (two?.sell ?? lastPrice);
    return px * orderForm.quantity;
  }, [lastPrice, two, orderForm.side, orderForm.quantity]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const request: OrderRequest = {
        instrument: symbol.trim().toUpperCase(),
        side: orderForm.side,
        order_type: orderForm.order_type,
        quantity: Number(orderForm.quantity),
        limit_price: orderForm.order_type === "limit" ? Number(orderForm.limit_price) : undefined,
        stop_price: orderForm.order_type === "stop" ? Number(orderForm.stop_price) : undefined,
      };
      const result = isLive ? await submitLiveOrder(request) : await submitOrder(request);

      // Paper desk: market orders (and marketable limits/stops) fill straight
      // away so the Buy/Sell ticket actually opens the position instead of
      // resting as an unfilled order. Live orders fill at the broker.
      let fillNote = "";
      if (!isLive) {
        try {
          const fill = await simulateFill(result.order_id);
          if (fill.filled) {
            fillNote = ` · filled @ ${money(fill.price)}`;
            setSection("positions");
          }
        } catch {
          /* no quote or market closed — the order stays working */
        }
      }

      setNotice(`${result.message} — order ${result.order_id.slice(0, 8)}${fillNote}`);
      void refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelOrder = async (orderId: string) => {
    setFillBusyId(orderId);
    setError(null);
    setNotice(null);
    try {
      await cancelLiveOrder(orderId);
      setNotice(`Order ${orderId.slice(0, 8)} canceled`);
      void refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setFillBusyId(null);
    }
  };

  /** Broker-level kill switch: blocks new live orders until reset. */
  const handleKillSwitch = async () => {
    setError(null);
    setNotice(null);
    try {
      const statusRes = await fetch(`${API_BASE}/live/kill-switch/status`);
      const status = statusRes.ok ? ((await statusRes.json()) as { active?: boolean }) : {};
      if (status.active) {
        const res = await fetch(`${API_BASE}/live/kill-switch/deactivate`, { method: "POST" });
        if (!res.ok) throw new Error(await readLiveError(res));
        setNotice("Kill switch deactivated — live orders allowed again.");
      } else {
        if (!window.confirm("Activate the kill switch? New live orders will be blocked until you reset it.")) return;
        const res = await fetch(`${API_BASE}/live/kill-switch/activate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: "Activated from the live trading desk" }),
        });
        if (!res.ok) throw new Error(await readLiveError(res));
        setNotice("Kill switch ACTIVATED — new live orders are blocked.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kill switch failed");
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
    return <div className="paper-loading">{isLive ? "Loading live account…" : "Loading paper portfolio…"}</div>;
  }

  if (loadError) {
    return (
      <div className="paper-error" role="alert">
        {isLive ? "Live account unavailable" : "Paper portfolio unavailable"}:{" "}
        {loadError instanceof Error ? loadError.message : "unknown error"}
        <button className="btn-secondary" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    );
  }

  const activeMeta = meta(symbol);

  return (
    <div className="paper-trading">
      {(notice || error) && (
        <div className={error ? "paper-alert error" : "paper-alert"} role="status">
          <span>{error ?? notice}</span>
          <button className="btn-ghost" onClick={() => { setNotice(null); setError(null); }}>
            Dismiss
          </button>
        </div>
      )}

      {/* Account status — directly under the page header/description */}
      <div className={`desk-status ${isLive ? "live" : ""}`}>
        <div className="desk-status-metrics">
          <span><b>Equity</b> ${money(portfolio?.equity)}</span>
          <span><b>Cash</b> ${money(portfolio?.cash)}</span>
          <span><b>Buying power</b> ${money(portfolio?.buying_power)}</span>
          <span><b>Positions</b> {positions.length}</span>
          {isLive && portfolio?.portfolio_id ? (
            <span className="desk-account-id"><b>Account</b> {portfolio.portfolio_id.replace("live:", "")}</span>
          ) : null}
        </div>
      </div>

      <div className="paper-desk" style={deskStyle} ref={deskRef}>
        {/* Left icon rail */}
        <nav className="desk-rail" aria-label="Trading desk sections" ref={railRef}>
          {RAIL_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`desk-rail-item ${section === item.id ? "active" : ""}`}
              onClick={() => setSection(item.id)}
              aria-pressed={section === item.id}
            >
              <span className="desk-rail-icon" aria-hidden="true">{item.icon}</span>
              <span className="desk-rail-label">{item.label}</span>
            </button>
          ))}
          <div className="desk-rail-foot">
            <span className={`paper-live ${live ? "on" : ""}`}>
              {isLive ? "Broker" : live ? "Live" : "Poll"}
            </span>
            <span className={`paper-session ${marketOpen ? "open" : "closed"}`}>
              {marketOpen === null ? "…" : marketOpen ? "Open" : "Closed"}
            </span>
            <span className={`mode-badge ${isLive ? "live" : "paper"}`}>
              {isLive ? "LIVE" : "Paper"}
            </span>
            {isLive && (
              <button className="desk-kill-switch" onClick={() => void handleKillSwitch()} title="Broker kill switch — block new live orders">
                🛑 Kill switch
              </button>
            )}
          </div>
        </nav>

        {/* Watchlist */}
        <aside className="desk-watchlist" ref={watchlistRef}>
          <div className="desk-wl-scroll">
            <h3 className="desk-wl-title">Most Popular</h3>
            {WATCHLIST_GROUPS.filter((g) => g.section === "popular").map((g) => (
              <button
                key={g.id}
                className={`desk-wl-item ${groupId === g.id ? "active" : ""}`}
                onClick={() => { setGroupId(g.id); setSection("trade"); }}
              >
                {g.label}
              </button>
            ))}
            <h3 className="desk-wl-title desk-wl-title-gap">
              My Watchlists
              <button className="desk-wl-edit" title="Watchlist editing is decorative" aria-hidden="true">✎</button>
            </h3>
            {WATCHLIST_GROUPS.filter((g) => g.section === "mine").map((g) => (
              <button
                key={g.id}
                className={`desk-wl-item ${groupId === g.id ? "active" : ""}`}
                onClick={() => { setGroupId(g.id); setSection("trade"); }}
              >
                {g.label}
              </button>
            ))}
          </div>
        </aside>

        {/* Center: quote list + chart (Trade) or account panels */}
        <main className="desk-center">
          {section === "trade" && (
            <>
              <section
                className="desk-card desk-quotes-card"
                ref={quotesRef}
                style={quotesH !== null ? { height: `${quotesH}px`, maxHeight: "none" } : undefined}
              >
                <table className="desk-quotes">
                  <thead>
                    <tr>
                      <th>
                        <button className="desk-sort" onClick={() => setSortKey("name")}>
                          Instrument <span aria-hidden="true">{sortKey === "name" ? "⇅" : "⇅"}</span>
                        </button>
                      </th>
                      <th>
                        <button className="desk-sort" onClick={() => setSortKey("change")}>
                          Change <span aria-hidden="true">⇅</span>
                        </button>
                      </th>
                      <th>Sell</th>
                      <th>Buy</th>
                      <th aria-hidden="true" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const up = (row.changePct ?? 0) >= 0;
                      const selected = row.symbol === symbol;
                      return (
                        <tr
                          key={row.symbol}
                          className={selected ? "selected" : ""}
                          onClick={() => pickSymbol(row.symbol)}
                        >
                          <td>
                            <span className="desk-inst">
                              <span className="desk-inst-icon" style={{ background: row.meta.tint }} aria-hidden="true">
                                {row.meta.icon}
                              </span>
                              <span className="desk-inst-name">{row.meta.name}</span>
                            </span>
                          </td>
                          <td>
                            <span className={`desk-change ${up ? "up" : "down"}`}>
                              {row.changePct === null ? "—" : fmtPct(row.changePct)}
                            </span>
                          </td>
                          <td>
                            <button
                              className="desk-quote-btn sell"
                              onClick={(e) => { e.stopPropagation(); quoteTrade(row.symbol, "sell"); }}
                              disabled={!row.two}
                            >
                              <span>Sell</span>
                              <b>{row.two ? fmtPrice(row.two.sell) : "—"}</b>
                            </button>
                          </td>
                          <td>
                            <button
                              className="desk-quote-btn buy"
                              onClick={(e) => { e.stopPropagation(); quoteTrade(row.symbol, "buy"); }}
                              disabled={!row.two}
                            >
                              <span>Buy</span>
                              <b>{row.two ? fmtPrice(row.two.buy) : "—"}</b>
                            </button>
                          </td>
                          <td className="desk-chevron" aria-hidden="true">›</td>
                        </tr>
                      );
                    })}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={5} className="paper-empty">No instruments in this watchlist.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>

              {/* Drag vertically: more instruments vs. a taller chart */}
              <ResizeHandle
                side="top"
                orientation="horizontal"
                mode="delta"
                className="desk-handle-row"
                measureRef={quotesRef}
                width={quotesH ?? quotesHDefault()}
                minWidth={QUOTES_H_MIN}
                maxWidth={quotesHMax()}
                collapseBelow={QUOTES_H_MIN}
                collapsedWidth={QUOTES_H_MIN}
                defaultWidth={quotesHDefault()}
                storageKey={DESK_QUOTES_H_KEY}
                ariaLabel="Resize quote list height"
                onChange={applyQuotesHeight}
              />

              <section className="desk-card desk-chart-card">
                <div className="desk-chart-toolbar">
                  <span className="desk-chart-inst">
                    <span className="desk-inst-icon" style={{ background: activeMeta.tint }} aria-hidden="true">
                      {activeMeta.icon}
                    </span>
                    <b>{activeMeta.name}</b>
                    <span className={`desk-change ${(changePct ?? 0) >= 0 ? "up" : "down"}`}>
                      {changePct === null ? "—" : fmtPct(changePct)}
                    </span>
                  </span>
                  {two && (
                    <span className="desk-chart-prices">
                      <button className="desk-quote-btn sell" onClick={() => quoteTrade(symbol, "sell")}>
                        <span>Sell</span><b>{fmtPrice(two.sell)}</b>
                      </button>
                      <button className="desk-quote-btn buy" onClick={() => quoteTrade(symbol, "buy")}>
                        <span>Buy</span><b>{fmtPrice(two.buy)}</b>
                      </button>
                    </span>
                  )}
                  <div className="desk-chart-tools">
                    <button
                      className="tf-button chart-now-btn"
                      onClick={() => setNowSignal((n) => n + 1)}
                      title="Jump back to the most recent candle"
                    >
                      ⏱ Now
                    </button>
                    <ProviderSelect />
                    <IndicatorsButton />
                  </div>
                </div>
                <div className="desk-chart-body">
                  <MainChart
                    ticker={symbol}
                    historyData={chartBars}
                    loading={chartLoading}
                    liveUpdate={liveUpdate}
                    indicators={chartIndicators}
                    nowSignal={nowSignal}
                  />
                </div>
                <div className="desk-tf-row" role="group" aria-label="Chart timeframe">
                  {TF_CHIPS.map((chip, i) => (
                    <button
                      key={chip.label}
                      className={`tf-button ${i === tfIndex ? "active" : ""}`}
                      onClick={() => setTfIndex(i)}
                      aria-pressed={i === tfIndex}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              </section>
            </>
          )}

          {section === "positions" && (
            <section className="desk-card">
              <h3>Open positions</h3>
              {positions.length === 0 ? (
                <p className="paper-empty">No open positions — use the trade ticket to place your first order.</p>
              ) : (
                <table className="paper-table">
                  <thead>
                    <tr><th>Symbol</th><th>Qty</th><th>Avg cost</th><th>Market value</th><th>Unrealized PnL</th></tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.instrument_id}>
                        <td className="paper-symbol">{p.instrument_id}</td>
                        <td>{p.quantity}</td>
                        <td>{money(p.avg_cost)}</td>
                        <td>{money(p.market_value)}</td>
                        <td className={p.unrealized_pnl >= 0 ? "positive" : "negative"}>
                          {p.unrealized_pnl >= 0 ? "+" : ""}{money(p.unrealized_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {section === "orders" && (
            <section className="desk-card">
              <h3>Open orders</h3>
              {openOrders.length === 0 ? (
                <p className="paper-empty">No working orders.</p>
              ) : (
                <table className="paper-table">
                  <thead>
                    <tr><th>Symbol</th><th>Side</th><th>Type</th><th>Qty</th><th>Price</th><th>Status</th><th /></tr>
                  </thead>
                  <tbody>
                    {openOrders.map((o) => (
                      <tr key={o.id}>
                        <td className="paper-symbol">{o.instrument_id}</td>
                        <td><span className={`side-badge ${o.side}`}>{o.side === "buy" ? "Buy" : "Sell"}</span></td>
                        <td>{o.type}</td>
                        <td>{o.qty}</td>
                        <td>{o.limit_price ? money(o.limit_price) : o.stop_price ? money(o.stop_price) : "—"}</td>
                        <td>{o.status}</td>
                        <td>
                          {isLive ? (
                            <button
                              className="btn-secondary paper-fill-btn"
                              onClick={() => void handleCancelOrder(o.id)}
                              disabled={fillBusyId === o.id}
                            >
                              {fillBusyId === o.id ? "…" : "Cancel"}
                            </button>
                          ) : (
                            <button
                              className="btn-secondary paper-fill-btn"
                              onClick={() => void handleSimulateFill(o.id)}
                              disabled={fillBusyId === o.id}
                            >
                              {fillBusyId === o.id ? "…" : "Simulate fill"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {section === "closed" && (
            <section className="desk-card">
              <h3>Closed positions / recent fills</h3>
              {recentFills.length === 0 ? (
                <p className="paper-empty">No fills yet.</p>
              ) : (
                <table className="paper-table">
                  <thead>
                    <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Comm.</th></tr>
                  </thead>
                  <tbody>
                    {recentFills.map((f) => (
                      <tr key={f.id}>
                        <td>{new Date(f.timestamp).toLocaleTimeString()}</td>
                        <td className="paper-symbol">{f.instrument_id}</td>
                        <td><span className={`side-badge ${f.side}`}>{f.side === "buy" ? "Buy" : "Sell"}</span></td>
                        <td>{f.qty}</td>
                        <td>{money(f.price)}</td>
                        <td>{money(f.commission)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}

          {section === "insights" && (
            <section className="desk-card">
              <h3>+Insights — {activeMeta.name}</h3>
              {analysis ? (
                <div className="desk-insight">
                  <div className="desk-insight-dir">
                    <span className={`desk-insight-badge ${analysis.direction ?? "neutral"}`}>
                      {(analysis.direction ?? "neutral").toUpperCase()}
                    </span>
                    <span>Confidence {Math.round((analysis.overall_confidence ?? 0) * 100)}%</span>
                    <span>RSI {analysis.rsi !== undefined ? analysis.rsi.toFixed(1) : "—"}</span>
                  </div>
                  <p className="paper-empty">Model read for {symbol}. Trade from the ticket — this is not advice.</p>
                </div>
              ) : (
                <p className="paper-empty">No analysis available for {symbol}.</p>
              )}
            </section>
          )}

          {section === "funds" && (
            <section className="desk-card">
              <h3>Funds</h3>
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
                  <span className="paper-metric-label">Open positions</span>
                  <span className="paper-metric-value">{positions.length}</span>
                </div>
              </div>
              <p className="paper-empty">
                {isLive
                  ? "Real funds in your linked broker account — orders route to the exchange. Positions and fills refresh from the broker feed."
                  : "Simulated cash only — orders fill against live quotes with a \u201cpaper\u201d spread and commission."}
              </p>
            </section>
          )}
        </main>

        <aside className="desk-ticket" ref={ticketRef}>
          <div className="desk-ticket-tabs" role="tablist" aria-label="Ticket views">
            {TICKET_TABS.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={ticketTab === tab.id}
                className={`desk-ticket-tab ${ticketTab === tab.id ? "active" : ""}`}
                onClick={() => setTicketTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="desk-ticket-head">
            <span className="desk-inst-icon lg" style={{ background: activeMeta.tint }} aria-hidden="true">
              {activeMeta.icon}
            </span>
            <div className="desk-ticket-title">
              <h3>{activeMeta.name}</h3>
              <span className="desk-ticket-sub">
                ({symbol}){" "}
                <span className={`desk-change ${(changePct ?? 0) >= 0 ? "up" : "down"}`}>
                  {changePct === null ? "—" : fmtPct(changePct)} {(changePct ?? 0) >= 0 ? "↑" : "↓"}
                </span>
              </span>
            </div>
          </div>

          <div className="desk-ticket-prices">
            <button
              className={`desk-price-box sell ${orderForm.side === "sell" && ticketTab === "trade" ? "armed" : ""}`}
              onClick={() => { setOrderForm((f) => ({ ...f, side: "sell" })); setTicketTab("trade"); }}
            >
              <span>Sell</span>
              <b>{two ? fmtPrice(two.sell) : "—"}</b>
            </button>
            <button
              className={`desk-price-box buy ${orderForm.side === "buy" && ticketTab === "trade" ? "armed" : ""}`}
              onClick={() => { setOrderForm((f) => ({ ...f, side: "buy" })); setTicketTab("trade"); }}
            >
              <span>Buy</span>
              <b>{two ? fmtPrice(two.buy) : "—"}</b>
            </button>
          </div>

          {/* Live position for the selected instrument (opens with the ticket) */}
          <div className={`desk-position ${activePosition ? "has" : ""}`}>
            {activePosition ? (
              <>
                <span className="desk-position-label">Your position</span>
                <span className="desk-position-qty">
                  {activePosition.quantity} × {symbol}
                </span>
                <span className="desk-position-meta">
                  avg {money(activePosition.avg_cost)} · MV {money(activePosition.market_value)}
                </span>
                <span className={`desk-position-pnl ${activePosition.unrealized_pnl >= 0 ? "up" : "down"}`}>
                  {activePosition.unrealized_pnl >= 0 ? "+" : ""}
                  {money(activePosition.unrealized_pnl)}
                </span>
              </>
            ) : (
              <span className="desk-position-empty">No open position in {symbol}</span>
            )}
          </div>

          <div className="desk-bites">
            <span className="desk-bites-label" title="Quick model take on the selected instrument">
              <span aria-hidden="true">📊</span> +AI Bites
              <span className="desk-bites-info" aria-hidden="true">ⓘ</span>
            </span>
            <button className="desk-bites-cta" onClick={() => setTicketTab("insights")}>
              Get analysis
            </button>
          </div>

          <div className="desk-ticket-body">
            {ticketTab === "overview" && (
              <RightInspector activeView="paper-trading" selectedSymbol={symbol} collapsed={false} />
            )}

            {ticketTab === "trade" && (
              <form onSubmit={handleSubmit} className="paper-order-form">
                <div className="paper-form-row">
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
                  <label className="paper-field">
                    <span>Type</span>
                    <select
                      value={orderForm.order_type}
                      onChange={(e) => setOrderForm({ ...orderForm, order_type: e.target.value as "market" | "limit" | "stop" })}
                    >
                      <option value="market">Market</option>
                      <option value="limit">Limit</option>
                      <option value="stop">Stop</option>
                    </select>
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

                <div className="paper-order-foot">
                  {estimatedCost !== null && <span className="paper-est">Est. ≈ ${money(estimatedCost)}</span>}
                  <button
                    type="submit"
                    className={`btn-primary paper-submit ${orderForm.side}`}
                    disabled={submitting || orderForm.quantity < 1 || two === null}
                  >
                    {submitting
                      ? "Submitting…"
                      : `${orderForm.side === "buy" ? "Buy" : "Sell"} ${orderForm.quantity} ${symbol}`}
                  </button>
                </div>
              </form>
            )}

            {ticketTab === "info" && (
              <div className="desk-live-stats">
                <h4 className="desk-ls-title">Live Statistics <span aria-hidden="true">ⓘ</span></h4>
                <div className="desk-ls-changes" role="group" aria-label="Change over time">
                  {[
                    { label: "5 Minutes", value: stats.change5m },
                    { label: "1 Hour", value: stats.change1h },
                    { label: "1 Day", value: stats.change1d },
                  ].map((cell) => (
                    <div key={cell.label} className="desk-ls-cell">
                      <b className={(cell.value ?? 0) >= 0 ? "up" : "down"}>{fmtPct(cell.value)}</b>
                      <span>{cell.label}</span>
                    </div>
                  ))}
                </div>

                <div className="desk-ls-rate">
                  Current sell rate: <b>{stats.sellRate !== null ? fmtPrice(stats.sellRate) : "—"}</b>
                </div>

                <div className="desk-ls-ranges">
                  <div className="desk-ls-range-head"><span>Low</span><span>High</span></div>
                  {stats.ranges.map((range) => (
                    <div key={range.label} className="desk-ls-range">
                      <div className="desk-ls-bar">
                        <span
                          className="desk-ls-marker"
                          style={{ left: `${Math.round((range.marker ?? 0) * 100)}%` }}
                          aria-hidden="true"
                        />
                      </div>
                      <div className="desk-ls-range-meta">
                        <span>{fmtPrice(range.low)}</span>
                        <span className="desk-ls-range-label">{range.label}</span>
                        <span>{fmtPrice(range.high)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {ticketTab === "insights" && (
              <div className="desk-insight">
                {analysis ? (
                  <div className="desk-insight-dir">
                    <span className={`desk-insight-badge ${analysis.direction ?? "neutral"}`}>
                      {(analysis.direction ?? "neutral").toUpperCase()}
                    </span>
                    <span>Confidence {Math.round((analysis.overall_confidence ?? 0) * 100)}%</span>
                    <span>RSI {analysis.rsi !== undefined ? analysis.rsi.toFixed(1) : "—"}</span>
                  </div>
                ) : (
                  <p className="paper-empty">Loading analysis for {symbol}…</p>
                )}
                <p className="paper-empty">Model read only — not investment advice.</p>
              </div>
            )}
          </div>

          {ticketTab !== "overview" && (
            <div className="desk-ticket-news">
              <h4 className="desk-ls-title">In the news</h4>
            {newsItems.length > 0 ? (
              newsItems.map((item) => (
                <a
                  key={item.id || item.headline}
                  className="desk-news-item"
                  href={item.url || "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={item.headline}
                >
                  <span className="desk-news-source">{item.source || "News"}</span>
                  <span className="desk-news-headline">{item.headline}</span>
                </a>
              ))
            ) : (
              <p className="paper-empty">No recent headlines for {symbol}.</p>
            )}
            </div>
          )}
        </aside>

        {/* Drag a section's edge to resize it; double-click resets. */}
        <ResizeHandle
          side="left"
          mode="delta"
          className="desk-handle desk-handle-rail"
          measureRef={railRef}
          width={railW ?? DESK_DEFAULTS.rail}
          minWidth={DESK_LIMITS.rail.min}
          maxWidth={DESK_LIMITS.rail.max}
          collapseBelow={DESK_LIMITS.rail.min}
          collapsedWidth={DESK_LIMITS.rail.min}
          defaultWidth={DESK_DEFAULTS.rail}
          storageKey={DESK_WIDTH_KEYS.rail}
          ariaLabel="Resize section rail"
          onChange={(w) => setDeskWidth("rail", w, setRailW)}
        />
        <ResizeHandle
          side="left"
          mode="delta"
          className="desk-handle desk-handle-watchlist"
          measureRef={watchlistRef}
          width={watchlistW ?? DESK_DEFAULTS.watchlist}
          minWidth={DESK_LIMITS.watchlist.min}
          maxWidth={DESK_LIMITS.watchlist.max}
          collapseBelow={DESK_LIMITS.watchlist.min}
          collapsedWidth={DESK_LIMITS.watchlist.min}
          defaultWidth={DESK_DEFAULTS.watchlist}
          storageKey={DESK_WIDTH_KEYS.watchlist}
          ariaLabel="Resize watchlist"
          onChange={(w) => setDeskWidth("watchlist", w, setWatchlistW)}
        />
        <ResizeHandle
          side="right"
          mode="delta"
          className="desk-handle desk-handle-ticket"
          measureRef={ticketRef}
          width={ticketW ?? DESK_DEFAULTS.ticket}
          minWidth={DESK_LIMITS.ticket.min}
          maxWidth={DESK_LIMITS.ticket.max}
          collapseBelow={DESK_LIMITS.ticket.min}
          collapsedWidth={DESK_LIMITS.ticket.min}
          defaultWidth={DESK_DEFAULTS.ticket}
          storageKey={DESK_WIDTH_KEYS.ticket}
          ariaLabel="Resize trade ticket"
          onChange={(w) => setDeskWidth("ticket", w, setTicketW)}
        />
      </div>
    </div>
  );
}
