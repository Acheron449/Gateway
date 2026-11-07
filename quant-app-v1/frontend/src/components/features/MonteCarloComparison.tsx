import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE } from "../../lib/constants";

interface LabRun {
  id: string;
  kind: string;
  strategy: string;
  symbol: string;
  symbol_b?: string | null;
  capital: number;
  bar_returns?: number[];
}

interface MonteCarloPoint {
  step: number;
  median: number;
  lower: number;
  upper: number;
}

interface MonteCarloSeries {
  run_id: string;
  strategy: string;
  symbol?: string;
  points: MonteCarloPoint[];
}

interface Props {
  token: string | null;
  refreshKey?: number;
}

const COLORS = ["#42d3a5", "#ff9f43", "#5da9ff", "#d58cff", "#ff6680", "#f5d547", "#54d6e8", "#b9d86a"];

/** Multi-run historical bootstrap, moved out of the retired in-lab Backtester panel. */
export function MonteCarloComparison({ token, refreshKey = 0 }: Props) {
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [simulations, setSimulations] = useState(300);
  const [horizon, setHorizon] = useState(250);
  const [confidence, setConfidence] = useState(0.9);
  const [series, setSeries] = useState<MonteCarloSeries[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }, [token]);

  const loadRuns = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/runs?limit=50`, { headers: authHeaders });
      if (!response.ok) throw new Error(`Could not load model runs (${response.status})`);
      const data = (await response.json()) as { runs?: LabRun[] };
      const list = data.runs ?? [];
      setRuns(list);
      setSelected((current) => current.filter((id) => list.some((run) => run.id === id)));
    } catch (err) {
      setRuns([]);
      setSelected([]);
      setError(err instanceof Error ? err.message : "Could not load model runs");
    }
  }, [authHeaders]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns, refreshKey]);

  const eligible = runs.filter(
    (run) =>
      run.kind !== "pairs" &&
      !run.symbol_b &&
      Array.isArray(run.bar_returns) &&
      run.bar_returns.length > 0 &&
      run.bar_returns.length <= 1000,
  );
  const excluded = runs.length - eligible.length;
  const requestedWorkExceedsLimit = selected.length * simulations * horizon > 4_000_000;
  const values = series.flatMap((entry) => entry.points.flatMap((point) => [point.lower, point.upper]));
  const min = values.length ? Math.min(...values) : 0;
  const span = (values.length ? Math.max(...values) : 1) - min || 1;
  const colors = useMemo(
    () =>
      new Map(
        [...new Set(series.map((entry) => entry.run_id))]
          .sort()
          .map((runId, index) => [runId, COLORS[index] ?? COLORS[0]!]),
      ),
    [series],
  );

  const runComparison = useCallback(async () => {
    if (!selected.length || requestedWorkExceedsLimit) return;
    setBusy(true);
    setError(null);
    const startCapital = runs.find((run) => run.id === selected[0])?.capital || 10_000;
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/monte-carlo`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          run_ids: selected,
          simulations,
          horizon,
          confidence,
          seed: 1,
          start_capital: startCapital,
        }),
      });
      if (!response.ok) throw new Error((await response.text()).slice(0, 300));
      setSeries(((await response.json()) as { series: MonteCarloSeries[] }).series);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Monte Carlo comparison failed");
    } finally {
      setBusy(false);
    }
  }, [selected, requestedWorkExceedsLimit, runs, simulations, horizon, confidence, authHeaders]);

  return (
    <section className="mc-panel" aria-label="Monte Carlo comparison">
      <div className="mc-panel-head">
        <div>
          <h2>Monte Carlo comparison</h2>
          <p>Resample historical per-bar returns to compare selected single-strategy model runs.</p>
        </div>
        <span>
          {eligible.length} eligible{excluded ? ` · ${excluded} excluded` : ""}
        </span>
      </div>
      <div className="mc-controls">
        <label>
          Simulations
          <input
            type="number"
            min={100}
            max={1000}
            step={50}
            value={simulations}
            onChange={(event) => setSimulations(Number(event.target.value))}
          />
        </label>
        <label>
          Horizon bars
          <input
            type="number"
            min={20}
            max={1000}
            step={10}
            value={horizon}
            onChange={(event) => setHorizon(Number(event.target.value))}
          />
        </label>
        <label>
          Confidence
          <select value={confidence} onChange={(event) => setConfidence(Number(event.target.value))}>
            <option value={0.8}>80%</option>
            <option value={0.9}>90%</option>
            <option value={0.95}>95%</option>
            <option value={0.99}>99%</option>
          </select>
        </label>
        <button
          type="button"
          className="btn-primary"
          disabled={busy || !selected.length || requestedWorkExceedsLimit}
          onClick={() => void runComparison()}
        >
          {busy ? "Simulating…" : "Compare selected"}
        </button>
      </div>
      {requestedWorkExceedsLimit && (
        <p className="mc-excluded" role="status">
          Reduce runs, simulations, or horizon to stay within the 4,000,000-point work limit.
        </p>
      )}
      <div className="mc-run-options">
        {eligible.map((run) => (
          <label key={run.id}>
            <input
              type="checkbox"
              checked={selected.includes(run.id)}
              onChange={() =>
                setSelected((current) =>
                  current.includes(run.id)
                    ? current.filter((id) => id !== run.id)
                    : current.length < 8
                      ? [...current, run.id]
                      : current,
                )
              }
            />
            <span>{run.symbol} · {run.strategy}</span>
          </label>
        ))}
      </div>
      {excluded > 0 && (
        <p className="mc-excluded">
          Pairs and legacy runs without full-resolution returns are excluded; only new single-strategy runs can be sampled.
        </p>
      )}
      <p className="mc-disclaimer">
        Historical-return bootstrap only — this is not a forecast, guarantee, or protection from overfitting.
      </p>
      {error && (
        <p className="settings-error" role="alert">
          {error}
          <button type="button" className="btn-secondary" onClick={() => void loadRuns()}>
            Refresh model runs
          </button>
        </p>
      )}
      {series.length > 0 && (
        <div className="mc-chart-wrap">
          <svg className="mc-chart" viewBox="0 0 720 260" role="img" aria-label="Monte Carlo median and confidence paths">
            <line x1="0" y1="245" x2="720" y2="245" className="mc-axis" />
            {series.map((entry) => {
              const color = colors.get(entry.run_id) ?? COLORS[0]!;
              const x = (step: number) => (step / Math.max(1, horizon)) * 710 + 5;
              const y = (value: number) => 245 - ((value - min) / span) * 225;
              const line = entry.points.map((point) => `${x(point.step)},${y(point.median)}`).join(" ");
              const polygon = [
                ...entry.points.map((point) => `${x(point.step)},${y(point.upper)}`),
                ...[...entry.points].reverse().map((point) => `${x(point.step)},${y(point.lower)}`),
              ].join(" ");
              return (
                <g key={entry.run_id}>
                  <polygon points={polygon} fill={color} opacity="0.12" />
                  <polyline points={line} fill="none" stroke={color} strokeWidth="2.5" />
                </g>
              );
            })}
          </svg>
          <div className="mc-legend">
            {series.map((entry) => (
              <span key={entry.run_id}>
                <i style={{ background: colors.get(entry.run_id) ?? COLORS[0]! }} />
                {entry.symbol} · {entry.strategy}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
