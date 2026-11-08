import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE } from "../../lib/constants";

/* §5.1 Monte Carlo surface (FR-M1..M7): percentile fan, drawdown histogram,
   tail risk, ruin probability and the sizing suggestion. Everything rendered
   here is a resampling of the source's own past returns — either a stored
   backtest run's equity curve or a series the caller derived from real bars. */

interface FanPoint {
  step: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

interface Histogram {
  bins: number[];
  counts: number[];
}

interface McResponse {
  source: "run" | "returns";
  run_id?: string;
  receipt_data_hash?: string | null;
  seed: number;
  paths: number;
  horizon: number;
  method: "gbm" | "bootstrap";
  block_length: number | null;
  start_equity: number;
  data_hash: string;
  output_hash: string;
  engine_version: string;
  observations: number;
  fan: FanPoint[];
  terminal_distribution: Histogram;
  terminal_summary: { mean: number; sd: number };
  var_cvar: { var_95: number; cvar_95: number; var_99: number; cvar_99: number };
  drawdown_distribution: {
    p50_pct: number;
    p95_pct: number;
    p99_pct: number;
    worst_pct: number;
    histogram: Histogram;
  };
  ruin: {
    threshold: number;
    fraction_of_start: number;
    probability: number;
    ruined_paths: number;
    median_time_to_ruin: number | null;
  };
  sizing: {
    risk_budget: number;
    position_multiplier: number;
    cvar_99: number;
    expected_tail_loss_at_multiplier: number;
    note: string;
  } | null;
  disclaimer: string;
}

export interface MonteCarloSeries {
  /** Simple per-bar returns derived from real closes; the API log-transforms them. */
  returns: number[];
  /** The last observed close the simulated paths start from. */
  startEquity: number;
  /** Human-readable provenance, e.g. "daily returns of AAPL". */
  label: string;
}

interface Props {
  /** A stored run to resample; mutually exclusive with `series`. */
  runId?: string;
  /** A series derived from real market bars, used when there is no stored run. */
  series?: MonteCarloSeries;
  token: string | null;
  initialCapital?: number;
  bars?: number;
}

const money = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(digits)}%`;

const W = 720;
const FAN_H = 240;
const HIST_H = 150;
const PAD = { left: 10, right: 10, top: 10, bottom: 16 };

function FanChart({ fan, startEquity }: { fan: FanPoint[]; startEquity: number }) {
  const { min, max } = useMemo(() => {
    const values = fan.flatMap((point) => [point.p5, point.p95]);
    const low = Math.min(...values, startEquity);
    const high = Math.max(...values, startEquity);
    const span = high - low || Math.max(high, 1) * 0.01;
    return { min: low - span * 0.04, max: high + span * 0.04 };
  }, [fan, startEquity]);

  const maxStep = fan.at(-1)?.step ?? 1;
  const x = (step: number) =>
    PAD.left + (step / Math.max(1, maxStep)) * (W - PAD.left - PAD.right);
  const y = (value: number) =>
    PAD.top + (1 - (value - min) / Math.max(1e-9, max - min)) * (FAN_H - PAD.top - PAD.bottom);

  const band = (lowKey: "p5" | "p25", highKey: "p75" | "p95") =>
    [
      ...fan.map((point) => `${x(point.step)},${y(point[highKey])}`),
      ...[...fan].reverse().map((point) => `${x(point.step)},${y(point[lowKey])}`),
    ].join(" ");

  const median = fan.map((point) => `${x(point.step)},${y(point.p50)}`).join(" ");

  return (
    <svg className="mc-chart" viewBox={`0 0 ${W} ${FAN_H}`} role="img" aria-label="Percentile fan of simulated equity">
      <polygon className="mc-band-outer" points={band("p5", "p95")} />
      <polygon className="mc-band-inner" points={band("p25", "p75")} />
      <line className="report-chart-base" x1={PAD.left} x2={W - PAD.right} y1={y(startEquity)} y2={y(startEquity)} />
      <polyline className="mc-median" points={median} />
      <text className="mc-axis-label" x={PAD.left} y={FAN_H - 3}>
        bar 0
      </text>
      <text className="mc-axis-label" x={W - PAD.right} y={FAN_H - 3} textAnchor="end">
        bar {maxStep}
      </text>
      <text className="mc-axis-label" x={PAD.left + 6} y={y(startEquity) - 4}>
        start {money(startEquity)}
      </text>
    </svg>
  );
}

function DrawdownHistogram({ histogram }: { histogram: Histogram }) {
  const counts = histogram.counts;
  const peak = Math.max(1, ...counts);
  const bins = counts.length;
  const width = (W - PAD.left - PAD.right) / Math.max(1, bins);
  return (
    <svg className="mc-chart" viewBox={`0 0 ${W} ${HIST_H}`} role="img" aria-label="Histogram of simulated maximum drawdowns">
      {counts.map((count, index) => {
        const height = (count / peak) * (HIST_H - PAD.top - PAD.bottom);
        return (
          <rect
            key={index}
            className="mc-dd-bar"
            x={PAD.left + index * width + 1}
            y={HIST_H - PAD.bottom - height}
            width={Math.max(1, width - 2)}
            height={height}
          />
        );
      })}
      <line
        className="mc-axis"
        x1={PAD.left}
        x2={W - PAD.right}
        y1={HIST_H - PAD.bottom}
        y2={HIST_H - PAD.bottom}
      />
      <text className="mc-axis-label" x={PAD.left} y={HIST_H - 3}>
        {pct(histogram.bins[0], 1)} max drawdown
      </text>
      <text className="mc-axis-label" x={W - PAD.right} y={HIST_H - 3} textAnchor="end">
        {pct(histogram.bins.at(-1), 1)}
      </text>
    </svg>
  );
}

export function MonteCarloPanel({ runId, series, token, initialCapital, bars }: Props) {
  const defaultHorizon = Math.min(250, Math.max(20, (bars ?? 250) - 1));
  const [method, setMethod] = useState<"bootstrap" | "gbm">("bootstrap");
  const [paths, setPaths] = useState(10_000);
  const [horizon, setHorizon] = useState(defaultHorizon);
  const [seed, setSeed] = useState(42);
  const [budget, setBudget] = useState<string>("");
  const [result, setResult] = useState<McResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    const source = runId
      ? { run_id: runId }
      : series
        ? { returns: series.returns, start_equity: series.startEquity }
        : null;
    if (!source) return;
    setLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const parsedBudget = Number(budget);
      const response = await fetch(`${API_BASE}/quant/monte-carlo`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          ...source,
          method,
          paths,
          horizon,
          seed,
          ...(budget.trim() !== "" && Number.isFinite(parsedBudget) && parsedBudget >= 0
            ? { risk_budget: parsedBudget }
            : {}),
        }),
      });
      if (response.status === 401) {
        setError("Sign in to simulate this run.");
        return;
      }
      const payload = (await response.json()) as McResponse & { detail?: unknown };
      if (!response.ok) {
        const detail = payload.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message?: unknown }).message)
              : `Simulation failed (${response.status})`;
        throw new Error(message);
      }
      setResult(payload);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setLoading(false);
    }
  }, [budget, horizon, method, paths, runId, seed, series, token]);

  useEffect(() => {
    if (!runId && !series) return;
    setResult(null);
    void run();
    // A new run selection or a new bar-derived series re-simulates with the current controls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, series]);

  const sizing = result?.sizing;

  return (
    <div
      className="report-section mc-panel"
      data-source={result?.source}
      data-engine={result?.engine_version}
      data-paths={result?.paths}
      data-horizon={result?.horizon}
      data-seed={result?.seed}
      data-method={result?.method}
      data-observations={result?.observations}
      data-start-equity={result?.start_equity}
      data-output-hash={result?.output_hash}
    >
      <p className="mc-disclaimer">
        <strong>Simulation, not a forecast.</strong> These paths resample the past{" "}
        {series ? series.label : "returns of this strategy"}
        {result ? ` (${result.observations} observations, engine ${result.engine_version})` : ""}; they do not
        predict future prices and do not prove the strategy will keep working.
      </p>

      <div className="mc-controls">
        <label>
          Method
          <select value={method} onChange={(event) => setMethod(event.target.value as "bootstrap" | "gbm")}>
            <option value="bootstrap">Block bootstrap (observed returns)</option>
            <option value="gbm">GBM (fitted drift & volatility)</option>
          </select>
        </label>
        <label>
          Paths
          <input
            type="number"
            min={100}
            max={50_000}
            step={500}
            value={paths}
            onChange={(event) => setPaths(Math.max(1, Number(event.target.value) || 1))}
          />
        </label>
        <label>
          Horizon (bars)
          <input
            type="number"
            min={1}
            max={2_000}
            value={horizon}
            onChange={(event) => setHorizon(Math.max(1, Number(event.target.value) || 1))}
          />
        </label>
        <label>
          Seed
          <input
            type="number"
            min={0}
            value={seed}
            onChange={(event) => setSeed(Math.max(0, Math.floor(Number(event.target.value) || 0)))}
          />
        </label>
        <label>
          Risk budget
          <input
            type="number"
            min={0}
            step={100}
            placeholder={initialCapital ? String(Math.round(initialCapital * 0.02)) : "optional"}
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
          />
        </label>
        <button type="button" className="btn-secondary" onClick={() => void run()} disabled={loading}>
          {loading ? "Simulating…" : "Simulate"}
        </button>
      </div>

      {error && <p className="report-error-text">{error}</p>}

      {result && (
        <>
          <div className="report-charts">
            <figure>
              <figcaption>Percentile fan (5/25/50/75/95)</figcaption>
              <FanChart fan={result.fan} startEquity={result.start_equity} />
              <p className="report-axis">
                Median path in the centre; the pale band holds 5–95% of simulated paths.
              </p>
            </figure>
            <figure>
              <figcaption>Max drawdown distribution</figcaption>
              <DrawdownHistogram histogram={result.drawdown_distribution.histogram} />
              <p className="report-axis">
                p50 {pct(result.drawdown_distribution.p50_pct, 1)} · p95{" "}
                {pct(result.drawdown_distribution.p95_pct, 1)} · p99{" "}
                {pct(result.drawdown_distribution.p99_pct, 1)} · worst{" "}
                {pct(result.drawdown_distribution.worst_pct, 1)}
              </p>
            </figure>
          </div>

          <table className="report-table">
            <caption>
              Tail risk over {result.paths.toLocaleString()} paths · horizon {result.horizon} bars ·{" "}
              {result.method === "bootstrap" ? `block length ${result.block_length}` : "GBM" } · seed {result.seed}
            </caption>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">95%</th>
                <th scope="col">99%</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">VaR (loss not exceeded)</th>
                <td>{money(result.var_cvar.var_95, 2)}</td>
                <td>{money(result.var_cvar.var_99, 2)}</td>
              </tr>
              <tr>
                <th scope="row">CVaR (mean loss beyond VaR)</th>
                <td>{money(result.var_cvar.cvar_95, 2)}</td>
                <td>{money(result.var_cvar.cvar_99, 2)}</td>
              </tr>
              <tr>
                <th scope="row">P(ruin) — equity ≤ {money(result.ruin.threshold)}</th>
                <td colSpan={2}>
                  {pct(result.ruin.probability * 100, 1)} ({result.ruin.ruined_paths} of{" "}
                  {result.paths.toLocaleString()} paths)
                  {result.ruin.median_time_to_ruin !== null
                    ? ` · median first crossing at bar ${result.ruin.median_time_to_ruin}`
                    : ""}
                </td>
              </tr>
              <tr>
                <th scope="row">Median terminal equity</th>
                <td colSpan={2}>
                  {money(result.fan.at(-1)?.p50, 2)} (mean {money(result.terminal_summary.mean, 2)})
                </td>
              </tr>
            </tbody>
          </table>

          <div className="mc-sizing">
            <h3>Sizing suggestion</h3>
            {sizing ? (
              <p>
                <strong>{sizing.position_multiplier.toFixed(2)}×</strong> position multiplier keeps simulated
                CVaR at 99% ({money(sizing.cvar_99, 2)}) within the {money(sizing.risk_budget, 2)} budget —
                expected tail loss {money(sizing.expected_tail_loss_at_multiplier, 2)}. {sizing.note}
              </p>
            ) : (
              <p className="report-note">
                Enter a risk budget to get a position multiplier sized so simulated CVaR at 99% stays inside it.
              </p>
            )}
          </div>

          <dl className="report-defs">
            {(
              [
                ["Seed", String(result.seed)],
                ["Paths", result.paths.toLocaleString()],
                ["Horizon", `${result.horizon} bars`],
                ["Method", result.method],
                ["Block length", result.block_length === null ? "—" : String(result.block_length)],
                ["Engine", result.engine_version],
                ["Data hash", result.data_hash],
                ["Output hash", result.output_hash],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd className={label.endsWith("hash") ? "mono" : undefined}>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  );
}
