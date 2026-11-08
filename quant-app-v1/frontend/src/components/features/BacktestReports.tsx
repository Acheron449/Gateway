import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";
import { BacktestLauncher } from "./BacktestLauncher";
import { MonteCarloComparison } from "./MonteCarloComparison";
import { MonteCarloPanel } from "./MonteCarloPanel";

/* The P4 run report: equity + drawdown, metrics, trades, receipt, CSV and a
   side-by-side comparison. Every figure on screen comes from the stored run
   payload; the receipt is one click away and always shows the data hash. */

type MetricValue = number | string | boolean | null | undefined;

interface Metrics {
  [key: string]: MetricValue;
}

interface EquityPoint {
  time: string;
  equity: number;
}

interface Trade {
  side: string;
  qty: number;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  commission: number;
  notional: number;
  bars_held: number;
  exit_reason: string;
}

interface Receipt {
  engine_version?: string;
  symbol?: string;
  timeframe?: string;
  window?: { start?: string; end?: string };
  bars?: number;
  data_hash?: string;
  spec_hash?: string;
  seed?: number;
  initial_capital?: number;
  oos_ratio?: number;
  created_at?: string;
  costs?: Record<string, number>;
  spec?: Record<string, unknown>;
}

interface OosBlock {
  evaluated: boolean;
  reason?: string;
  ratio?: number;
  split_time?: string;
  metrics?: Metrics;
  trades?: number;
}

interface RunResult {
  equity_curve?: EquityPoint[];
  trades?: Trade[];
  is_metrics?: Metrics;
  oos?: OosBlock;
  metrics?: Metrics;
  engine_version?: string;
  data_hash?: string;
}

interface RunSummary {
  run_id: string;
  status: string;
  symbol: string | null;
  timeframe: string | null;
  data_hash: string;
  created_at: string;
  metrics: Metrics | null;
}

interface RunDetail {
  run_id: string;
  status: string;
  created_at: string;
  receipt: Receipt;
  metrics: Metrics;
  result: RunResult | null;
}

interface CompareBlock {
  run_id: string;
  receipt: Receipt;
  metrics: Metrics;
}

interface CompareResponse {
  left: CompareBlock;
  right: CompareBlock;
  deltas: Record<string, number | { left: MetricValue; right: MetricValue }>;
}

type Tab = "summary" | "trades" | "receipt" | "monte-carlo";

type MetricFormat = "money" | "pct" | "pctPlain" | "number";

/** `negate` marks magnitudes stored as positive that read negative to a trader (drawdown). */
const METRIC_ROWS: { key: string; label: string; format: MetricFormat; negate?: boolean }[] = [
  { key: "net_pnl", label: "Net P&L", format: "money" },
  { key: "total_return_pct", label: "Total return", format: "pct" },
  { key: "max_drawdown_pct", label: "Max drawdown", format: "pctPlain", negate: true },
  { key: "sharpe", label: "Sharpe", format: "number" },
  { key: "sortino", label: "Sortino", format: "number" },
  { key: "hit_rate", label: "Hit rate", format: "pctPlain" },
  { key: "profit_factor", label: "Profit factor", format: "number" },
  { key: "expectancy", label: "Expectancy / trade", format: "money" },
  { key: "exposure_pct", label: "Exposure", format: "pctPlain" },
  { key: "turnover", label: "Turnover (× capital)", format: "number" },
  { key: "trades", label: "Trades", format: "number" },
  { key: "avg_bars_held", label: "Avg bars held", format: "number" },
];

