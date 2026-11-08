import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

interface AiConfig {
  enabled: boolean;
  route: "paper" | "live";
  symbols: string[];
  strategy: "momentum" | "mean_reversion";
  max_position_notional: number;
  confidence_threshold: number;
  use_journal_memory: boolean;
  use_backtest_memory: boolean;
  cycle_seconds: number;
}

interface JournalMemory {
  closed: number;
  wins: number;
  win_rate: number | null;
  pnl: number;
}

interface LogRow {
  id: string;
  ts: string;
  symbol: string | null;
  action: string;
  confidence: number | null;
  reason: string | null;
  price: number | null;
  qty: number | null;
  route: string;
  ok: number;
  detail: string | null;
}

interface AiStatus {
  running: boolean;
  config: AiConfig;
  last_log: LogRow[];
  journal_memory: Record<string, JournalMemory>;
  backtest_edge: number | null;
}

const ACTION_LABELS: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  hold: "Hold",
  skip: "Skip",
  error: "Error",
};

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * AI Trading section: the agent allocates funds and trades on a cycle,
 * scaling its confidence with learned experience from the owner's journal
 * (past paper/actual trades) and local backtest results.
 */
export function AiTrading({ selectedSymbol }: { selectedSymbol?: string }) {
  const { token, isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [log, setLog] = useState<LogRow[]>([]);
  const [form, setForm] = useState<AiConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/ai-trading`, { headers: authHeaders(token) });
      if (!res.ok) return;
      const data = (await res.json()) as AiStatus;
      setStatus(data);
      setForm((current) => current ?? data.config);
    } catch {
      /* status is decoration */
    }
  }, [token]);

  const fetchLog = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/ai-trading/log?limit=50`, {
        headers: authHeaders(token),
      });
      if (!res.ok) return;
      setLog((await res.json()) as LogRow[]);
    } catch {
      /* log is decoration */
    }
  }, [token]);

  useEffect(() => {
    if (!token) {
      setStatus(null);
      setLog([]);
      setForm(null);
      return;
    }
    void fetchStatus();
    void fetchLog();
  }, [token, fetchStatus, fetchLog]);

  // Poll faster while the agent is running so decisions show up live.
  useEffect(() => {
    if (!token) return undefined;
    const interval = status?.running ? 5000 : 20000;
    const id = window.setInterval(() => {
      void fetchStatus();
      void fetchLog();
    }, interval);
    return () => window.clearInterval(id);
  }, [status?.running, token, fetchStatus, fetchLog]);

  const post = async (path: string): Promise<void> => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: authHeaders(token),
      });
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(body.detail ?? `Request failed (${res.status})`);
      await fetchStatus();
      await fetchLog();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!form) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`${API_BASE}/ai-trading`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders(token) },
        body: JSON.stringify(form),
      });
      const body = (await res.json().catch(() => ({}))) as { detail?: string; config?: AiConfig };
      if (!res.ok) throw new Error(body.detail ?? "Save failed");
      if (body.config) setForm(body.config);
      setNotice("Configuration saved.");
      await fetchStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const running = status?.running ?? false;
  const memoryEntries = Object.entries(status?.journal_memory ?? {});

  if (!isAuthenticated || !token) {
    return (
      <section className="paper-error" role="status" aria-label="Sign in to use AI Trading">
        <h2>Sign in to use AI Trading</h2>
        <p>
          Your AI trader, its watchlist and every decision it makes are private to your
          account. Sign in to configure it and run its paper portfolio.
        </p>
        <button className="btn-primary" onClick={() => openAuth()}>
          Sign in
        </button>
      </section>
    );
  }

  if (!form) {
    return <div className="paper-loading">{error ?? "Loading AI trader…"}</div>;
  }

  return (
    <div className="ai-trading" data-running={running} data-log-count={log.length}>
      {(error || notice) && (
        <div className={error ? "paper-alert error" : "paper-alert"} role="status">
          <span>{error ?? notice}</span>
          <button className="btn-ghost" onClick={() => { setError(null); setNotice(null); }}>
            Dismiss
          </button>
        </div>
      )}

      <div className="ai-controls">
        <section className="desk-card ai-config-card">
          <div className="ai-card-head">
            <h3>Agent configuration</h3>
            <span className={`ai-run-badge ${running ? "on" : ""}`}>
              {running ? "● Running" : "○ Stopped"}
            </span>
          </div>

          <div className="ai-form-grid">
            <label className="paper-field">
              <span>Symbols (comma separated)</span>
              <input
                type="text"
                value={form.symbols.join(", ")}
                onChange={(e) =>
                  setForm({
                    ...form,
                    symbols: e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
                  })
                }
                placeholder="SPY, QQQ, AAPL"
              />
            </label>

            <label className="paper-field">
              <span>Strategy</span>
              <select
                value={form.strategy}
                onChange={(e) => setForm({ ...form, strategy: e.target.value as AiConfig["strategy"] })}
              >
                <option value="momentum">Momentum (follow the trend)</option>
                <option value="mean_reversion">Mean reversion (fade extremes)</option>
              </select>
            </label>

            <label className="paper-field">
              <span>Max position size ($ per symbol)</span>
              <input
                type="number"
                min={10}
                step={50}
                value={form.max_position_notional}
                onChange={(e) => setForm({ ...form, max_position_notional: Number(e.target.value) || 10 })}
              />
            </label>

            <label className="paper-field">
              <span>Confidence threshold — {Math.round(form.confidence_threshold * 100)}%</span>
              <input
                type="range"
                min={0.3}
                max={0.95}
                step={0.05}
                value={form.confidence_threshold}
                onChange={(e) => setForm({ ...form, confidence_threshold: Number(e.target.value) })}
              />
            </label>

            <label className="paper-field">
              <span>Cycle every (seconds)</span>
              <input
                type="number"
                min={15}
                step={15}
                value={form.cycle_seconds}
                onChange={(e) => setForm({ ...form, cycle_seconds: Number(e.target.value) || 60 })}
              />
            </label>
          </div>

          <p className="ai-route-note">
            Trade route: <b>Paper portfolio</b> (simulated funds only — live broker
            execution is not available).
          </p>

          <div className="ai-memory-toggles">
            <label>
              <input
                type="checkbox"
                checked={form.use_journal_memory}
                onChange={(e) => setForm({ ...form, use_journal_memory: e.target.checked })}
              />
              Learn from past trades (journal win rate &amp; PnL)
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.use_backtest_memory}
                onChange={(e) => setForm({ ...form, use_backtest_memory: e.target.checked })}
              />
              Learn from backtest results (recent strategy edge)
            </label>
          </div>

          <div className="ai-actions">
            <button className="btn-secondary" onClick={() => void handleSave()} disabled={busy}>
              Save config
            </button>
            <button
              className="btn-secondary"
              onClick={() => void post("/ai-trading/cycle")}
              disabled={busy}
              title="Evaluate every symbol once right now"
            >
              Run one cycle now
            </button>
            {running ? (
              <button className="btn-secondary" onClick={() => void post("/ai-trading/stop")} disabled={busy}>
                ⏸ Stop agent
              </button>
            ) : (
              <button
                className="btn-primary"
                onClick={() => void post("/ai-trading/start")}
                disabled={busy || form.symbols.length === 0}
              >
                ▶ Start agent
              </button>
            )}
          </div>
        </section>

        <section className="desk-card ai-memory-card">
          <div className="ai-card-head">
            <h3>Learned experience</h3>
            <span className="ai-edge">
              Backtest edge:{" "}
              <b className={(status?.backtest_edge ?? 0) >= 0 ? "up" : "down"}>
                {status?.backtest_edge === null || status?.backtest_edge === undefined
                  ? "—"
                  : `${status.backtest_edge >= 0 ? "+" : ""}${(status.backtest_edge * 100).toFixed(1)}%`}
              </b>
            </span>
          </div>
          {memoryEntries.length === 0 ? (
            <p className="paper-empty">No journal memory yet — close some trades to teach the agent.</p>
          ) : (
            <table className="paper-table">
              <thead>
                <tr><th>Symbol</th><th>Closed trades</th><th>Win rate</th><th>PnL</th></tr>
              </thead>
              <tbody>
                {memoryEntries.map(([symbol, m]) => (
                  <tr key={symbol}>
                    <td className="paper-symbol">{symbol}</td>
                    <td>{m.closed}</td>
                    <td>{m.win_rate === null ? "—" : `${Math.round(m.win_rate * 100)}%`}</td>
                    <td className={m.pnl >= 0 ? "positive" : "negative"}>
                      {m.pnl >= 0 ? "+" : ""}{m.pnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="desk-card ai-log-card">
        <div className="ai-card-head">
          <h3>Decision log {selectedSymbol ? <span className="ai-log-sub">watching {selectedSymbol}</span> : null}</h3>
        </div>
        {log.length === 0 ? (
          <p className="paper-empty">
            No decisions yet — start the agent or run a cycle to see its reasoning.
          </p>
        ) : (
          <table className="paper-table">
            <thead>
              <tr>
                <th>Time</th><th>Symbol</th><th>Action</th><th>Conf.</th><th>Price</th><th>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {log.map((row) => (
                <tr key={row.id} className={row.ok ? "" : "ai-log-error"} data-log-id={row.id}>
                  <td>{new Date(row.ts).toLocaleTimeString()}</td>
                  <td className="paper-symbol">{row.symbol ?? "—"}</td>
                  <td>
                    <span className={`side-badge ${row.action === "buy" ? "buy" : row.action === "sell" ? "sell" : ""}`}>
                      {ACTION_LABELS[row.action] ?? row.action}
                    </span>
                  </td>
                  <td>{fmtPct(row.confidence)}</td>
                  <td>{row.price !== null ? row.price.toFixed(2) : "—"}</td>
                  <td className="ai-log-reason">
                    {row.detail || row.reason || ""}
                    <span className="ai-log-route">{row.route}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
