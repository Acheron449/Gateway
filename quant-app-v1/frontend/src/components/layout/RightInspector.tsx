import { useEffect, useState, useCallback, useMemo } from "react";

import { API_BASE } from "../../lib/constants";
import { NewsPage } from "../../components/features/NewsPage";

interface RightInspectorProps {
  activeView: string;
  selectedSymbol: string;
  /** Compact rail mode (drag handle collapsed the panel). */
  collapsed: boolean;
}

interface QuoteData {
  instrument: string;
  last_price?: number;
  bid?: number;
  ask?: number;
  change?: number;
  change_pct?: number;
  provenance?: {
    source?: string;
    provider_version?: string;
    fetched_at?: string;
    data_time?: string;
    delay_seconds?: number;
  };
}

interface AnalysisData {
  ticker?: string;
  direction?: string;
  overall_confidence?: number;
  signals?: unknown[];
  price?: number;
  rsi?: number;
}

interface InstrumentData {
  symbol: string;
  name?: string;
  exchange?: string;
  instrument_type?: string;
  description?: string;
  provenance?: {
    source?: string;
    provider_version?: string;
    data_time?: string;
  };
}

interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CalendarEvent {
  id: string;
  title: string;
  scheduled_at: string;
  importance: string;
  currency: string;
}

interface InspectorNewsItem {
  id: string;
  headline: string;
  url?: string;
  source: string;
  published_at: string;
  related_symbols?: string[];
}

interface PaperPosition {
  instrument_id: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
}

const EMPTY_STATE_MESSAGES: Record<string, string> = {
  overview: "Select a view to see contextual information",
  scanner: "Select a symbol from the scanner to inspect",
  markets: "Select a symbol to view market details",
  calendar: "Upcoming economic events will appear here",
  strategies: "Select or create a strategy to see details",
  "paper-trading": "Place simulated orders from the paper desk",
  journal: "Select a trade to review",
};

function formatPrice(price: number | undefined): string {
  if (price === undefined || price === null) return "$0.00";
  return `$${price.toFixed(2)}`;
}

function formatChange(change: number | undefined): { value: string; className: string } {
  if (change === undefined || change === null) return { value: "0.00%", className: "neutral" };
  const isPositive = change >= 0;
  return {
    value: `${isPositive ? "+" : ""}${change.toFixed(2)}%`,
    className: isPositive ? "positive" : "negative",
  };
}

function formatProvenance(provenance?: QuoteData["provenance"]): string[] {
  if (!provenance) return ["Source: —", "Fetched: —", "Data Time: —", "Delay: —"];
  return [
    `Source: ${provenance.source ?? "—"}`,
    `Fetched: ${provenance.fetched_at ? new Date(provenance.fetched_at).toLocaleString() : "—"}`,
    `Data Time: ${provenance.data_time ? new Date(provenance.data_time).toLocaleString() : "—"}`,
    `Delay: ${provenance.delay_seconds !== undefined ? `${provenance.delay_seconds}s` : "—"}`,
  ];
}

