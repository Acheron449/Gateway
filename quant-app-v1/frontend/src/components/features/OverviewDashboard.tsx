import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE } from "../../lib/constants";
import { NewsPage } from "../../components/features/NewsPage";

/**
 * Overview dashboard — the quadrant-style market home screen.
 *
 * Layout mirrors the reference design: a market-overview ticker strip with
 * sparklines, a main chart with range tabs, market movers, a news preview
 * (category tabs, fixed-height preview + full-page overlay), SEC filings,
 * a risk summary, a watchlist table, and a sector heat map.
 *
 * Every panel is fed by existing public endpoints:
 *   /quotes, /history/{sym}, /news, /filings, /risk/metrics, /risk/alerts
 * so the page needs no new backend surface beyond /filings.
 */

// ---------------------------------------------------------------------------
// Static configuration
// ---------------------------------------------------------------------------

/** Market-overview strip: label + Gateway ticker (Yahoo symbols). */
const STRIP: { symbol: string; label: string }[] = [
  { symbol: "^GSPC", label: "S&P 500" },
  { symbol: "^IXIC", label: "Nasdaq" },
  { symbol: "^DJI", label: "Dow Jones" },
  { symbol: "BTC-USD", label: "BTC" },
  { symbol: "ETH-USD", label: "ETH" },
  { symbol: "GC=F", label: "Gold" },
  { symbol: "CL=F", label: "WTI Crude" },
  { symbol: "^TNX", label: "10Y Yield" },
];

/** Range tabs → (tf, limit) for the /history endpoint's yfinance mapping. */
const RANGES: { id: string; label: string; tf: string; limit: number }[] = [
  { id: "1d", label: "1D", tf: "1m", limit: 390 },
  { id: "1w", label: "1W", tf: "15m", limit: 220 },
  { id: "1m", label: "1M", tf: "1h", limit: 170 },
  { id: "3m", label: "3M", tf: "1d", limit: 65 },
  { id: "1y", label: "1Y", tf: "1d", limit: 260 },
  { id: "all", label: "ALL", tf: "1wk", limit: 260 },
];

/** Liquid basket used for movers + the heat map (one shared /quotes call). */
const MOVER_BASKET = [
  "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA", "NFLX",
  "AMD", "INTC", "JPM", "V", "WMT", "DIS", "XOM", "BTC-USD",
];

/** Static sector grouping for the heat map (by the basket above). */
const SECTORS: { name: string; symbols: string[] }[] = [
  { name: "Technology", symbols: ["AAPL", "MSFT", "NVDA", "AMD", "INTC"] },
  { name: "Communication", symbols: ["GOOG", "META", "NFLX", "DIS"] },
  { name: "Consumer", symbols: ["AMZN", "TSLA", "WMT"] },
  { name: "Financials", symbols: ["JPM", "V"] },
  { name: "Energy", symbols: ["XOM"] },
  { name: "Crypto", symbols: ["BTC-USD"] },
];

/** Watchlist tabs: grouped baskets rendered as the table. */
const WATCH_TABS: { id: string; label: string; symbols: { symbol: string; label: string }[] }[] = [
  { id: "indexes", label: "Indexes", symbols: STRIP },
  {
    id: "stocks",
    label: "Stocks",
    symbols: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA"].map((s) => ({ symbol: s, label: s })),
  },
  {
    id: "crypto",
    label: "Crypto",
    symbols: ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"].map((s) => ({ symbol: s, label: s.split("-")[0] ?? s })),
  },
];

/** Filing tabs (Watchlist/Recent are views; Insider filters Form 4 rows). */
const FILING_TABS = ["Watchlist", "Recent", "Insider", "Transcripts"] as const;

/** News category tabs — keyword match over headline/source/categories. */
const NEWS_TABS: { id: string; label: string; keywords: string[] | null }[] = [
  { id: "top", label: "Top", keywords: null },
  { id: "markets", label: "Markets", keywords: ["market", "stock", "rally", "selloff", "investor", "nasdaq", "dow", "s&p"] },
  { id: "economy", label: "Economy", keywords: ["fed ", "federal reserve", "inflation", "cpi", "rate", "economy", "jobs", "treasury"] },
  { id: "tech", label: "Tech", keywords: [" ai", "ai ", "chip", "semiconductor", "tech", "apple", "nvidia", "google", "microsoft"] },
  { id: "energy", label: "Energy", keywords: ["oil", "crude", "energy", "gas", "opec", "wti"] },
  { id: "deals", label: "Deals", keywords: ["acqui", "merger", "deal", "buyout", "stake", "takeover"] },
];

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