function asNumber(value: MetricValue): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function fmtMetric(value: MetricValue, format: MetricFormat, negate = false): string {
  const raw = asNumber(value);
  if (raw === null) return value === null || value === undefined ? "—" : String(value);
  const num = negate ? -raw : raw;
  if (format === "money") {
    return `${num < 0 ? "−" : ""}$${Math.abs(num).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  if (format === "pct") return `${num >= 0 ? "+" : "−"}${Math.abs(num).toFixed(2)}%`;
  if (format === "pctPlain") return `${num < 0 ? "−" : ""}${Math.abs(num).toFixed(2)}%`;
  return num.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function fmtRow(row: { format: MetricFormat; negate?: boolean }, value: MetricValue): string {
  return fmtMetric(value, row.format, row.negate);
}

/** Drawdown reads as a loss, and a smaller drawdown is the better side of a delta. */
function rowTone(row: { negate?: boolean }, value: MetricValue): string {
  const num = asNumber(value);
  if (num === null) return "";
  if (row.negate) return num > 0 ? "down" : "";
  return tone(num);
}

function deltaTone(row: { negate?: boolean }, value: number | null): string {
  if (value === null) return "";
  return tone(row.negate ? -value : value);
}

function fmtTime(iso: string | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().replace("T", " ").slice(0, 16) + "Z";
}

function tone(value: MetricValue): string {
  const num = asNumber(value);
  if (num === null) return "";
  if (num > 0) return "up";
  if (num < 0) return "down";
  return "";
}

function drawdownSeries(curve: EquityPoint[]): { time: string; drawdown: number }[] {
  let peak = -Infinity;
  return curve.map((point) => {
    peak = Math.max(peak, point.equity);
    const drawdown = peak > 0 ? ((point.equity - peak) / peak) * 100 : 0;
    return { time: point.time, drawdown };
  });
}

function LineChart({
  values,
  baseline,
  toneClass,
  label,
}: {
  values: number[];
  baseline?: number;
  toneClass: string;
  label: string;
}) {
  if (values.length < 2) {
    return <p className="report-empty">Not enough points to draw {label.toLowerCase()}.</p>;
  }
  const min = Math.min(...values, baseline ?? Infinity);
  const max = Math.max(...values, baseline ?? -Infinity);
  const span = max - min || 1;
  const width = 720;
  const height = 170;
  const x = (index: number) => (index / (values.length - 1)) * width;
  const y = (value: number) => height - ((value - min) / span) * (height - 14) - 7;
  const points = values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const baseY = baseline !== undefined ? y(baseline) : null;
  return (
    <svg className="report-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      {baseY !== null && <line x1={0} y1={baseY} x2={width} y2={baseY} className="report-chart-base" />}
      <polyline points={points} className={`report-chart-line ${toneClass}`} />
    </svg>
  );
}

function DrawdownChart({ series }: { series: { time: string; drawdown: number }[] }) {
  if (series.length < 2) {
    return <p className="report-empty">No drawdown path recorded for this run.</p>;
  }
  const width = 720;
  const height = 120;
  const worst = Math.min(...series.map((point) => point.drawdown));
  const span = Math.abs(worst) || 1;
  const points = series
    .map((point, index) => {
      const x = (index / (series.length - 1)) * width;
      const y = (Math.abs(point.drawdown) / span) * (height - 10) + 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const area = `0,0 ${points} ${width},0`;
  return (
    <svg className="report-chart report-drawdown" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Drawdown from peak equity">
      <polygon points={area} className="report-drawdown-area" />
      <polyline points={points} className="report-chart-line down" />
    </svg>
  );
}

export function BacktestReports({ selectedSymbol = "AAPL" }: { selectedSymbol?: string }) {
  const { token, isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const params = useParams();
  const deepLinkId = (params["*"] ?? "").trim();

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [tab, setTab] = useState<Tab>("summary");
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<CompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const [toolsRefresh, setToolsRefresh] = useState(0);

  const authHeaders = useMemo<Record<string, string>>(() => {
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }, [token]);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/backtest/runs`, { headers: authHeaders });
      if (response.status === 401) {
        setError("Sign in to see your backtest receipts.");
        setRuns([]);
        return;
      }
      if (!response.ok) throw new Error(`Could not load runs (${response.status})`);
      const data = (await response.json()) as { runs?: RunSummary[] };
      const list = data.runs ?? [];
      setRuns(list);
      setSelectedId((current) => current ?? list[0]?.run_id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load backtest runs");
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void loadRuns();
  }, [isAuthenticated, loadRuns]);

  useEffect(() => {
    if (deepLinkId && runs.some((run) => run.run_id === deepLinkId)) {
      setSelectedId(deepLinkId);
    }
  }, [deepLinkId, runs]);

  const loadDetail = useCallback(
    async (runId: string) => {
      setDetailLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/backtest/runs/${encodeURIComponent(runId)}`, {
          headers: authHeaders,
        });
        if (!response.ok) throw new Error(`Could not load run (${response.status})`);
        setDetail((await response.json()) as RunDetail);
      } catch (err) {
        setDetail(null);
        setError(err instanceof Error ? err.message : "Could not load this run");
      } finally {
        setDetailLoading(false);
      }
    },
    [authHeaders],
  );

  useEffect(() => {
    if (selectedId) {
      setTab("summary");
      setCopyState("idle");
      void loadDetail(selectedId);
    }
  }, [selectedId, loadDetail]);

  const equity = detail?.result?.equity_curve ?? [];
  const drawdowns = useMemo(() => drawdownSeries(equity), [equity]);
  const trades = detail?.result?.trades ?? [];
  const metrics = detail?.metrics ?? detail?.result?.metrics ?? {};
  const oos = detail?.result?.oos;
  const receipt = detail?.receipt ?? {};

  const downloadCsv = useCallback(async () => {
    if (!selectedId) return;
    setDownloadError(null);
    try {
      const response = await fetch(`${API_BASE}/backtest/runs/${encodeURIComponent(selectedId)}/csv`, {
        headers: authHeaders,
      });
      if (!response.ok) throw new Error(`CSV download failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `backtest-${selectedId}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "CSV download failed");
    }
  }, [authHeaders, selectedId]);

  const copyReceipt = useCallback(async () => {
    if (!detail) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(detail.receipt, null, 2));
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setDownloadError("Clipboard is unavailable in this browser");
    }
  }, [detail]);

  const toggleCompare = useCallback((runId: string) => {
    setComparison(null);
    setCompareIds((current) => {
      if (current.includes(runId)) return current.filter((id) => id !== runId);
      if (current.length >= 2) return current;
      return [...current, runId];
    });
  }, []);

  const runComparison = useCallback(async () => {
    if (compareIds.length !== 2) return;
    setComparing(true);
    setCompareError(null);
    try {
      const response = await fetch(`${API_BASE}/backtest/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ run_ids: compareIds }),
      });
      if (response.status === 401) {
        setCompareError("Sign in to compare runs.");
        return;
      }
      if (!response.ok) throw new Error(`Comparison failed (${response.status})`);
      setComparison((await response.json()) as CompareResponse);
    } catch (err) {
      setComparison(null);
      setCompareError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setComparing(false);
    }
  }, [authHeaders, compareIds]);

  if (!isAuthenticated) {
    return (
      <div className="canvas-view canvas-view-wide">
        <div className="view-header">
          <h1>Backtest reports</h1>
          <p className="view-description">Equity, drawdown, metrics, trades and the receipt behind every run.</p>
        </div>
        <section className="report-gate">
          <h2>Sign in to view run receipts</h2>
          <p>Runs are stored per account; the report reads only your own receipts.</p>
          <button type="button" className="btn-primary" onClick={() => openAuth("login")}>
            Sign in
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="canvas-view canvas-view-wide report-view">
      <div className="view-header report-header">
        <div>
          <h1>Backtest reports</h1>
          <p className="view-description">
            Every number below comes from a stored run receipt. Simulated on historical bars — not a forecast.
          </p>
        </div>
        <div className="report-header-actions">
          <button
            type="button"
            className={compareMode ? "btn-primary" : "btn-secondary"}
            onClick={() => {
              setCompareMode((current) => !current);
              setComparison(null);
              setCompareIds([]);
            }}
          >
            {compareMode ? "Exit compare" : "Compare two runs"}
          </button>
          <button type="button" className="btn-secondary" onClick={() => void loadRuns()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div className="report-error" role="alert">
          <span>{error}</span>
          {error.startsWith("Sign in") ? (
            <button type="button" className="btn-secondary" onClick={() => openAuth("login")}>
              Sign in
            </button>
          ) : (
            <button type="button" className="btn-secondary" onClick={() => void loadRuns()}>
              Retry
            </button>
          )}
        </div>
      )}

      <section className="report-tools" aria-label="Backtest tools">
        <BacktestLauncher
          initialSymbol={selectedSymbol}
          onComplete={async () => {
            setToolsRefresh((current) => current + 1);
            await loadRuns();
          }}
        />
        <MonteCarloComparison token={token} refreshKey={toolsRefresh} />
      </section>

      <div className="report-layout">
        <aside className="report-list" aria-label="Backtest runs">
          <div className="report-list-head">
            <h2>Runs</h2>
            <span>{runs.length} retained</span>
          </div>
          {runs.length === 0 && !loading && !error && (
            <p className="report-empty">
              No runs yet. Start a model backtest above, or use Strategy Studio / <code>POST /backtest/run</code>; receipts appear here.
            </p>
          )}
          <ul>
            {runs.map((run) => {
              const selected = !compareMode && selectedId === run.run_id;
              const checked = compareIds.includes(run.run_id);
              return (
                <li key={run.run_id}>
                  <button
                    type="button"
                    className={`report-run ${selected ? "active" : ""} ${checked ? "compared" : ""}`}
                    onClick={() => (compareMode ? toggleCompare(run.run_id) : setSelectedId(run.run_id))}
                    aria-pressed={compareMode ? checked : selected}
                  >
                    <span className="report-run-main">
                      <b>{run.symbol ?? "—"}</b>
                      <small>
                        {run.timeframe ?? "—"} · {fmtTime(run.created_at)}
                      </small>
                    </span>
                    <span className={`report-run-value ${tone(run.metrics?.net_pnl)}`}>
                      {fmtMetric(run.metrics?.net_pnl, "money")}
                    </span>
                    {compareMode && <span className="report-run-check" aria-hidden="true">{checked ? "✓" : "+"}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {compareMode && (
            <div className="report-compare-actions">
              <p>
                {compareIds.length}/2 selected. Choose two runs, then compare their metrics and receipts.
              </p>
              <button
                type="button"
                className="btn-primary"
                disabled={compareIds.length !== 2 || comparing}
                onClick={() => void runComparison()}
              >
                {comparing ? "Comparing…" : "Compare selected"}
              </button>
              {compareError && <p className="report-error-text" role="alert">{compareError}</p>}
            </div>
          )}
        </aside>

        <main className="report-main">
          {compareMode ? (
            comparison ? (
              <ComparisonTable comparison={comparison} />
            ) : (
              <section className="report-card report-placeholder">
                <h2>Side-by-side comparison</h2>
                <p>Select exactly two runs on the left to see metric deltas and both receipts side by side.</p>
              </section>
            )
          ) : detailLoading && !detail ? (
            <section className="report-card report-placeholder">Loading run…</section>
          ) : !detail ? (
            <section className="report-card report-placeholder">
              <h2>No run selected</h2>
              <p>Pick a run to see its equity curve, drawdown, metrics, trades and receipt.</p>
            </section>
          ) : (
            <>
              <section className="report-card">
                <header className="report-card-head">
                  <div>
                    <h2>
                      {receipt.symbol ?? "—"} · {receipt.timeframe ?? "—"}
                    </h2>
                    <p>
                      {receipt.bars ?? "—"} bars · {fmtTime(receipt.window?.start)} → {fmtTime(receipt.window?.end)} · engine{" "}
                      {receipt.engine_version ?? detail.result?.engine_version ?? "—"}
                    </p>
                  </div>
                  <div className="report-hero">
                    <span className={`report-hero-value ${tone(metrics.total_return_pct)}`}>
                      {fmtMetric(metrics.total_return_pct, "pct")}
                    </span>
                    <span className="report-hero-sub">{fmtMetric(metrics.net_pnl, "money")} net</span>
                  </div>
                </header>
                <nav className="report-tabs" role="tablist" aria-label="Run sections">
                  {(
                    [
                      ["summary", "Summary"],
                      ["trades", `Trades (${trades.length})`],
                      ["receipt", "Receipt"],
                      ["monte-carlo", "Monte Carlo"],
                    ] as [Tab, string][]
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      role="tab"
                      type="button"
                      aria-selected={tab === id}
                      className={tab === id ? "active" : ""}
                      onClick={() => setTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </nav>

                {tab === "summary" && (
                  <div className="report-section">
                    <div className="report-charts">
                      <figure>
                        <figcaption>Equity curve</figcaption>
                        <LineChart
                          values={equity.map((point) => point.equity)}
                          baseline={receipt.initial_capital}
                          toneClass={tone(metrics.net_pnl)}
                          label="Equity curve"
                        />
                        <p className="report-axis">
                          {fmtTime(equity[0]?.time)} → {fmtTime(equity.at(-1)?.time)} · dashed line is starting capital
                        </p>
                      </figure>
                      <figure>
                        <figcaption>Drawdown from peak</figcaption>
                        <DrawdownChart series={drawdowns} />
                        <p className="report-axis">Worst {fmtMetric(metrics.max_drawdown_pct, "pctPlain", true)} from a prior peak</p>
                      </figure>
                    </div>

                    <table className="report-table report-metrics-table">
                      <caption>Run metrics</caption>
                      <thead>
                        <tr>
                          <th scope="col">Metric</th>
                          <th scope="col">Full window</th>
                          <th scope="col">In-sample</th>
                          <th scope="col">Out-of-sample</th>
                        </tr>
                      </thead>
                      <tbody>
                        {METRIC_ROWS.map((row) => (
                          <tr key={row.key}>
                            <th scope="row">{row.label}</th>
                            <td className={rowTone(row, metrics[row.key])}>{fmtRow(row, metrics[row.key])}</td>
                            <td>{fmtRow(row, detail.result?.is_metrics?.[row.key])}</td>
                            <td>
                              {oos?.evaluated ? fmtRow(row, oos.metrics?.[row.key]) : "not evaluated"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="report-note">
                      {oos?.evaluated
                        ? `Out-of-sample starts ${fmtTime(oos.split_time)} (${Math.round((oos.ratio ?? 0) * 100)}% of bars). In-sample figures use the earlier window only.`
                        : `Out-of-sample was not evaluated: ${oos?.reason ?? "no split was recorded"}. This run reports in-sample performance only.`}
                    </p>

                    <div className="report-actions">
                      <button type="button" className="btn-secondary" onClick={() => void downloadCsv()}>
                        Download CSV
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => void copyReceipt()}>
                        {copyState === "copied" ? "Receipt copied" : "Copy receipt JSON"}
                      </button>
                      {downloadError && <span className="report-error-text">{downloadError}</span>}
                    </div>
                  </div>
                )}

                {tab === "monte-carlo" && selectedId && (
                  <MonteCarloPanel
                    runId={selectedId}
                    token={token}
                    initialCapital={receipt.initial_capital}
                    bars={receipt.bars}
                  />
                )}

                {tab === "trades" && (
                  <div className="report-section">
                    {trades.length === 0 ? (
                      <p className="report-empty">No trades were executed in this run.</p>
                    ) : (
                      <table className="report-table">
                        <caption>
                          {trades.length} simulated trade{trades.length === 1 ? "" : "s"} · fees and slippage included
                        </caption>
                        <thead>
                          <tr>
                            <th scope="col">Side</th>
                            <th scope="col">Qty</th>
                            <th scope="col">Entry</th>
                            <th scope="col">Exit</th>
                            <th scope="col">P&L</th>
                            <th scope="col">Return</th>
                            <th scope="col">Fees</th>
                            <th scope="col">Exit reason</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trades.slice(0, 200).map((trade, index) => (
                            <tr key={`${trade.entry_time}-${index}`}>
                              <td>
                                <span className={`report-side ${trade.side}`}>{trade.side}</span>
                              </td>
                              <td>{trade.qty}</td>
                              <td title={fmtTime(trade.entry_time)}>
                                {trade.entry_price} <small>{fmtTime(trade.entry_time).slice(5, 16)}</small>
                              </td>
                              <td title={fmtTime(trade.exit_time)}>
                                {trade.exit_price} <small>{fmtTime(trade.exit_time).slice(5, 16)}</small>
                              </td>
                              <td className={tone(trade.pnl)}>{fmtMetric(trade.pnl, "money")}</td>
                              <td className={tone(trade.pnl_pct)}>{fmtMetric(trade.pnl_pct, "pct")}</td>
                              <td>{fmtMetric(trade.commission, "money")}</td>
                              <td>{trade.exit_reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {trades.length > 200 && (
                      <p className="report-note">Showing the first 200 trades; the CSV contains all {trades.length}.</p>
                    )}
                  </div>
                )}

                {tab === "receipt" && (
                  <div className="report-section">
                    <p className="report-note">
                      Replaying this receipt recomputes the run from the same bars. If the data hash no longer matches, the
                      API refuses the replay with <code>409 data_changed</code> rather than reporting different numbers.
                    </p>
                    <dl className="report-defs">
                      {([
                        ["Run id", detail.run_id],
                        ["Engine version", receipt.engine_version ?? "—"],
                        ["Symbol", receipt.symbol ?? "—"],
                        ["Timeframe", receipt.timeframe ?? "—"],
                        ["Bars", receipt.bars ?? "—"],
                        ["Window start", fmtTime(receipt.window?.start)],
                        ["Window end", fmtTime(receipt.window?.end)],
                        ["Initial capital", fmtMetric(receipt.initial_capital, "money")],
                        ["Seed", receipt.seed ?? "—"],
                        ["OOS ratio", receipt.oos_ratio ?? "—"],
                        ["Created", fmtTime(receipt.created_at)],
                        ["Data hash", receipt.data_hash ?? "—"],
                        ["Spec hash", receipt.spec_hash ?? "—"],
                      ] as [string, string | number][]).map(([label, value]) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd className={label.endsWith("hash") ? "mono" : undefined}>{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <h3>Cost assumptions</h3>
                    <dl className="report-defs report-costs">
                      {Object.entries(receipt.costs ?? {}).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replaceAll("_", " ")}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <details className="report-spec">
                      <summary>Strategy spec</summary>
                      <pre>{JSON.stringify(receipt.spec ?? {}, null, 2)}</pre>
                    </details>
                    <div className="report-actions">
                      <button type="button" className="btn-secondary" onClick={() => void downloadCsv()}>
                        Download CSV
                      </button>
                      <button type="button" className="btn-secondary" onClick={() => void copyReceipt()}>
                        {copyState === "copied" ? "Receipt copied" : "Copy receipt JSON"}
                      </button>
                      {downloadError && <span className="report-error-text">{downloadError}</span>}
                    </div>
                  </div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function ComparisonTable({ comparison }: { comparison: CompareResponse }) {
  const keys = METRIC_ROWS;
  return (
    <section className="report-card">
      <header className="report-card-head">
        <div>
          <h2>Side-by-side</h2>
          <p>
            {comparison.left.receipt.symbol} · {comparison.left.receipt.timeframe} — {comparison.left.run_id.slice(-8)} vs{" "}
            {comparison.right.run_id.slice(-8)}
          </p>
        </div>
      </header>
      <table className="report-table report-compare-table">
        <caption>Metric deltas (right minus left). Both runs share the reportable fields.</caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">Left</th>
            <th scope="col">Right</th>
            <th scope="col">Δ</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((row) => {
            const delta = comparison.deltas[row.key];
            const numeric = typeof delta === "number" ? delta : null;
            return (
              <tr key={row.key}>
                <th scope="row">{row.label}</th>
                <td>{fmtRow(row, comparison.left.metrics[row.key])}</td>
                <td>{fmtRow(row, comparison.right.metrics[row.key])}</td>
                <td className={deltaTone(row, numeric)}>
                  {numeric === null ? "—" : fmtMetric(numeric, row.format)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="report-compare-receipts">
        {[comparison.left, comparison.right].map((side) => (
          <div key={side.run_id}>
            <h3>{side.run_id.slice(-8)}</h3>
            <dl className="report-defs report-costs">
              {Object.entries(side.receipt.costs ?? {}).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
              <div>
                <dt>data hash</dt>
                <dd className="mono">{side.receipt.data_hash?.slice(0, 16) ?? "—"}…</dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}
