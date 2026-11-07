import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";
import { ModelPicker } from "../layout/ModelPicker";

interface ProviderChoice {
  id: string;
  label: string;
  configured: boolean;
  default_model: string | null;
}

interface JobState {
  status?: string;
  message?: string;
  progress?: number;
  error?: string;
}

interface Props {
  initialSymbol: string;
  onComplete: () => Promise<void> | void;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("gateway_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** LLM strategy launcher, moved out of the retired in-lab Backtester panel. */
export function BacktestLauncher({ initialSymbol, onComplete }: Props) {
  const { isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const [prompt, setPrompt] = useState("");
  const [symbol, setSymbol] = useState(initialSymbol.toUpperCase());
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [tf, setTf] = useState("1d");
  const [bars, setBars] = useState(260);
  const [capital, setCapital] = useState(10000);
  const [callCap, setCallCap] = useState(12);
  const [providers, setProviders] = useState<ProviderChoice[]>([]);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setSymbol(initialSymbol.toUpperCase());
  }, [initialSymbol]);

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/llm/providers`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { providers?: ProviderChoice[] } | null) => {
        if (!active || !data?.providers) return;
        const ready = data.providers.filter((entry) => entry.configured);
        setProviders(ready);
        setProvider((current) => current || ready[0]?.id || "");
      })
      .catch(() => {
        if (active) setProviders([]);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => () => {
    if (pollRef.current) clearTimeout(pollRef.current);
  }, []);

  const launch = useCallback(async () => {
    if (!isAuthenticated) {
      openAuth("login");
      return;
    }
    if (!prompt.trim() || !symbol.trim() || !provider || !model) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const response = await fetch(`${API_BASE}/agentic-lab/backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          kind: "llm",
          prompt: prompt.trim(),
          provider,
          model,
          symbol: symbol.trim().toUpperCase(),
          tf,
          bars,
          capital,
          max_llm_calls: callCap,
          risk: { max_position_pct: 100, max_drawdown_pct: 0, allow_short: true },
        }),
      });
      if (!response.ok) throw new Error((await response.text()).slice(0, 300) || "Could not start backtest");
      const { job_id } = (await response.json()) as { job_id: string };

      const poll = async (): Promise<void> => {
        const result = await fetch(`${API_BASE}/agentic-lab/jobs/${job_id}`, { headers: authHeaders() });
        if (!result.ok) throw new Error((await result.text()).slice(0, 300) || "Could not poll backtest");
        const state = (await result.json()) as JobState;
        setJob(state);
        if (state.status === "queued" || state.status === "running") {
          pollRef.current = setTimeout(() => {
            void poll().catch((err: unknown) => {
              setError(err instanceof Error ? err.message : "Backtest polling failed");
              setBusy(false);
            });
          }, 1000);
          return;
        }
        setBusy(false);
        if (state.status === "succeeded") await onComplete();
      };

      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start backtest");
      setBusy(false);
    }
  }, [isAuthenticated, openAuth, prompt, provider, model, symbol, tf, bars, capital, callCap, onComplete]);

  return (
    <section className="strategy-launcher" aria-label="Natural-language strategy backtest">
      <div className="strategy-launcher-head">
        <div>
          <h2>Describe a strategy to backtest</h2>
          <p>Model-generated signals are replayed against historical OHLCV only. No orders are placed.</p>
        </div>
        <span className="bt-historical">Historical only</span>
      </div>
      <label className="strategy-prompt-field">
        <span>Strategy instruction</span>
        <textarea
          value={prompt}
          maxLength={2000}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="e.g. Go long when the 20-day moving average crosses above the 50-day average; exit when it crosses below."
          rows={3}
        />
      </label>
      <div className="strategy-launcher-grid">
        <label>
          <span>Symbol</span>
          <input value={symbol} maxLength={20} onChange={(event) => setSymbol(event.target.value.toUpperCase())} />
        </label>
        <label>
          <span>Provider</span>
          <select
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setModel("");
            }}
          >
            <option value="">Choose configured provider…</option>
            {providers.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.label}</option>
            ))}
          </select>
        </label>
        <div className="strategy-model-field">
          <span>Model</span>
          <ModelPicker
            providerId={provider}
            configured={!!providers.find((entry) => entry.id === provider)?.configured}
            value={model}
            onChange={setModel}
          />
        </div>
        <label>
          <span>Timeframe</span>
          <select value={tf} onChange={(event) => setTf(event.target.value)}>
            <option value="1d">Daily</option>
            <option value="1h">Hourly</option>
            <option value="1wk">Weekly</option>
          </select>
        </label>
        <label>
          <span>Bars (40–1000)</span>
          <input
            type="number"
            min={40}
            max={1000}
            value={bars}
            onChange={(event) => setBars(Math.min(1000, Math.max(40, Number(event.target.value) || 40)))}
          />
        </label>
        <label>
          <span>Capital ($100–$10m)</span>
          <input
            type="number"
            min={100}
            max={10000000}
            value={capital}
            onChange={(event) => setCapital(Math.min(10000000, Math.max(100, Number(event.target.value) || 100)))}
          />
        </label>
        <label>
          <span>Model calls (1–40)</span>
          <input
            type="number"
            min={1}
            max={40}
            value={callCap}
            onChange={(event) => setCallCap(Math.min(40, Math.max(1, Number(event.target.value) || 1)))}
          />
        </label>
      </div>
      <div className="strategy-review">
        <span>Review</span>
        <p>
          {prompt.trim() || "Describe the rules the model should follow."} · {symbol || "No symbol"} · {tf} · {bars} bars ·
          ${capital.toLocaleString()} capital · up to {callCap} model calls
        </p>
      </div>
      <div className="action-buttons">
        <button
          type="button"
          className="btn-primary"
          disabled={busy || !prompt.trim() || !symbol.trim() || !provider || !model}
          onClick={() => void launch()}
        >
          {busy ? "Running historical backtest…" : "Run backtest"}
        </button>
        {!isAuthenticated && (
          <button type="button" className="btn-secondary" onClick={() => openAuth("login")}>
            Sign in to run
          </button>
        )}
      </div>
      {error && <p className="settings-error" role="alert">{error}</p>}
      {job && (
        <div className="strategy-job" role="status">
          <p>{job.message || job.status}</p>
          {(job.status === "queued" || job.status === "running") && (
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }} />
            </div>
          )}
          {job.error && <p className="settings-error">{job.error}</p>}
          {job.status === "succeeded" && (
            <p>
              Backtest complete. <a href="/app/agentic-lab">Open Agentic Lab</a> to review the model run.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
