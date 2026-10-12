import { useCallback, useMemo, useState } from "react";
import { API_BASE } from "../../lib/constants";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface BtTrade {
  direction: "long" | "short";
  entry_equity: number;
  exit_equity: number;
  pnl_pct: number;
  entry_time: number | null;
  entry_price: number | null;
  exit_time: number | null;
  exit_price: number | null;
}

interface BtDecision {
  time: number;
  action: string;
  price: number;
  reason: string;
  risk?: { rule: string; proposed: string; approved: string; reason: string };
}

export interface BtRun {
  id: string;
  created_at: string;
  kind: string;
  strategy: string;
  symbol: string;
  symbol_b?: string | null;
  pair_config?: Record<string, any>;
  pair_series?: { time: number; spread: number | null; zscore: number | null; beta: number | null; pvalue: number | null; cointegrated: boolean; signal: string }[];
  walk_forward?: { folds?: { fold: number; test_start: number; test_end: number; cointegration_pvalue: number | null; cointegrated: boolean; metrics: Record<string, any> }[]; out_of_sample_metrics?: Record<string, any> };
  fills?: { status: string; fill_time?: number; legs?: { symbol_leg: string; side: string; filled_quantity: number; fill_price: number; modeled_spread_bps: number; fee: number; status: string }[] }[];
  execution_model?: { warning?: string; participation_rate?: number; spread_floor_bps?: number; range_factor?: number };
  bars: number;
  tf: string;
  capital: number;
  provider: string | null;
  model: string | null;
  decisions: BtDecision[];
  trades: BtTrade[];
  equity_curve: { time: number; equity: number }[];
  risk_events?: { time: number; rule: string; reason: string }[];
  bar_returns?: number[];
  metrics: Record<string, any>;
}