interface Quote {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
}

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface NewsStory {
  id: string;
  headline: string;
  url?: string;
  source: string;
  thumbnail?: string | null;
  published_at: string;
  related_symbols: string[];
}

interface Filing {
  symbol: string;
  type: string;
  date: string | null;
  title: string;
  url?: string | null;
}

interface RiskMetrics {
  portfolio_value?: number;
  cash?: number;
  daily_pnl?: number;
  daily_pnl_pct?: number;
  max_drawdown?: number;
  current_drawdown?: number;
  gross_exposure?: number;
  net_exposure?: number;
  open_positions?: number;
  var_95?: number;
  concentration_risk?: { symbol: string; pct: number }[];
}

interface RiskAlert {
  id: string;
  type: string;
  message: string;
  acknowledged: boolean;
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

/** Compact sparkline for the ticker strip (points → polyline). */
function Sparkline({ points, up }: { points: number[]; up: boolean }) {
  if (points.length < 2) return <span className="ov-spark empty" aria-hidden="true" />;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 28 - ((value - min) / span) * 26 - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="ov-spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
      <polyline
        points={path}
        fill="none"
        stroke={up ? "#22c55e" : "#ef4444"}
        strokeWidth="1.6"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Area chart for the main markets panel (close line + gradient fill). */
function AreaChart({ candles }: { candles: Candle[] }) {
  if (candles.length < 2) return <div className="ov-chart-empty empty-state">No chart data</div>;

  const W = 720;
  const H = 260;
  const pad = { l: 8, r: 56, t: 14, b: 24 };
  const closes = candles.map((c) => c.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const first = candles[0]!; // guarded by candles.length < 2 above
  const last = candles[candles.length - 1]!;
  const t0 = first.time;
  const t1 = last.time;
  const spanT = t1 - t0 || 1;
  const up = last.close >= first.close;
  const color = up ? "#22c55e" : "#ef4444";

  const x = (t: number) => pad.l + ((t - t0) / spanT) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / span) * (H - pad.t - pad.b);

  const line = candles.map((c) => `${x(c.time).toFixed(1)},${y(c.close).toFixed(1)}`).join(" ");
  const area = `${pad.l},${H - pad.b} ${line} ${x(t1).toFixed(1)},${H - pad.b}`;
  const label = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  return (
    <svg className="ov-chart-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Price chart">
      <defs>
        <linearGradient id="ov-area-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {/* Value gridlines with right-hand labels */}
      {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
        const value = min + span * frac;
        const yy = y(value);
        return (
          <g key={frac}>
            <line x1={pad.l} y1={yy} x2={W - pad.r} y2={yy} stroke="var(--border-primary)" strokeWidth="0.6" opacity="0.6" />
            <text x={W - pad.r + 6} y={yy + 3} className="ov-axis-label">
              {value >= 1000 ? value.toFixed(0) : value.toFixed(2)}
            </text>
          </g>
        );
      })}
      <polygon points={area} fill="url(#ov-area-fill)" />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      <text x={pad.l} y={H - 6} className="ov-axis-label">{label(t0)}</text>
      <text x={W - pad.r} y={H - 6} textAnchor="end" className="ov-axis-label">{label(t1)}</text>
    </svg>
  );
}

/** Section shell shared by all overview cards. */
function Card({
  title,
  extra,
  className,
  children,
}: {
  title: string;
  extra?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`ov-card ${className ?? ""}`}>
      <header className="ov-card-head">
        <h3>{title}</h3>
        <div className="ov-card-extra">{extra}</div>
      </header>
      {children}
    </section>
  );
}

