import { useEffect, useState, useCallback } from "react";

import { API_BASE } from "../../lib/constants";

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

const EMPTY_STATE_MESSAGES: Record<string, string> = {
  overview: "Select a view to see contextual information",
  scanner: "Select a symbol from the scanner to inspect",
  markets: "Select a symbol to view market details",
  calendar: "Upcoming economic events will appear here",
  strategies: "Select or create a strategy to see details",
  backtests: "Select a backtest run to see results",
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
  const [loading, setLoading] = useState(false);

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
              news.slice(0, 5).map((item) => (
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
            <h3 className="section-label">Paper Order Preview</h3>
            <div className="order-preview-content">
              <div className="preview-row">
                <span>{selectedSymbol}</span>
                <span className="side-badge buy">Buy</span>
                <span>10</span>
              </div>
              <p className="preview-note">
                Estimated notional {formatPrice(currentPrice * 10)} — risk checks run server-side when the
                order is submitted from the paper desk.
              </p>
            </div>
          </section>
        )}
      </div>

      {loading && (
        <div className="inspector-loading" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.3)", zIndex: 10 }}>
          <div className="spinner" style={{ width: 24, height: 24, border: "2px solid var(--border-secondary)", borderTopColor: "var(--accent-primary)", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}
    </div>
  );
}