export function RightInspector({ activeView, selectedSymbol, collapsed }: RightInspectorProps) {
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [instrument, setInstrument] = useState<InstrumentData | null>(null);
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [news, setNews] = useState<InspectorNewsItem[]>([]);
  const [position, setPosition] = useState<PaperPosition | null>(null);
  const [loading, setLoading] = useState(false);
  // Full-page news overlay (the panel itself only previews what fits).
  const [newsPageOpen, setNewsPageOpen] = useState(false);

  const fetchData = useCallback(async () => {
    const sym = selectedSymbol?.trim()?.toUpperCase();
    if (!sym) return;

    setLoading(true);

    try {
      // Fetch quote, analysis, instrument, history, calendar, and news in parallel
      const [quoteRes, analysisRes, instrumentRes, historyRes, calendarRes, newsRes] = await Promise.allSettled([
        fetch(`${API_BASE}/quote/${encodeURIComponent(sym)}`),
        fetch(`${API_BASE}/analysis/${encodeURIComponent(sym)}`),
        fetch(`${API_BASE}/stocks/${encodeURIComponent(sym)}/metadata`),
        fetch(`${API_BASE}/history/${encodeURIComponent(sym)}?tf=1h&limit=50`),
        fetch(`${API_BASE}/news/calendar?limit=50`),
        fetch(`${API_BASE}/news?symbol=${encodeURIComponent(sym)}&limit=6`),
      ]);

      if (quoteRes.status === "fulfilled" && quoteRes.value.ok) {
        setQuote(await quoteRes.value.json());
      }
      if (analysisRes.status === "fulfilled" && analysisRes.value.ok) {
        setAnalysis(await analysisRes.value.json());
      }
      if (instrumentRes.status === "fulfilled" && instrumentRes.value.ok) {
        setInstrument(await instrumentRes.value.json());
      }
      if (historyRes.status === "fulfilled" && historyRes.value.ok) {
        const candles = await historyRes.value.json();
        setCandles(candles);
      }
      if (calendarRes.status === "fulfilled" && calendarRes.value.ok) {
        const payload = await calendarRes.value.json();
        setEvents(Array.isArray(payload.events) ? payload.events : []);
      }
      if (newsRes.status === "fulfilled" && newsRes.value.ok) {
        const payload = await newsRes.value.json();
        const items = Array.isArray(payload.items) ? payload.items : [];
        setNews(
          items.map((item: Record<string, unknown>) => ({
            id: String(item.id ?? ""),
            headline: String(item.headline ?? ""),
            url: typeof item.url === "string" ? item.url : undefined,
            source: String(item.source ?? "—"),
            published_at: String(item.published_at ?? ""),
            related_symbols: Array.isArray(item.related_symbols) ? (item.related_symbols as string[]) : [],
          })),
        );
      }
    } catch (err) {
      console.error("Failed to load inspector data:", err);
    } finally {
      setLoading(false);
    }
  }, [selectedSymbol]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Open paper position for the selected symbol (paper desk view only).
  useEffect(() => {
    if (activeView !== "paper-trading") {
      setPosition(null);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const token = localStorage.getItem("gateway_auth_token");
        const res = await fetch(`${API_BASE}/portfolio`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) return;
        const data = (await res.json()) as { positions?: PaperPosition[] };
        const found = (data.positions ?? []).find(
          (p) => p.instrument_id === selectedSymbol,
        );
        if (!cancelled) setPosition(found ?? null);
      } catch {
        /* inspector decoration */
      }
    };
    void load();
    const id = window.setInterval(load, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeView, selectedSymbol]);

  // Volatility & risk of the selected symbol (relocated from the old Risk
  // dashboard) — realized volatility annualised from the loaded candles.
  const riskStats = useMemo(() => {
    const closes = candles.map((c) => c.close).filter((v) => Number.isFinite(v) && v > 0);
    if (closes.length < 5) return null;
    const returns: number[] = [];
    for (let i = 1; i < closes.length; i++) {
      const curr = closes[i];
      const prev = closes[i - 1];
      if (curr !== undefined && prev !== undefined && prev > 0) returns.push(curr / prev - 1);
    }
    if (returns.length < 4) return null;
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, returns.length - 1);
    const std = Math.sqrt(variance);
    // Loaded candles are 1h bars → ~24 sessions × 252 days per year.
    const annualized = std * Math.sqrt(24 * 252) * 100;
    const level = annualized >= 60 ? "High" : annualized >= 30 ? "Medium" : "Low";
    return { annualized, level };
  }, [candles]);

  if (collapsed) {
    const change = quote?.change_pct;
    const up = change === undefined || change === null ? null : change >= 0;
    return (
      <aside className="inspector-rail" aria-label="Inspector rail">
        <div className="rail-divider" aria-hidden="true" />
        <button
          className={`rail-icon ${activeView === "markets" ? "active" : ""}`}
          title={`Inspector — ${selectedSymbol}`}
          aria-label={`Inspector — ${selectedSymbol}`}
          onClick={() => window.dispatchEvent(new CustomEvent("inspector-expand"))}
        >
          <span className="rail-symbol">{selectedSymbol.slice(0, 2)}</span>
        </button>
        {up !== null && (
          <span className={`rail-trend ${up ? "up" : "down"}`} aria-hidden="true">
            {up ? "▲" : "▼"}
          </span>
        )}
      </aside>
    );
  }

  if (!selectedSymbol) {
    return (
      <div className="inspector-empty">
        <div className="empty-icon">📋</div>
        <p className="empty-message">{EMPTY_STATE_MESSAGES[activeView] || EMPTY_STATE_MESSAGES.overview}</p>
      </div>
    );
  }

  // Compute latest price and change from candles
  const latestCandle = candles[candles.length - 1];
  const prevCandle = candles[candles.length - 2];
  const currentPrice = quote?.last_price ?? latestCandle?.close ?? 0;
  const priceChange = quote?.change_pct ?? (prevCandle && currentPrice ? ((currentPrice - prevCandle.close) / prevCandle.close) * 100 : 0);

  const provenanceLines = formatProvenance(quote?.provenance);

  // Signal calculations
  const technicalSignal = analysis?.direction === "bullish" ? 1 : analysis?.direction === "bearish" ? -1 : 0;
  const technicalConfidence = analysis?.overall_confidence ?? 0;
  const rsiValue = analysis?.rsi ?? 50;
  const sentimentSignal = rsiValue > 70 ? -1 : rsiValue < 30 ? 1 : 0;

  return (
    <div className="inspector-content">
      <div className="inspector-header">
        <h2 className="inspector-title">{selectedSymbol}</h2>
        <span className="inspector-subtitle">{instrument?.name ? `${instrument.name} · ${activeView}` : `${activeView} inspector`}</span>
      </div>

      <div className="inspector-sections">
        <section className="inspector-section">
          <h3 className="section-label">Price & Change</h3>
          <div className="price-display">
            <span className="price-value">{formatPrice(currentPrice)}</span>
            <span className={`price-change ${formatChange(priceChange).className}`}>{formatChange(priceChange).value}</span>
          </div>
          <div className="price-meta">
            <span>Bid: {formatPrice(quote?.bid)}</span>
            <span>Ask: {formatPrice(quote?.ask)}</span>
            <span>Spread: {quote?.bid && quote?.ask ? ((quote.ask - quote.bid) / quote.bid * 100).toFixed(2) + "%" : "—"}</span>
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Key Metrics</h3>
          <dl className="metrics-grid">
            <div><dt>Volume</dt><dd>{candles.length > 0 ? candles[candles.length - 1]?.volume?.toLocaleString() ?? "—" : "—"}</dd></div>
            <div><dt>Avg Volume</dt><dd>—</dd></div>
            <div><dt>Market Cap</dt><dd>—</dd></div>
            <div><dt>P/E Ratio</dt><dd>—</dd></div>
            <div><dt>52W High</dt><dd>{candles.length > 0 ? formatPrice(Math.max(...candles.map(c => c.high))) : "—"}</dd></div>
            <div><dt>52W Low</dt><dd>{candles.length > 0 ? formatPrice(Math.min(...candles.map(c => c.low))) : "—"}</dd></div>
          </dl>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Volatility &amp; Risk</h3>
          {riskStats ? (
            <div className="risk-stat-block">
              <div className="risk-stat-row">
                <span>Annualised volatility</span>
                <strong>{riskStats.annualized.toFixed(1)}%</strong>
              </div>
              <div className="risk-stat-row">
                <span>Risk level</span>
                <strong className={`risk-level ${riskStats.level.toLowerCase()}`}>{riskStats.level}</strong>
              </div>
              {typeof analysis?.rsi === "number" && (
                <div className="risk-stat-row">
                  <span>RSI(14)</span>
                  <strong>{analysis.rsi.toFixed(1)}</strong>
                </div>
              )}
              {analysis?.direction && (
                <div className="risk-stat-row">
                  <span>Signal</span>
                  <strong>{analysis.direction}</strong>
                </div>
              )}
            </div>
          ) : (
            <div className="risk-stat-empty">Not enough price history to size risk yet.</div>
          )}
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Next Events</h3>
          <div className="events-list">
            {events.length > 0 ? (
              events.slice(0, 5).map((event) => (
                <div className="event-item" key={event.id}>
                  <span className="event-time">{new Date(event.scheduled_at).toLocaleString()}</span>
                  <span className="event-title">{event.title}</span>
                  <span className={`event-importance ${event.importance || "medium"}`}>
                    {event.currency} · {event.importance || "medium"}
                  </span>
                </div>
              ))
            ) : (
              <div className="event-item">
                <span className="event-time">Unavailable</span>
                <span className="event-title">No calendar events returned</span>
                <span className="event-importance low">Provider may be unconfigured</span>
              </div>
            )}
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Latest News</h3>
          <div className="inspector-news">
            {news.length > 0 ? (
              // Preview only — the section is height-constrained, so show the
              // first 4 and open the scrollable NewsPage for the full feed.
              news.slice(0, 4).map((item) => (
                <a
                  key={item.id || item.headline}
                  className="inspector-news-item"
                  href={item.url || "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={item.headline}
                >
                  <span className="inspector-news-headline">{item.headline}</span>
                  <span className="inspector-news-meta">
                    {item.source}
                    {item.published_at ? ` · ${new Date(item.published_at).toLocaleDateString()}` : ""}
                  </span>
                </a>
              ))
            ) : (
              <p className="inspector-news-empty">No recent headlines for {selectedSymbol}</p>
            )}
            {news.length > 0 && (
              <button type="button" className="news-view-all" onClick={() => setNewsPageOpen(true)}>
                View all news →
              </button>
            )}
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Signals & Confidence</h3>
          <div className="signal-display">
            <div className="signal-bar">
              <span className="signal-label">Overall</span>
              <div className="signal-progress">
                <div className={`signal-fill ${technicalSignal > 0 ? "bullish" : technicalSignal < 0 ? "bearish" : "neutral"}`} style={{ width: `${Math.abs(technicalSignal) * 100 || 50}%` }}></div>
              </div>
              <span className="signal-value">{Math.round(Math.abs(technicalSignal) * 100 || 50)}%</span>
            </div>
            <div className="signal-bar">
              <span className="signal-label">Technical</span>
              <div className="signal-progress">
                <div className={`signal-fill ${technicalSignal > 0 ? "bullish" : technicalSignal < 0 ? "bearish" : "neutral"}`} style={{ width: `${technicalConfidence * 100}%` }}></div>
              </div>
              <span className="signal-value">{Math.round(technicalConfidence * 100)}%</span>
            </div>
            <div className="signal-bar">
              <span className="signal-label">Sentiment (RSI)</span>
              <div className="signal-progress">
                <div className={`signal-fill ${sentimentSignal > 0 ? "bullish" : sentimentSignal < 0 ? "bearish" : "neutral"}`} style={{ width: `${sentimentSignal !== 0 ? 80 : 50}%` }}></div>
              </div>
              <span className="signal-value">RSI: {rsiValue?.toFixed(1) ?? "—"}</span>
            </div>
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Risk / Provenance</h3>
          <div className="provenance-info">
            {provenanceLines.map((line, i) => (
              <p key={i} className="provenance-item">{line}</p>
            ))}
          </div>
        </section>

        {activeView === "paper-trading" && (
          <section className="inspector-section order-preview">
            <h3 className="section-label">Open Position</h3>
            <div className="order-preview-content">
              {position ? (
                <>
                  <div className="preview-row">
                    <span>{selectedSymbol}</span>
                    <span className={`side-badge ${position.quantity >= 0 ? "buy" : "sell"}`}>
                      {position.quantity >= 0 ? "Long" : "Short"}
                    </span>
                    <span>{Math.abs(position.quantity)}</span>
                  </div>
                  <p className="preview-note">
                    Avg cost {formatPrice(position.avg_cost)} · market value{" "}
                    {formatPrice(position.market_value)} · unrealized PnL{" "}
                    <span className={position.unrealized_pnl >= 0 ? "positive" : "negative"}>
                      {position.unrealized_pnl >= 0 ? "+" : ""}
                      {formatPrice(position.unrealized_pnl)}
                    </span>
                  </p>
                </>
              ) : (
                <>
                  <div className="preview-row">
                    <span>{selectedSymbol}</span>
                    <span className="side-badge buy">Buy</span>
                    <span>10</span>
                  </div>
                  <p className="preview-note">
                    No open position in {selectedSymbol}. Estimated notional{" "}
                    {formatPrice(currentPrice * 10)} — risk checks run server-side when the order is
                    submitted from the paper desk.
                  </p>
                </>
              )}
            </div>
          </section>
        )}
      </div>

      {loading && (
        <div className="inspector-loading" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.3)", zIndex: 10 }}>
          <div className="spinner" style={{ width: 24, height: 24, border: "2px solid var(--border-secondary)", borderTopColor: "var(--accent-primary)", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}

      {/* Big scrollable news page for the full feed beyond the 4-item preview */}
      <NewsPage open={newsPageOpen} onClose={() => setNewsPageOpen(false)} symbol={selectedSymbol} />
    </div>
  );
}