/** Tab-chip row (reuses the app's .filter-chip styling). */
function Tabs<T extends string>({
  tabs,
  active,
  onSelect,
}: {
  tabs: readonly T[];
  active: T;
  onSelect: (tab: T) => void;
}) {
  return (
    <div className="ov-tabs">
      {tabs.map((tab) => (
        <button
          key={tab}
          type="button"
          className={`filter-chip ${active === tab ? "on" : ""}`}
          onClick={() => onSelect(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data helpers
// ---------------------------------------------------------------------------

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

async function fetchQuotes(symbols: string[]): Promise<Quote[]> {
  const payload = await fetchJson<{ quotes?: Quote[] }>(`/quotes?symbols=${symbols.join(",")}`);
  return payload.quotes ?? [];
}

async function fetchCandles(symbol: string, tf: string, limit: number): Promise<Candle[]> {
  const rows = await fetchJson<Candle[]>(`/history/${encodeURIComponent(symbol)}?tf=${tf}&limit=${limit}`);
  return Array.isArray(rows) ? rows : [];
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60000);
  if (minutes < 60) return `${Math.max(minutes, 1)}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function pct(value: number | undefined, digits = 2): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function pickSymbol(symbol: string) {
  window.dispatchEvent(new CustomEvent("symbol-select", { detail: symbol }));
}

// ---------------------------------------------------------------------------
// Overview dashboard
// ---------------------------------------------------------------------------

export function OverviewDashboard({ selectedSymbol }: { selectedSymbol: string }) {
  // --- market strip -------------------------------------------------------
  const [stripQuotes, setStripQuotes] = useState<Record<string, Quote>>({});
  const [stripSparks, setStripSparks] = useState<Record<string, number[]>>({});

  // --- main chart (defaults to the app's selected symbol, like the strip) ---
  const [chartSymbol, setChartSymbol] = useState(selectedSymbol || "^GSPC");
  const [chartLabel, setChartLabel] = useState(
    STRIP.find((s) => s.symbol === selectedSymbol)?.label ?? selectedSymbol ?? "S&P 500",
  );
  const [range, setRange] = useState("1y");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [chartLoading, setChartLoading] = useState(true);

  // --- movers / heat map (one shared quote basket) -----------------------
  const [basket, setBasket] = useState<Quote[]>([]);
  const [moverTab, setMoverTab] = useState<"gainers" | "losers">("gainers");

  // --- news ---------------------------------------------------------------
  const [news, setNews] = useState<NewsStory[]>([]);
  const [newsTab, setNewsTab] = useState("top");
  const [newsOpen, setNewsOpen] = useState(false);
  const [newsError, setNewsError] = useState<string | null>(null);

  // --- filings ------------------------------------------------------------
  const [filings, setFilings] = useState<Filing[]>([]);
  const [filingTab, setFilingTab] = useState<(typeof FILING_TABS)[number]>("Watchlist");

  // --- risk ---------------------------------------------------------------
  const [riskMetrics, setRiskMetrics] = useState<RiskMetrics | null>(null);
  const [riskAlerts, setRiskAlerts] = useState<RiskAlert[]>([]);

  // --- watchlist ----------------------------------------------------------
  const [watchTab, setWatchTab] = useState("indexes");
  const [watchRows, setWatchRows] = useState<Record<string, { quote?: Quote; ytd?: number }>>({});
  const [watchLoading, setWatchLoading] = useState(false);

  // Panels load independently so one slow feed never blocks the page.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const quotes = await fetchQuotes(STRIP.map((s) => s.symbol));
        if (cancelled) return;
        setStripQuotes(Object.fromEntries(quotes.map((q) => [q.symbol, q])));
      } catch {
        /* strip degrades to dashes when quotes are unreachable */
      }
      // Sparklines: 30 daily closes per strip symbol, in parallel.
      STRIP.forEach(({ symbol }) => {
        fetchCandles(symbol, "1d", 30)
          .then((rows) => {
            if (!cancelled && rows.length) {
              setStripSparks((prev) => ({ ...prev, [symbol]: rows.map((c) => c.close) }));
            }
          })
          .catch(() => undefined);
      });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Main chart reloads when the symbol or range tab changes.
  useEffect(() => {
    let cancelled = false;
    setChartLoading(true);
    const spec = RANGES.find((r) => r.id === range) ?? RANGES[0]!;
    fetchCandles(chartSymbol, spec.tf, spec.limit)
      .then((rows) => {
        if (!cancelled) setCandles(rows);
      })
      .catch(() => {
        if (!cancelled) setCandles([]);
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chartSymbol, range]);

  // Movers + heat map share one basket fetch.
  useEffect(() => {
    let cancelled = false;
    fetchQuotes(MOVER_BASKET)
      .then((rows) => {
        if (!cancelled) setBasket(rows);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // News preview (category filtering happens client-side below).
  useEffect(() => {
    let cancelled = false;
    fetchJson<{ items?: NewsStory[]; status?: string; message?: string }>(`/news?limit=20`)
      .then((payload) => {
        if (!cancelled) setNews(payload.items ?? []);
      })
      .catch((err) => {
        if (!cancelled) setNewsError(err instanceof Error ? err.message : "Failed to load news");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // SEC filings for the watchlist basket (cached server-side for 10 min).
  useEffect(() => {
    let cancelled = false;
    const symbols = WATCH_TABS.find((t) => t.id === "stocks")!.symbols.map((s) => s.symbol).join(",");
    fetchJson<{ items?: Filing[] }>(`/filings?symbols=${symbols}&limit=6`)
      .then((payload) => {
        if (!cancelled) setFilings(payload.items ?? []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Risk summary (metrics + alerts from the risk module).
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([fetchJson<RiskMetrics>(`/risk/metrics`), fetchJson<{ alerts?: RiskAlert[] }>(`/risk/alerts`)]).then(
      ([metrics, alerts]) => {
        if (cancelled) return;
        if (metrics.status === "fulfilled") setRiskMetrics(metrics.value);
        if (alerts.status === "fulfilled") setRiskAlerts(alerts.value.alerts ?? []);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // Watchlist rows: quotes for the active tab + YTD from daily history.
  const loadWatchTab = useCallback(async (tabId: string) => {
    const tab = WATCH_TABS.find((t) => t.id === tabId);
    if (!tab) return;
    setWatchLoading(true);
    try {
      const symbols = tab.symbols.map((s) => s.symbol);
      const quotes = await fetchQuotes(symbols);
      const quoteMap = Object.fromEntries(quotes.map((q) => [q.symbol, q]));
      const rows: Record<string, { quote?: Quote; ytd?: number }> = {};
      symbols.forEach((symbol) => {
        rows[symbol] = { quote: quoteMap[symbol] };
      });
      setWatchRows(rows);
      // YTD: first daily close of the current calendar year vs latest close.
      const year = new Date().getFullYear();
      await Promise.all(
        symbols.map(async (symbol) => {
          try {
            const daily = await fetchCandles(symbol, "1d", 260);
            if (daily.length < 2) return;
            const currentYear = daily.filter((c) => new Date(c.time * 1000).getFullYear() === year);
            const base = (currentYear[0] ?? daily[0])!.close;
            const last = daily[daily.length - 1]!.close;
            setWatchRows((prev) => ({
              ...prev,
              [symbol]: { ...prev[symbol], ytd: ((last - base) / base) * 100 },
            }));
          } catch {
            /* leave YTD as "—" when history is unreachable */
          }
        }),
      );
    } finally {
      setWatchLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWatchTab(watchTab);
  }, [watchTab, loadWatchTab]);

  // --- derived state ------------------------------------------------------
  const movers = useMemo(() => {
    const sorted = [...basket].sort((a, b) => b.change_pct - a.change_pct);
    return moverTab === "gainers" ? sorted : sorted.reverse();
  }, [basket, moverTab]);

  const visibleNews = useMemo(() => {
    const tab = NEWS_TABS.find((t) => t.id === newsTab);
    if (!tab?.keywords) return news;
    return news.filter((story) => {
      const haystack = `${story.headline} ${story.source}`.toLowerCase();
      return tab.keywords!.some((word) => haystack.includes(word));
    });
  }, [news, newsTab]);

  const visibleFilings = useMemo(() => {
    // Cap rows so the card stays card-sized (the full feed is per-symbol
    // paginated server-side); newest filings sort first.
    const CAP = 8;
    if (filingTab === "Insider") {
      return filings.filter((f) => /^4\/?A?$/i.test(f.type.trim())).slice(0, CAP);
    }
    if (filingTab === "Transcripts") return []; // not part of the SEC forms feed
    if (filingTab === "Watchlist") {
      const watch = new Set(WATCH_TABS.find((t) => t.id === "stocks")!.symbols.map((s) => s.symbol));
      return filings.filter((f) => watch.has(f.symbol)).slice(0, CAP);
    }
    return filings.slice(0, CAP);
  }, [filings, filingTab]);

  const chartQuote = stripQuotes[chartSymbol] ?? basket.find((q) => q.symbol === chartSymbol);
  const lastCandle = candles[candles.length - 1];
  const firstCandle = candles[0];
  const chartUp = !!(lastCandle && firstCandle && lastCandle.close >= firstCandle.close);

  // Risk checklist derived from the real metrics/alert fields.
  const checklist = useMemo(() => {
    const worst = (riskMetrics?.concentration_risk ?? []).reduce((max, row) => Math.max(max, row.pct ?? 0), 0);
    const items: { label: string; ok: boolean; note: string }[] = [
      { label: "Concentration", ok: worst <= 10, note: worst ? `Top position ${worst.toFixed(1)}%` : "No open positions" },
      { label: "Leverage", ok: (riskMetrics?.gross_exposure ?? 0) <= 0.8, note: `${((riskMetrics?.gross_exposure ?? 0) * 100).toFixed(0)}% gross exposure` },
      { label: "Drawdown", ok: (riskMetrics?.current_drawdown ?? 0) < (riskMetrics?.max_drawdown ?? 100), note: `${(riskMetrics?.current_drawdown ?? 0).toFixed(1)}% of ${(riskMetrics?.max_drawdown ?? 0).toFixed(1)}% limit` },
      { label: "Daily P&L", ok: (riskMetrics?.daily_pnl_pct ?? 0) > -3, note: pct(riskMetrics?.daily_pnl_pct) },
      { label: "Alerts", ok: !riskAlerts.some((a) => !a.acknowledged && a.type === "critical"), note: riskAlerts.length ? `${riskAlerts.filter((a) => !a.acknowledged).length} unacknowledged` : "None active" },
    ];
    return items;
  }, [riskMetrics, riskAlerts]);

  // --- render -------------------------------------------------------------
  return (
    <div className="canvas-view ov-page">
      <div className="view-header">
        <h1>Overview</h1>
        <p className="view-description">Markets, news, filings and risk at a glance</p>
      </div>

      {/* Market overview strip — click a tile to load it in the main chart */}
      <div className="ov-strip">
        {STRIP.map(({ symbol, label }) => {
          const quote = stripQuotes[symbol];
          const up = (quote?.change_pct ?? 0) >= 0;
          const spark = stripSparks[symbol] ?? [];
          return (
            <button
              key={symbol}
              type="button"
              className={`ov-tile ${chartSymbol === symbol ? "on" : ""}`}
              onClick={() => {
                setChartSymbol(symbol);
                setChartLabel(label);
              }}
            >
              <span className="ov-tile-label">{label}</span>
              <span className="ov-tile-price">{quote ? quote.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</span>
              <span className={`ov-tile-change ${up ? "up" : "down"}`}>{quote ? pct(quote.change_pct, 2) : "—"}</span>
              <Sparkline points={spark} up={up} />
            </button>
          );
        })}
      </div>

      <div className="ov-grid">
        {/* Main chart */}
        <Card
          title={chartLabel}
          className="ov-chart-card"
          extra={
            <div className="ov-chart-meta">
              <span className="ov-chart-price">
                {chartQuote ? chartQuote.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : candles.at(-1)?.close.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—"}
              </span>
              <span className={chartUp ? "up" : "down"}>
                {chartQuote ? pct(chartQuote.change_pct) : pct(chartUp ? 1 : -1)}
              </span>
              <Tabs tabs={RANGES.map((r) => r.id)} active={range} onSelect={setRange} />
              <span className="ov-range-label">
                {RANGES.find((r) => r.id === range)?.label}
              </span>
            </div>
          }
        >
          {chartLoading ? <div className="ov-chart-empty">Loading chart…</div> : <AreaChart candles={candles} />}
        </Card>

        {/* Market movers */}
        <Card
          title="Market Movers"
          extra={
            <Tabs
              tabs={["gainers", "losers"] as const}
              active={moverTab}
              onSelect={setMoverTab}
            />
          }
        >
          <div className="ov-movers">
            {movers.length === 0 && <div className="empty-state">Loading quotes…</div>}
            {movers.slice(0, 8).map((row, index) => (
              <button key={row.symbol} type="button" className="ov-mover-row" onClick={() => pickSymbol(row.symbol)}>
                <span className="ov-rank">{index + 1}</span>
                <span className="ov-mover-symbol">{row.symbol.replace("-USD", "")}</span>
                <span className="ov-mover-price">{row.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                <span className={row.change_pct >= 0 ? "up" : "down"}>{pct(row.change_pct)}</span>
              </button>
            ))}
          </div>
        </Card>

        {/* News preview */}
        <Card
          title="News"
          extra={
            <button type="button" className="btn-secondary ov-view-all" onClick={() => setNewsOpen(true)}>
              View all
            </button>
          }
        >
          <Tabs tabs={NEWS_TABS.map((t) => t.id)} active={newsTab} onSelect={setNewsTab} />
          <div className="ov-news-list">
            {newsError && <div className="empty-state">{newsError}</div>}
            {!newsError && visibleNews.length === 0 && <div className="empty-state">No headlines right now.</div>}
            {/* Preview is capped at what fits the card; View all opens the scrollable page. */}
            {visibleNews.slice(0, 4).map((story) => (
              <a key={story.id} className="ov-news-row" href={story.url || "#"} target="_blank" rel="noopener noreferrer">
                {story.thumbnail ? (
                  <img className="ov-news-thumb" src={story.thumbnail} alt="" loading="lazy" />
                ) : (
                  <span className="ov-news-thumb placeholder" aria-hidden="true">📰</span>
                )}
                <span className="ov-news-body">
                  <span className="ov-news-headline">{story.headline}</span>
                  <span className="ov-news-meta">
                    {story.source}
                    {story.published_at ? ` · ${timeAgo(story.published_at)}` : ""}
                  </span>
                </span>
              </a>
            ))}
          </div>
        </Card>

        {/* Filings */}
        <Card title="Filings">
          <Tabs tabs={FILING_TABS} active={filingTab} onSelect={setFilingTab} />
          <div className="ov-table-wrap">
            {visibleFilings.length === 0 ? (
              <div className="empty-state">
                {filingTab === "Transcripts" ? "Transcripts are not part of the SEC forms feed." : "No filings found."}
              </div>
            ) : (
              <table className="ov-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Type</th>
                    <th>Date</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleFilings.map((filing, index) => (
                    <tr key={`${filing.symbol}-${filing.type}-${index}`}>
                      <td>{filing.symbol}</td>
                      <td>{filing.type}</td>
                      <td>{filing.date ? new Date(filing.date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—"}</td>
                      <td className="ov-cell-truncate" title={filing.title}>
                        {filing.url ? (
                          <a href={filing.url} target="_blank" rel="noopener noreferrer">
                            {filing.title}
                          </a>
                        ) : (
                          filing.title
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>

        {/* Risk summary — metrics + derived checklist side by side */}
        <Card title="Risk">
          <div className="ov-risk">
            <div className="ov-risk-metrics">
              {riskMetrics ? (
                <>
                  <div className="ov-risk-row"><span>Portfolio value</span><strong>${(riskMetrics.portfolio_value ?? 0).toLocaleString()}</strong></div>
                  <div className="ov-risk-row"><span>Daily P&L</span><strong className={(riskMetrics.daily_pnl ?? 0) >= 0 ? "up" : "down"}>{pct(riskMetrics.daily_pnl_pct)}</strong></div>
                  <div className="ov-risk-row"><span>Max drawdown</span><strong className="down">{(riskMetrics.max_drawdown ?? 0).toFixed(1)}%</strong></div>
                  <div className="ov-risk-row"><span>Current drawdown</span><strong>{(riskMetrics.current_drawdown ?? 0).toFixed(1)}%</strong></div>
                  <div className="ov-risk-row"><span>Gross exposure</span><strong>{((riskMetrics.gross_exposure ?? 0) * 100).toFixed(0)}%</strong></div>
                  <div className="ov-risk-row"><span>VaR (95%)</span><strong>${(riskMetrics.var_95 ?? 0).toLocaleString()}</strong></div>
                </>
              ) : (
                <div className="empty-state">Loading risk metrics…</div>
              )}
              {(riskMetrics?.concentration_risk ?? []).length > 0 && (
                <div className="ov-concentration">
                  <span className="section-label">Concentration</span>
                  {riskMetrics!.concentration_risk!.slice(0, 4).map((row) => (
                    <div key={row.symbol} className="ov-conc-row">
                      <span>{row.symbol}</span>
                      <div className="ov-conc-bar">
                        <div style={{ width: `${Math.min(100, row.pct * 4)}%` }} />
                      </div>
                      <span>{row.pct.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="ov-risk-check">
              <span className="section-label">Risk checklist</span>
              {checklist.map((item) => (
                <div key={item.label} className="ov-check-row" title={item.note}>
                  <span className={`ov-check-dot ${item.ok ? "ok" : "warn"}`} aria-hidden="true" />
                  <span className="ov-check-label">{item.label}</span>
                  <span className={`ov-check-status ${item.ok ? "ok" : "warn"}`}>{item.ok ? "OK" : "Monitor"}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {/* Watchlist */}
        <Card title="Watchlist" extra={watchLoading ? <span className="ov-muted">Updating…</span> : undefined}>
          <Tabs tabs={WATCH_TABS.map((t) => t.id)} active={watchTab} onSelect={setWatchTab} />
          <div className="ov-table-wrap">
            <table className="ov-table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Price</th>
                  <th>1D</th>
                  <th>YTD</th>
                </tr>
              </thead>
              <tbody>
                {(WATCH_TABS.find((t) => t.id === watchTab)?.symbols ?? []).map(({ symbol, label }) => {
                  const row = watchRows[symbol];
                  const quote = row?.quote;
                  return (
                    <tr key={symbol} onClick={() => pickSymbol(symbol)}>
                      <td>{label}</td>
                      <td>{quote ? quote.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</td>
                      <td className={(quote?.change_pct ?? 0) >= 0 ? "up" : "down"}>{quote ? pct(quote.change_pct) : "—"}</td>
                      <td className={(row?.ytd ?? 0) >= 0 ? "up" : "down"}>{row?.ytd !== undefined ? pct(row.ytd, 1) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Heat map */}
        <Card title="Market Heat Map" className="ov-heat-card">
          <div className="ov-heat">
            {SECTORS.map((sector) => (
              <div key={sector.name} className="ov-heat-sector">
                <span className="ov-heat-name">{sector.name}</span>
                <div className="ov-heat-cells">
                  {sector.symbols.map((symbol) => {
                    const quote = basket.find((q) => q.symbol === symbol);
                    const change = quote?.change_pct ?? 0;
                    // Green/red intensity scaled to ±3% daily move.
                    const strength = Math.min(Math.abs(change) / 3, 1);
                    const background =
                      change >= 0
                        ? `rgba(34, 197, 94, ${(0.14 + strength * 0.55).toFixed(2)})`
                        : `rgba(239, 68, 68, ${(0.14 + strength * 0.55).toFixed(2)})`;
                    return (
                      <button
                        key={symbol}
                        type="button"
                        className="ov-heat-cell"
                        style={{ background }}
                        onClick={() => pickSymbol(symbol)}
                        title={`${symbol}: ${pct(change)}`}
                      >
                        <strong>{symbol.replace("-USD", "")}</strong>
                        <span>{quote ? pct(change, 2) : "—"}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Full-page scrollable news (same overlay the inspector opens) */}
      <NewsPage open={newsOpen} onClose={() => setNewsOpen(false)} />
    </div>
  );
}
