import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../context/AuthContext";
import { useHistory } from "../../hooks/useHistory";
import { API_BASE } from "../../lib/constants";
import type { HistoryCandle } from "../../types/market";

/* §5.3 simulated order book (FR-L1..L6): a horizontal histogram, price on the
   vertical axis with the mid as the reference line, bid size extending left and
   ask size extending right, stacked by the archetype that placed the quote.

   The price context — mid, recent and lookback returns, lookback volatility —
   is derived from the chart's selected symbol and its last daily bars, so the
   ladder is never fed by hand-entered prices. */

interface Contribution {
  archetype: string;
  size: number;
  share: number;
  agents: number;
}

interface BookLevel {
  price: number;
  side: "bid" | "ask";
  size: number;
  share_of_side: number;
  contributions: Contribution[];
}

interface OrderBook {
  simulated: boolean;
  label: string;
  engine_version: string;
  mid: number;
  seed: number;
  agents: number;
  levels: BookLevel[];
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  spread_ticks: number | null;
  levels_per_side: { bid: number; ask: number };
  levels_truncated: { bid: number; ask: number };
  total_size: number;
  visible_size: number;
  dropped_size: number;
  size_by_archetype: Record<string, number>;
  weights: Record<string, number>;
  parameters: Record<string, number>;
  output_hash: string;
}

interface BookContext {
  mid: number;
  recent_return: number;
  lookback_return: number;
  lookback_volatility: number;
  as_of: string | null;
  bars: number;
  lookbackWindow: number;
}

const ARCHETYPES = ["market_maker", "momentum", "noise", "large_passive"] as const;
const ARCHETYPE_LABEL: Record<string, string> = {
  market_maker: "Market maker",
  momentum: "Momentum",
  noise: "Noise",
  large_passive: "Large passive",
};
const DISPLAY_DEPTH = 25;
const CONTEXT_BARS = 60;
const LOOKBACK_BARS = 20;

const fmt = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

const pct = (value: number, digits = 2) => `${(value * 100).toFixed(digits)}%`;

/** Mid, recent return, lookback return and volatility from the latest bars. */
export function buildBookContext(rows: HistoryCandle[]): BookContext | null {
  const usable = rows.filter(
    (bar) => Number.isFinite(bar.close) && bar.close > 0 && Number.isFinite(bar.time),
  );
  if (usable.length < 2) return null;
  const closes = usable.map((bar) => bar.close);
  const last = closes.at(-1);
  const previous = closes.at(-2);
  const lastBar = usable.at(-1);
  if (last === undefined || previous === undefined || lastBar === undefined) return null;
  const windowStart = Math.max(0, closes.length - 1 - LOOKBACK_BARS);
  const window = closes.slice(windowStart);
  const windowFirst = window[0];
  if (windowFirst === undefined) return null;
  const returns: number[] = [];
  for (let index = 1; index < window.length; index += 1) {
    const current = window[index];
    const prior = window[index - 1];
    if (current === undefined || prior === undefined) continue;
    returns.push(current / prior - 1);
  }
  const mean = returns.reduce((sum, value) => sum + value, 0) / Math.max(1, returns.length);
  const variance =
    returns.length > 1
      ? returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1)
      : 0;
  const sd = Math.sqrt(variance);
  return {
    mid: last,
    recent_return: last / previous - 1,
    lookback_return: last / windowFirst - 1,
    // The engine needs a positive volatility; a flat series falls back to 1%.
    lookback_volatility: sd > 1e-9 ? sd : 0.01,
    as_of: new Date(lastBar.time * 1000).toISOString().slice(0, 10),
    bars: usable.length,
    lookbackWindow: window.length - 1,
  };
}

