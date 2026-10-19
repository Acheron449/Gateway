import { useState } from "react";
import { API_BASE } from "../../lib/constants";

interface PairConfig {
  lookback: number;
  entry_z: number;
  exit_z: number;
  cointegration_pvalue: number;
  walk_forward_folds: number;
  spread_floor_bps: number;
  range_factor: number;
  participation_rate: number;
}

const DEFAULT_CONFIG: PairConfig = {
  lookback: 60,
  entry_z: 2,
  exit_z: 0.5,
  cointegration_pvalue: 0.05,
  walk_forward_folds: 4,
  spread_floor_bps: 2,
  range_factor: 0.1,
  participation_rate: 0.1,
};

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function responseError(response: Response): Promise<string> {
  const body = await response.text().catch(() => "");
  try {
    const parsed = JSON.parse(body) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // Surface a bounded response body for non-JSON failures.
  }
  return body.slice(0, 300) || `${response.status} ${response.statusText}`;
}

export function PairsBacktestLauncher({
  initialSymbol = "",
  onComplete,
}: {
  initialSymbol?: string;
  onComplete: () => void;
}) {
  const [symbolA, setSymbolA] = useState(initialSymbol.toUpperCase());
  const [symbolB, setSymbolB] = useState("");
  const [timeframe, setTimeframe] = useState("1d");
  const [bars, setBars] = useState(400);
  const [capital, setCapital] = useState(10_000);
  const [config, setConfig] = useState<PairConfig>(DEFAULT_CONFIG);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const updateConfig = (key: keyof PairConfig, value: string) => {
    const number = Number(value);
    setConfig((current) => ({ ...current, [key]: number }));
  };

  const run = async () => {
    setError("");
    setMessage("");
    const first = symbolA.trim().toUpperCase();
    const second = symbolB.trim().toUpperCase();
    if (!first || !second || first === second) {
      setError("Choose two different symbols.");
      return;
    }
    if (config.exit_z >= config.entry_z) {
      setError("Exit z-score must be lower than entry z-score.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          kind: "pairs",
          symbol: first,
          symbol_b: second,
          tf: timeframe,
          bars,
          capital,
          pair_config: config,
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const { job_id: jobId } = (await response.json()) as { job_id: string };
      setMessage("Fetching aligned histories and starting the pair backtest…");
      for (let attempt = 0; attempt < 300; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const jobResponse = await fetch(`${API_BASE}/agentic-lab/jobs/${jobId}`, { headers: authHeaders() });
        if (!jobResponse.ok) throw new Error(await responseError(jobResponse));
        const job = (await jobResponse.json()) as { status: string; progress?: number; message?: string; error?: string };
        setMessage(job.message ?? `Running… ${Math.round((job.progress ?? 0) * 100)}%`);
        if (job.status === "failed") throw new Error(job.error || job.message || "Pairs backtest failed.");
        if (job.status === "succeeded") {
          setMessage("Pairs run complete. Results are saved in Backtester history.");
          onComplete();
          return;
        }
      }
      throw new Error("The run is taking longer than expected; check Backtester history shortly.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not run pairs backtest.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="pairs-launcher" aria-label="Pairs backtest launcher">
      <div className="pairs-launcher-head">
        <div>
          <h2>Cointegration pairs</h2>
          <p>Rolling log-price hedge ratio; trade spread reversions only while Engle–Granger indicates cointegration.</p>
        </div>
        <span className="pairs-badge">Research / historical only</span>
      </div>
      <div className="pairs-form-grid">
        <label>Leg A<input value={symbolA} maxLength={20} onChange={(event) => setSymbolA(event.target.value.toUpperCase())} placeholder="SPY" /></label>
        <label>Leg B<input value={symbolB} maxLength={20} onChange={(event) => setSymbolB(event.target.value.toUpperCase())} placeholder="QQQ" /></label>
        <label>Timeframe<select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}><option value="1d">Daily</option><option value="1h">Hourly</option><option value="1wk">Weekly</option></select></label>
        <label>Bars<input type="number" min={80} max={1000} step={20} value={bars} onChange={(event) => setBars(Number(event.target.value))} /></label>
        <label>Starting capital<input type="number" min={100} value={capital} onChange={(event) => setCapital(Number(event.target.value))} /></label>
        <label>Rolling lookback<input type="number" min={30} max={250} value={config.lookback} onChange={(event) => updateConfig("lookback", event.target.value)} /></label>
        <label>Entry z-score<input type="number" min={0.1} max={5} step={0.1} value={config.entry_z} onChange={(event) => updateConfig("entry_z", event.target.value)} /></label>
        <label>Exit z-score<input type="number" min={0} max={4} step={0.1} value={config.exit_z} onChange={(event) => updateConfig("exit_z", event.target.value)} /></label>
        <label>Cointegration p-value<input type="number" min={0.001} max={0.999} step={0.001} value={config.cointegration_pvalue} onChange={(event) => updateConfig("cointegration_pvalue", event.target.value)} /></label>
        <label>Walk-forward folds<input type="number" min={1} max={10} value={config.walk_forward_folds} onChange={(event) => updateConfig("walk_forward_folds", event.target.value)} /></label>
        <label>Spread floor (bps)<input type="number" min={0} max={100} step={0.5} value={config.spread_floor_bps} onChange={(event) => updateConfig("spread_floor_bps", event.target.value)} /></label>
        <label>Range factor<input type="number" min={0} max={2} step={0.05} value={config.range_factor} onChange={(event) => updateConfig("range_factor", event.target.value)} /></label>
        <label>Volume participation<input type="number" min={0.001} max={0.25} step={0.001} value={config.participation_rate} onChange={(event) => updateConfig("participation_rate", event.target.value)} /></label>
      </div>
      <p className="pairs-disclosure">Order-book fills are synthetic OHLCV approximations, volume-capped paired legs—not historical Level-2 replay. Walk-forward results assess historical out-of-sample behavior; they do not guarantee profitability or eliminate overfitting.</p>
      <div className="pairs-actions"><button type="button" className="btn-primary" onClick={() => void run()} disabled={busy}>{busy ? "Running pairs…" : "Run pairs backtest"}</button>{message && <span role="status">{message}</span>}</div>
      {error && <p className="settings-error" role="alert">{error}</p>}
    </section>
  );
}