interface OpenPosition {
  direction: "long" | "short";
  entry_time: number;
  entry_price: number;
  exit_time: number | null;
  exit_price: number | null;
  status: "open" | "closed";
}
type SideTab = "pnl" | "positions" | "trades" | "logs";
const SIDE_TABS: { id: SideTab; label: string; icon: string }[] = [
  { id: "pnl", label: "Theoretical P&L", icon: "∑" },
  { id: "positions", label: "Opened positions", icon: "⧉" },
  { id: "trades", label: "Trades", icon: "⇄" },
  { id: "logs", label: "Backtest logs", icon: "≡" },
];
const COLORS = ["#42d3a5", "#ff9f43", "#5da9ff", "#d58cff", "#ff6680", "#f5d547", "#54d6e8", "#b9d86a"];
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}
function fmtTime(ms: number | null | undefined): string {
  if (!ms) return "—";
  const seconds = ms > 1e12 ? ms / 1000 : ms;
  return new Date(seconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value < 0 ? "-" : ""}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function pct(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
function derivePositions(decisions: BtDecision[]): OpenPosition[] {
  const out: OpenPosition[] = [];
  let current: OpenPosition | null = null;
  const close = (time: number, price: number) => {
    if (!current) return;
    current.exit_time = time; current.exit_price = price; current.status = "closed"; out.push(current); current = null;
  };
  for (const decision of decisions) {
    if (decision.action === "long" || decision.action === "short") {
      if (current && current.direction !== decision.action) close(decision.time, decision.price);
      if (!current) current = { direction: decision.action, entry_time: decision.time, entry_price: decision.price, exit_time: null, exit_price: null, status: "open" };
    } else if (decision.action === "flat") close(decision.time, decision.price);
  }
  if (current) out.push(current);
  return out;
}
function EquityCurve({ curve, capital }: { curve: { time: number; equity: number }[]; capital: number }) {
  if (!curve || curve.length < 2) return <p className="empty-state">No equity curve recorded for this run.</p>;
  const values = curve.map((point) => point.equity), min = Math.min(...values, capital), max = Math.max(...values, capital), span = max - min || 1;
  const width = 720, height = 160;
  const line = values.map((value, index) => `${(index / (values.length - 1) * width).toFixed(1)},${(height - ((value - min) / span) * (height - 12) - 6).toFixed(1)}`).join(" ");
  const baseline = height - ((capital - min) / span) * (height - 12) - 6;
  return <svg className="bt-equity" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Equity curve"><line x1="0" y1={baseline} x2={width} y2={baseline} className="bt-equity-base"/><polyline points={line} className="bt-equity-line"/></svg>;
}
function PairSpreadChart({ series, entryZ, exitZ }: { series: NonNullable<BtRun["pair_series"]>; entryZ: number; exitZ: number }) {
  const points = series.filter((point) => Number.isFinite(point.zscore));
  if (points.length < 2) return <p className="empty-state">No eligible pair spread points in the stored run.</p>;
  const width = 720, height = 180, maxAbs = Math.max(entryZ * 1.2, ...points.map((point) => Math.abs(point.zscore ?? 0)));
  const y = (value: number) => height - (value + maxAbs) / (2 * maxAbs) * height;
  const path = points.map((point, index) => `${(index / (points.length - 1) * width).toFixed(1)},${y(point.zscore ?? 0).toFixed(1)}`).join(" ");
  return <div className="pairs-series-chart"><svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Pair spread z-score with entry and exit thresholds"><line x1="0" y1={y(entryZ)} x2={width} y2={y(entryZ)} className="pairs-entry-line"/><line x1="0" y1={y(-entryZ)} x2={width} y2={y(-entryZ)} className="pairs-entry-line"/><line x1="0" y1={y(exitZ)} x2={width} y2={y(exitZ)} className="pairs-exit-line"/><line x1="0" y1={y(-exitZ)} x2={width} y2={y(-exitZ)} className="pairs-exit-line"/><line x1="0" y1={y(0)} x2={width} y2={y(0)} className="pairs-zero-line"/><polyline points={path} className="pairs-z-line"/></svg><div className="pairs-chart-legend"><span>Spread z-score</span><span>Entry ±{entryZ}</span><span>Exit ±{exitZ}</span></div></div>;
}
function PairsRunDetails({ run }: { run: BtRun }) {
  const folds = run.walk_forward?.folds ?? [];
  const fillRows = (run.fills ?? []).flatMap((fill) => (fill.legs ?? []).map((leg) => ({ fill, leg })));
  return <section className="pairs-run-details"><div className="pairs-run-disclosure"><b>Synthetic order book</b><span>{run.execution_model?.warning ?? "OHLCV-derived spread and capacity; not historical Level-2 replay."}</span></div><div className="pairs-run-summary"><span>OOS return <b>{run.walk_forward?.out_of_sample_metrics?.total_return_pct ?? "—"}%</b></span><span>Folds <b>{folds.length}</b></span><span>Cointegrated folds <b>{folds.filter((fold) => fold.cointegrated).length}</b></span><span>Participation <b>{((run.execution_model?.participation_rate ?? 0) * 100).toFixed(1)}%</b></span></div>{folds.length > 0 && <table className="bt-table"><thead><tr><th>Fold</th><th>Test window</th><th>EG p-value</th><th>Return</th><th>Trades</th></tr></thead><tbody>{folds.map((fold) => <tr key={fold.fold}><td>{fold.fold}</td><td>{fmtTime(fold.test_start)} – {fmtTime(fold.test_end)}</td><td>{fold.cointegration_pvalue?.toFixed(3) ?? "—"}</td><td>{pct(fold.metrics.total_return_pct)}</td><td>{fold.metrics.trades}</td></tr>)}</tbody></table>}{fillRows.length > 0 && <details className="pairs-fills"><summary>Simulated leg fills ({fillRows.length})</summary><table className="bt-table"><thead><tr><th>Time</th><th>Leg</th><th>Side</th><th>Quantity</th><th>Price</th><th>Spread</th><th>Status</th></tr></thead><tbody>{fillRows.slice(0, 200).map(({ fill, leg }, index) => <tr key={`${fill.fill_time}-${index}`}><td>{fmtTime(fill.fill_time)}</td><td>{run.symbol && leg.symbol_leg === "a" ? run.symbol : run.symbol_b}</td><td>{leg.side}</td><td>{leg.filled_quantity.toFixed(4)}</td><td>{leg.fill_price.toFixed(4)}</td><td>{leg.modeled_spread_bps.toFixed(1)} bps</td><td>{leg.status}</td></tr>)}</tbody></table></details>}<p className="pairs-validation-note">Walk-forward folds report historical out-of-sample performance; this is not a guarantee against overfitting or future loss.</p></section>;
}

interface MonteCarloPoint { step: number; median: number; lower: number; upper: number }
interface MonteCarloSeries { run_id: string; strategy: string; symbol?: string; points: MonteCarloPoint[] }
interface BacktesterProps { runs: BtRun[]; loading: boolean; error: string | null; onRefresh: () => void }

export default function Backtester({ runs, loading, error: runError, onRefresh }: BacktesterProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<SideTab>("pnl");
  const [selectedMonteCarlo, setSelectedMonteCarlo] = useState<string[]>([]);
  const [simulations, setSimulations] = useState(300);
  const [horizon, setHorizon] = useState(250);
  const [confidence, setConfidence] = useState(0.9);
  const [monteCarlo, setMonteCarlo] = useState<MonteCarloSeries[]>([]);
  const [mcError, setMcError] = useState<string | null>(null);
  const [mcBusy, setMcBusy] = useState(false);
  const load = onRefresh;
  const selected = useMemo(() => runs.find((run) => run.id === selectedId) ?? runs[0] ?? null, [runs, selectedId]);
  const positions = useMemo(() => selected ? derivePositions(selected.decisions ?? []) : [], [selected]);
  const metrics = selected?.metrics ?? {};
  const capital = selected?.capital ?? 0;
  const finalEquity = typeof metrics.final_equity === "number" ? metrics.final_equity : null;
  const pnlDollars = finalEquity !== null ? finalEquity - capital : null;
  const eligible = runs.filter((run) => run.kind !== "pairs" && !run.symbol_b && Array.isArray(run.bar_returns) && run.bar_returns.length > 0 && run.bar_returns.length <= 1000);
  const [pairSelection, setPairSelection] = useState("all");
  const visibleRuns = pairSelection === "pairs" ? runs.filter((run) => run.kind === "pairs") : runs.filter((run) => run.kind !== "pairs");
  const excluded = runs.length - eligible.length;
  const requestedWorkExceedsLimit = selectedMonteCarlo.length * simulations * horizon > 4_000_000;
  const monteCarloValues = monteCarlo.flatMap((series) => series.points.flatMap((point) => [point.lower, point.upper]));
  const monteCarloMin = monteCarloValues.length ? Math.min(...monteCarloValues) : 0;
  const monteCarloSpan = (monteCarloValues.length ? Math.max(...monteCarloValues) : 1) - monteCarloMin || 1;
  const monteCarloColors = useMemo(() => new Map(
    [...new Set(monteCarlo.map((series) => series.run_id))]
      .sort()
      .map((runId, index) => [runId, COLORS[index] ?? COLORS[0]!]),
  ), [monteCarlo]);
  const runMonteCarlo = useCallback(async () => {
    if (!selectedMonteCarlo.length || requestedWorkExceedsLimit) return;
    setMcBusy(true); setMcError(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/monte-carlo`, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ run_ids: selectedMonteCarlo, simulations, horizon, confidence, seed: 1, start_capital: capital || 10_000 }) });
      if (!response.ok) throw new Error((await response.text()).slice(0, 300));
      setMonteCarlo(((await response.json()) as { series: MonteCarloSeries[] }).series);
    } catch (err) { setMcError(err instanceof Error ? err.message : "Monte Carlo comparison failed"); }
    finally { setMcBusy(false); }
  }, [selectedMonteCarlo, simulations, horizon, confidence, capital, requestedWorkExceedsLimit]);

  return <div className="bt-workspace">
    <section className="mc-panel" aria-label="Monte Carlo comparison"><div className="mc-panel-head"><div><h2>Monte Carlo comparison</h2><p>Resample historical per-bar returns to compare selected single-strategy runs.</p></div><span>{eligible.length} eligible{excluded ? ` · ${excluded} excluded` : ""}</span></div>
      <div className="mc-controls"><label>Simulations<input type="number" min={100} max={1000} step={50} value={simulations} onChange={(event) => setSimulations(Number(event.target.value))}/></label><label>Horizon bars<input type="number" min={20} max={1000} step={10} value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}/></label><label>Confidence<select value={confidence} onChange={(event) => setConfidence(Number(event.target.value))}><option value={0.8}>80%</option><option value={0.9}>90%</option><option value={0.95}>95%</option><option value={0.99}>99%</option></select></label><button type="button" className="btn-primary" disabled={mcBusy || !selectedMonteCarlo.length || requestedWorkExceedsLimit} onClick={() => void runMonteCarlo()}>{mcBusy ? "Simulating…" : "Compare selected"}</button></div>
      {requestedWorkExceedsLimit && <p className="mc-excluded" role="status">Reduce runs, simulations, or horizon to stay within the 4,000,000-point work limit.</p>}
      <div className="mc-run-options">{eligible.map((run) => <label key={run.id}><input type="checkbox" checked={selectedMonteCarlo.includes(run.id)} onChange={() => setSelectedMonteCarlo((current) => current.includes(run.id) ? current.filter((id) => id !== run.id) : current.length < 8 ? [...current, run.id] : current)}/><span>{run.symbol} · {run.strategy}</span></label>)}</div>
      {excluded > 0 && <p className="mc-excluded">Pairs and legacy runs without full-resolution returns are excluded; only new single-strategy runs can be sampled.</p>}<p className="mc-disclaimer">Historical-return bootstrap only — this is not a forecast, guarantee, or protection from overfitting.</p>
      {(mcError || runError) && <p className="settings-error" role="alert">{mcError || runError}<button type="button" className="btn-secondary" onClick={load}>Refresh history</button></p>}
      {monteCarlo.length > 0 && <div className="mc-chart-wrap"><svg className="mc-chart" viewBox="0 0 720 260" role="img" aria-label="Monte Carlo median and confidence paths"><line x1="0" y1="245" x2="720" y2="245" className="mc-axis"/>{monteCarlo.map((series) => { const color = monteCarloColors.get(series.run_id) ?? COLORS[0]!; const x = (step: number) => step / Math.max(1, horizon) * 710 + 5; const y = (value: number) => 245 - (value - monteCarloMin) / monteCarloSpan * 225; const line = series.points.map((point) => `${x(point.step)},${y(point.median)}`).join(" "); const polygon = [...series.points.map((point) => `${x(point.step)},${y(point.upper)}`), ...[...series.points].reverse().map((point) => `${x(point.step)},${y(point.lower)}`)].join(" "); return <g key={series.run_id}><polygon points={polygon} fill={color} opacity="0.12"/><polyline points={line} fill="none" stroke={color} strokeWidth="2.5"/></g>; })}</svg><div className="mc-legend">{monteCarlo.map((series) => <span key={series.run_id}><i style={{ background: monteCarloColors.get(series.run_id) ?? COLORS[0]! }}/>{series.symbol} · {series.strategy}</span>)}</div></div>}
    </section>      <div className="bt-desk"><aside className="bt-side" aria-label="Backtest details"><nav className="bt-side-tabs" role="tablist" aria-label="Backtest detail sections">{SIDE_TABS.map((entry) => <button key={entry.id} role="tab" aria-selected={tab === entry.id} className={`bt-side-tab ${tab === entry.id ? "active" : ""}`} onClick={() => setTab(entry.id)}><span aria-hidden="true">{entry.icon}</span>{entry.label}</button>)}</nav><div className="bt-side-body">
      {!selected && <p className="empty-state">{loading ? "Loading runs…" : "No backtest runs yet."}</p>}
      {selected && tab === "pnl" && <section className="bt-panel"><h3>Theoretical P&amp;L</h3><p className="bt-note">Simulated on historical bars — hypothetical, not realised.</p><div className="bt-pnl-hero"><span className={`bt-pnl-value ${(metrics.total_return_pct ?? 0) >= 0 ? "up" : "down"}`}>{pct(metrics.total_return_pct)}</span><span className="bt-pnl-sub">{fmtMoney(pnlDollars)}</span></div><dl className="bt-defs">{[["Start capital", fmtMoney(capital)], ["Final equity", fmtMoney(finalEquity)], ["Market return", pct(metrics.benchmark_return_pct)], ["vs market", pct(metrics.excess_return_pct)], ["Sharpe", metrics.sharpe_ratio ?? "—"], ["Max drawdown", `${metrics.max_drawdown_pct ?? "—"}%`], ["Win rate", `${metrics.win_rate_pct ?? "—"}%`], ["Profit factor", metrics.profit_factor ?? "—"], ["Trades", metrics.trades ?? selected.trades?.length ?? 0], ["Exposure", `${metrics.exposure_pct ?? "—"}%`]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{metrics.verdict && <p className={`bt-verdict ${metrics.verdict_tone ?? "neutral"}`}>{metrics.verdict}</p>}</section>}
      {selected && tab === "positions" && <section className="bt-panel"><h3>Opened positions</h3><p className="bt-note">{positions.length} position(s) opened during this run.</p>{positions.length === 0 ? <p className="empty-state">No positions were opened.</p> : <table className="bt-table"><thead><tr><th>Side</th><th>Entered</th><th>Entry</th><th>Exited</th><th>Exit</th><th>Status</th></tr></thead><tbody>{positions.map((position, index) => <tr key={`${position.entry_time}-${index}`}><td><span className={`bt-side-chip ${position.direction}`}>{position.direction}</span></td><td>{fmtTime(position.entry_time)}</td><td>{position.entry_price.toFixed(2)}</td><td>{fmtTime(position.exit_time)}</td><td>{position.exit_price?.toFixed(2) ?? "—"}</td><td><span className={`bt-status ${position.status}`}>{position.status === "open" ? "held to end" : "closed"}</span></td></tr>)}</tbody></table>}</section>}
      {selected && tab === "trades" && <section className="bt-panel"><h3>Trades</h3><p className="bt-note">Fill legs produced by the simulation.</p>{(selected.trades ?? []).length === 0 ? <p className="empty-state">No fills in this run.</p> : <table className="bt-table"><thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th></tr></thead><tbody>{selected.trades.map((trade, index) => <tr key={`${trade.entry_time}-${index}`}><td><span className={`bt-side-chip ${trade.direction}`}>{trade.direction}</span></td><td title={fmtTime(trade.entry_time)}>{trade.entry_price?.toFixed(2) ?? "—"}</td><td title={fmtTime(trade.exit_time)}>{trade.exit_price?.toFixed(2) ?? "—"}</td><td className={trade.pnl_pct >= 0 ? "up" : "down"}>{pct(trade.pnl_pct)}</td></tr>)}</tbody></table>}</section>}
      {selected && tab === "logs" && <section className="bt-panel"><h3>Backtest logs</h3><ul className="bt-log"><li><span className="bt-log-time">{fmtTime(Date.parse(selected.created_at))}Z</span><span className="bt-log-msg">Started {selected.strategy} on {selected.symbol} · {selected.tf} · {selected.bars} bars{selected.model ? ` · ${selected.model}` : ""}</span></li>{(selected.decisions ?? []).map((decision, index) => <li key={`d-${index}`}><span className="bt-log-time">{fmtTime(decision.time)}</span><span className="bt-log-msg"><b className={decision.action}>{decision.action}</b> @ {decision.price?.toFixed(2) ?? "—"}{decision.risk ? ` · 🛡 ${decision.risk.rule}` : ""}</span></li>)}{(selected.risk_events ?? []).map((event, index) => <li key={`r-${index}`}><span className="bt-log-time">{fmtTime(event.time)}</span><span className="bt-log-msg warn">🛡 {event.rule}: {event.reason}</span></li>)}</ul></section>}
    </div></aside><main className="bt-main"><div className="bt-main-head"><div className="bt-run-picker-wrap"><label className="bt-run-filter">Run type <select value={pairSelection} onChange={(event) => setPairSelection(event.target.value)}><option value="all">Single strategy</option><option value="pairs">Cointegration pairs</option></select></label><div className="bt-run-picker" role="group" aria-label="Select a backtest run">{visibleRuns.map((run) => <button key={run.id} className={`bt-run-chip ${selected?.id === run.id ? "active" : ""}`} onClick={() => setSelectedId(run.id)} title={`${run.strategy} · ${run.created_at}`}><b>{run.symbol}{run.symbol_b ? `/${run.symbol_b}` : ""}</b><span>{run.strategy}</span><i className={(run.metrics?.total_return_pct ?? 0) >= 0 ? "up" : "down"}>{pct(run.metrics?.total_return_pct)}</i></button>)}{visibleRuns.length === 0 && !loading && <span className="empty-state">No {pairSelection === "pairs" ? "pair" : "single-strategy"} runs yet.</span>}</div></div><span className="bt-historical" title="This screen only replays past market data">🕘 Historical only</span></div>
      {selected && <><section className="bt-card"><header className="bt-card-head"><div><h2>{selected.strategy}</h2><p>{selected.symbol}{selected.symbol_b ? ` / ${selected.symbol_b}` : ""} · {selected.tf} · {selected.bars} bars · capital {fmtMoney(selected.capital)}{selected.model ? ` · ${selected.model}` : ""}</p></div><div className="bt-card-stats"><span className={`bt-big ${(metrics.total_return_pct ?? 0) >= 0 ? "up" : "down"}`}>{pct(metrics.total_return_pct)}</span><span className="bt-big-sub">vs market {pct(metrics.benchmark_return_pct)}</span></div></header>{selected.kind === "pairs" ? <PairSpreadChart series={selected.pair_series ?? []} entryZ={selected.pair_config?.entry_z ?? 2} exitZ={selected.pair_config?.exit_z ?? 0.5}/> : <EquityCurve curve={selected.equity_curve ?? []} capital={selected.capital}/ >}{selected.kind === "pairs" && <PairsRunDetails run={selected}/>}<p className="bt-axis">{fmtTime(selected.equity_curve?.[0]?.time)} → {fmtTime(selected.equity_curve?.at(-1)?.time)} (UTC)</p></section><section className="bt-stat-grid">{(metrics.stats ?? []).map((stat: any) => <div key={stat.label} className="bt-stat" title={stat.hint}><span className="bt-stat-label">{stat.label}</span><strong className="bt-stat-value">{stat.value}</strong></div>)}{(metrics.stats ?? []).length === 0 && <><div className="bt-stat"><span className="bt-stat-label">Trades</span><strong className="bt-stat-value">{selected.trades?.length ?? 0}</strong></div><div className="bt-stat"><span className="bt-stat-label">Positions opened</span><strong className="bt-stat-value">{positions.length}</strong></div></>}</section></>}
    </main></div></div>;
}