export function OrderBookPanel({ symbol }: { symbol: string }) {
  const { token } = useAuth();
  const { data, loading: historyLoading, error: historyError, retry } = useHistory(
    symbol,
    "1d",
    CONTEXT_BARS,
  );
  const [controls, setControls] = useState({ agents: "500", seed: "7", inventory: "0" });
  const [book, setBook] = useState<OrderBook | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const context = useMemo(() => buildBookContext(data), [data]);

  const run = useCallback(
    async (ctx: BookContext) => {
      setLoading(true);
      setError(null);
      try {
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (token) headers.Authorization = `Bearer ${token}`;
        const response = await fetch(`${API_BASE}/quant/orderbook/simulate`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            mid: ctx.mid,
            recent_return: ctx.recent_return,
            lookback_return: ctx.lookback_return,
            lookback_volatility: ctx.lookback_volatility,
            agents: Math.round(Number(controls.agents)),
            seed: Math.round(Number(controls.seed)),
            inventory: Number(controls.inventory),
          }),
        });
        const payload = (await response.json()) as OrderBook & {
          detail?: { field?: string; message?: string };
        };
        if (!response.ok) {
          const detail = payload.detail;
          throw new Error(
            detail?.field
              ? `${detail.field}: ${detail.message ?? "invalid value"}`
              : (detail?.message ?? `Simulation failed (${response.status})`),
          );
        }
        setBook(payload);
        setSelected(null);
      } catch (err) {
        setBook(null);
        setError(err instanceof Error ? err.message : "Simulation failed");
      } finally {
        setLoading(false);
      }
    },
    [controls.agents, controls.seed, controls.inventory, token],
  );

  // A new symbol invalidates the old ladder immediately.
  useEffect(() => {
    setBook(null);
    setSelected(null);
    setError(null);
  }, [symbol]);

  // Re-simulate whenever the bar-derived context changes (symbol, refreshed bars).
  useEffect(() => {
    if (context) void run(context);
    // `run` is intentionally not a dependency: control edits should not auto-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, token]);

  const rows = useMemo(() => {
    if (!book) return [] as BookLevel[];
    const bids = book.levels.filter((level) => level.side === "bid").slice(0, DISPLAY_DEPTH);
    const asks = book.levels.filter((level) => level.side === "ask").slice(0, DISPLAY_DEPTH);
    // Highest ask at the top, walking down into the mid, then the best bid.
    return [...asks.slice().reverse(), ...bids];
  }, [book]);

  const maxSize = Math.max(1, ...rows.map((row) => row.size));
  const selectedLevel = book?.levels.find((level) => `${level.side}:${level.price}` === selected) ?? null;
  const update = (key: keyof typeof controls, value: string) =>
    setControls((current) => ({ ...current, [key]: value }));

  return (
    <div className="report-section mc-panel">
      <p className="ob-label">
        <strong>Simulated liquidity — not exchange data.</strong> Every price and size below comes
        from seeded agent quotes, not from an exchange, broker or order-book feed.
      </p>

      {historyError ? (
        <p className="report-note">
          {symbol.toUpperCase()} daily bars are unavailable ({historyError}). The ladder needs a last close.{" "}
          <button type="button" className="btn-secondary" onClick={retry}>
            Retry
          </button>
        </p>
      ) : context ? (
        <dl className="report-defs">
          {(
            [
              ["Symbol", symbol.toUpperCase()],
              ["Last daily close", fmt(context.mid)],
              ["Bar date", context.as_of ?? "—"],
              ["Recent return (1 bar)", pct(context.recent_return)],
              [`Lookback return (${context.lookbackWindow} bars)`, pct(context.lookback_return)],
              [`Lookback volatility (${context.lookbackWindow} bars)`, pct(context.lookback_volatility)],
            ] as [string, string][]
          ).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="report-note">
          {historyLoading
            ? `Loading ${symbol.toUpperCase()} daily bars…`
            : `No usable daily bars for ${symbol.toUpperCase()}; the ladder needs a last close.`}
        </p>
      )}

      <div className="mc-controls">
        <label>
          Agents
          <input
            value={controls.agents}
            onChange={(event) => update("agents", event.target.value)}
            inputMode="numeric"
          />
        </label>
        <label>
          Seed
          <input
            value={controls.seed}
            onChange={(event) => update("seed", event.target.value)}
            inputMode="numeric"
          />
        </label>
        <label>
          MM inventory
          <input
            value={controls.inventory}
            onChange={(event) => update("inventory", event.target.value)}
            inputMode="decimal"
          />
        </label>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => context && void run(context)}
          disabled={loading || !context}
        >
          {loading ? "Simulating…" : "Simulate"}
        </button>
      </div>

      {error && <p className="report-error-text">{error}</p>}

      {book && (
        <>
          <div className="ob-summary">
            <span>
              <small>Mid</small> <strong>{fmt(book.mid)}</strong>
            </span>
            <span>
              <small>Best bid</small> <strong>{fmt(book.best_bid)}</strong>
            </span>
            <span>
              <small>Best ask</small> <strong>{fmt(book.best_ask)}</strong>
            </span>
            <span>
              <small>Spread</small> <strong>{book.spread_ticks === null ? "—" : `${book.spread_ticks} ticks`}</strong>
            </span>
            <span>
              <small>Agents · seed</small>{" "}
              <strong>
                {book.agents.toLocaleString()} · {book.seed}
              </strong>
            </span>
            <span>
              <small>Levels (bid / ask)</small>{" "}
              <strong>
                {book.levels_per_side.bid} / {book.levels_per_side.ask}
              </strong>
            </span>
          </div>

          <div className="ob-legend" aria-label="Archetype legend">
            {ARCHETYPES.map((archetype) => (
              <span key={archetype} className="ob-legend-item">
                <span className={`ob-swatch ob-${archetype}`} aria-hidden="true" />
                {ARCHETYPE_LABEL[archetype]}
                <small>{Math.round((book.weights[archetype] ?? 0) * 100)}%</small>
              </span>
            ))}
          </div>

          <div className="ob-ladder" role="list" aria-label="Simulated bid and ask ladder, price descending">
            <div className="ob-ruler">
              <span>bid size</span>
              <span>price</span>
              <span>ask size</span>
            </div>
            {rows.map((level) => {
              const key = `${level.side}:${level.price}`;
              const breakdown = level.contributions
                .map(
                  (segment) =>
                    `${ARCHETYPE_LABEL[segment.archetype] ?? segment.archetype} ${fmt(segment.size, 0)} (${segment.agents} agents)`,
                )
                .join(", ");
              return (
                <button
                  key={key}
                  type="button"
                  role="listitem"
                  className={`ob-row ${level.side}${selected === key ? " selected" : ""}`}
                  onClick={() => setSelected(selected === key ? null : key)}
                  title={`${level.side} ${fmt(level.price)} · size ${fmt(level.size, 0)} (${(level.share_of_side * 100).toFixed(1)}% of side) · ${breakdown}`}
                  aria-label={`${level.side} ${fmt(level.price)}, size ${fmt(level.size, 0)}, ${breakdown}`}
                >
                  <span className="ob-side bid">
                    {level.side === "bid" && (
                      <span className="ob-bar" style={{ width: `${(level.size / maxSize) * 100}%` }}>
                        {level.contributions.map((segment) => (
                          <span
                            key={segment.archetype}
                            className={`ob-seg ob-${segment.archetype}`}
                            style={{ width: `${segment.share * 100}%` }}
                          />
                        ))}
                      </span>
                    )}
                  </span>
                  <span className="ob-price">{fmt(level.price)}</span>
                  <span className="ob-axis" aria-hidden="true" />
                  <span className="ob-side ask">
                    {level.side === "ask" && (
                      <span className="ob-bar" style={{ width: `${(level.size / maxSize) * 100}%` }}>
                        {level.contributions.map((segment) => (
                          <span
                            key={segment.archetype}
                            className={`ob-seg ob-${segment.archetype}`}
                            style={{ width: `${segment.share * 100}%` }}
                          />
                        ))}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
          <p className="report-axis">
            Showing the {DISPLAY_DEPTH} nearest levels each side of {book.levels_per_side.bid + book.levels_per_side.ask}{" "}
            total. Click a level for its derivation.
          </p>

          {selectedLevel && (
            <div className="ob-detail">
              <h3>
                {selectedLevel.side === "bid" ? "Bid" : "Ask"} {fmt(selectedLevel.price)}
              </h3>
              <p>
                Size {fmt(selectedLevel.size, 2)} · {((selectedLevel.share_of_side ?? 0) * 100).toFixed(2)}% of
                that side · seed {book.seed} · engine {book.engine_version}
              </p>
              <table className="report-table">
                <caption>Who is behind this level</caption>
                <thead>
                  <tr>
                    <th scope="col">Archetype</th>
                    <th scope="col">Size</th>
                    <th scope="col">Share of level</th>
                    <th scope="col">Agents</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedLevel.contributions.map((segment) => (
                    <tr key={segment.archetype}>
                      <th scope="row">{ARCHETYPE_LABEL[segment.archetype] ?? segment.archetype}</th>
                      <td>{fmt(segment.size, 2)}</td>
                      <td>{(segment.share * 100).toFixed(2)}%</td>
                      <td>{segment.agents}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details className="report-spec">
                <summary>Simulation parameters</summary>
                <pre>{JSON.stringify({ parameters: book.parameters, weights: book.weights, seed: book.seed, agents: book.agents, output_hash: book.output_hash }, null, 2)}</pre>
              </details>
            </div>
          )}
        </>
      )}
    </div>
  );
}
