import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

interface DivergenceAnalysis {
  strategy_id: string;
  strategy_version: number;
  backtest_run_id: string;
  paper_trading_id: string;
  divergence_score: number;
  metrics_comparison: {
    pnl_pct: { backtest: number; paper: number; diff: number };
    win_rate: { backtest: number; paper: number; diff: number };
    max_drawdown: { backtest: number; paper: number; diff: number };
    sharpe_ratio: { backtest: number; paper: number; diff: number };
    profit_factor: { backtest: number; paper: number; diff: number };
    avg_hold_time: { backtest: string; paper: string };
    total_trades: { backtest: number; paper: number };
  };
  risk_factors: string[];
  revalidation_recommended: boolean;
  revalidation_due: string;
}

interface RevalidationReminder {
  strategy_id: string;
  strategy_name: string;
  last_validation: string;
  days_since_validation: number;
  recommended_interval: number;
  overdue: boolean;
  performance_drift: number;
}

const DIVERGENCE_THRESHOLDS = {
  pnl_pct: 0.05,        // 5% divergence in PnL
  win_rate: 0.10,       // 10% divergence in win rate
  max_drawdown: 0.05,   // 5% divergence in max drawdown
  sharpe_ratio: 0.20,   // 20% divergence in Sharpe
  profit_factor: 0.15,  // 15% divergence in profit factor
};

const REVALIDATION_INTERVALS = {
  high_risk: 30,    // 30 days
  medium_risk: 60,  // 60 days
  low_risk: 90,     // 90 days
};

function getDivergenceClass(diff: number, threshold: number): string {
  const absDiff = Math.abs(diff);
  if (absDiff >= threshold) return "divergence-high";
  if (absDiff >= threshold * 0.5) return "divergence-medium";
  return "divergence-low";
}

function formatPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatDiff(backtest: number, paper: number): string {
  const diff = paper - backtest;
  return `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}%`;
}

export function DivergenceScorecards() {
  const [divergences, setDivergences] = useState<DivergenceAnalysis[]>([]);
  const [reminders, setReminders] = useState<RevalidationReminder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"scorecards" | "reminders" | "settings">("scorecards");

  const fetchDivergences = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/divergence/analyses`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDivergences(data.analyses);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load divergences");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchReminders = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/divergence/reminders`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setReminders(data.reminders);
    } catch (err) {
      console.error("Failed to load reminders:", err);
    }
  }, []);

  useEffect(() => {
    fetchDivergences();
    fetchReminders();
  }, [fetchDivergences, fetchReminders]);

  const calculateRiskLevel = (divergence: DivergenceAnalysis): "high" | "medium" | "low" => {
    const factors = divergence.risk_factors.length;
    if (factors >= 3) return "high";
    if (factors >= 1) return "medium";
    return "low";
  };

  const getRiskBadge = (level: "high" | "medium" | "low") => (
    <span className={`risk-badge ${level}`}>
      {level.charAt(0).toUpperCase() + level.slice(1)} Risk
    </span>
  );

  const triggerRevalidation = async (reminder: RevalidationReminder) => {
    if (!confirm(`Trigger revalidation for ${reminder.strategy_name}?`)) return;
    try {
      const res = await fetch(`${API_BASE}/divergence/revalidate/${reminder.strategy_id}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await res.text());
      fetchReminders();
      fetchDivergences();
    } catch (err) {
      console.error("Failed to trigger revalidation:", err);
    }
  };

  if (loading && divergences.length === 0) {
    return <div className="divergence-loading">Loading Divergence Scorecards...</div>;
  }

  if (error) {
    return <div className="divergence-error">Error: {error} <button onClick={fetchDivergences}>Retry</button></div>;
  }

  return (
    <div className="divergence-scorecards">
      <div className="divergence-header">
        <h1>Divergence Scorecards</h1>
        <div className="divergence-actions">
          {activeTab !== "scorecards" && (
            <button className="btn-secondary" onClick={() => setActiveTab("scorecards")}>
              ← Scorecards
            </button>
          )}
          <button className="btn-secondary" onClick={() => { fetchDivergences(); fetchReminders(); }}>
            🔄 Refresh
          </button>
        </div>
      </div>

      {activeTab === "scorecards" && (
        <div className="scorecards-tab">
          <div className="scorecards-summary">
            <div className="summary-stats">
              <div className="stat-card">
                <span className="stat-value">{divergences.length}</span>
                <span className="stat-label">Tracked Strategies</span>
              </div>
              <div className="stat-card">
                <span className="stat-value text-red-600">
                  {divergences.filter(d => getDivergenceClass(d.divergence_score, 0.5) === "high").length}
                </span>
                <span className="stat-label">High Divergence</span>
              </div>
              <div className="stat-card">
                <span className="stat-value text-yellow-600">
                  {divergences.filter(d => getDivergenceClass(d.divergence_score, 0.5) === "medium").length}
                </span>
                <span className="stat-label">Medium Divergence</span>
              </div>
              <div className="stat-card">
                <span className="stat-value text-green-600">
                  {divergences.filter(d => getDivergenceClass(d.divergence_score, 0.5) === "low").length}
                </span>
                <span className="stat-label">Low Divergence</span>
              </div>
            </div>
          </div>

          <div className="scorecards-grid">
            {divergences.map(divergence => {
              const riskLevel = getDivergenceClass(divergence.divergence_score, 0.5);
              return (
                <div key={divergence.strategy_id} className={`scorecard ${riskLevel}`}>
                  <div className="scorecard-header">
                    <div>
                      <h3>Strategy {divergence.strategy_id.slice(0, 8)}</h3>
                      <span className="version-badge">v{divergence.strategy_version}</span>
                    </div>
                    <div className="scorecard-score">
                      <span className={`divergence-score ${riskLevel}`}>
                        {(divergence.divergence_score * 100).toFixed(1)}%
                      </span>
                      {getRiskBadge(calculateRiskLevel(divergence))}
                    </div>
                  </div>

                  <div className="scorecard-metrics">
                    <div className="metric-row">
                      <span>PnL %</span>
                      <div className="metric-comparison">
                        <span>Backtest: {formatPct(divergence.metrics_comparison.pnl_pct.backtest)}</span>
                        <span className="separator">→</span>
                        <span>Paper: {formatPct(divergence.metrics_comparison.pnl_pct.paper)}</span>
                        <span className={getDivergenceClass(divergence.metrics_comparison.pnl_pct.diff, DIVERGENCE_THRESHOLDS.pnl_pct)}>
                          {formatDiff(divergence.metrics_comparison.pnl_pct.backtest, divergence.metrics_comparison.pnl_pct.paper)}
                        </span>
                      </div>
                    </div>
                    <div className="metric-row">
                      <span>Win Rate</span>
                      <div className="metric-comparison">
                        <span>Backtest: {divergence.metrics_comparison.win_rate.backtest.toFixed(1)}%</span>
                        <span className="separator">→</span>
                        <span>Paper: {divergence.metrics_comparison.win_rate.paper.toFixed(1)}%</span>
                        <span className={getDivergenceClass(divergence.metrics_comparison.win_rate.diff, DIVERGENCE_THRESHOLDS.win_rate)}>
                          {formatDiff(divergence.metrics_comparison.win_rate.backtest, divergence.metrics_comparison.win_rate.paper)}
                        </span>
                      </div>
                    </div>
                    <div className="metric-row">
                      <span>Max DD</span>
                      <div className="metric-comparison">
                        <span>Backtest: {divergence.metrics_comparison.max_drawdown.backtest.toFixed(2)}%</span>
                        <span className="separator">→</span>
                        <span>Paper: {divergence.metrics_comparison.max_drawdown.paper.toFixed(2)}%</span>
                        <span className={getDivergenceClass(divergence.metrics_comparison.max_drawdown.diff, DIVERGENCE_THRESHOLDS.max_drawdown)}>
                          {formatDiff(divergence.metrics_comparison.max_drawdown.backtest, divergence.metrics_comparison.max_drawdown.paper)}
                        </span>
                      </div>
                    </div>
                    <div className="metric-row">
                      <span>Sharpe</span>
                      <div className="metric-comparison">
                        <span>Backtest: {divergence.metrics_comparison.sharpe_ratio.backtest.toFixed(2)}</span>
                        <span className="separator">→</span>
                        <span>Paper: {divergence.metrics_comparison.sharpe_ratio.paper.toFixed(2)}</span>
                        <span className={getDivergenceClass(divergence.metrics_comparison.sharpe_ratio.diff, DIVERGENCE_THRESHOLDS.sharpe_ratio)}>
                          {formatDiff(divergence.metrics_comparison.sharpe_ratio.backtest, divergence.metrics_comparison.sharpe_ratio.paper)}
                        </span>
                      </div>
                    </div>
                    <div className="metric-row">
                      <span>Profit Factor</span>
                      <div className="metric-comparison">
                        <span>Backtest: {divergence.metrics_comparison.profit_factor.backtest.toFixed(2)}</span>
                        <span className="separator">→</span>
                        <span>Paper: {divergence.metrics_comparison.profit_factor.paper.toFixed(2)}</span>
                        <span className={getDivergenceClass(divergence.metrics_comparison.profit_factor.diff, DIVERGENCE_THRESHOLDS.profit_factor)}>
                          {formatDiff(divergence.metrics_comparison.profit_factor.backtest, divergence.metrics_comparison.profit_factor.paper)}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="scorecard-risk-factors">
                    <h4>Risk Factors</h4>
                    {divergence.risk_factors.length > 0 ? (
                      <ul>
                        {divergence.risk_factors.map((factor, i) => (
                          <li key={i}>{factor}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="no-factors">No significant risk factors detected</p>
                    )}
                  </div>

                  <div className="scorecard-actions">
                    <button className="btn-secondary btn-sm" onClick={() => {
                      // TODO: Show details modal
                    }}>
                      View Details
                    </button>
                    {divergence.revalidation_recommended && (
                      <button className="btn-warning btn-sm" onClick={() => {
                        // TODO: Trigger revalidation
                      }}>
                        ⚠ Revalidate
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {divergences.length === 0 && (
              <div className="empty-state">
                <p>No divergence analyses yet. Run backtests and paper trading to generate scorecards.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "reminders" && (
        <div className="reminders-tab">
          <div className="reminders-header">
            <h2>Revalidation Reminders</h2>
            <p className="reminders-note">
              Strategies should be revalidated periodically to ensure paper performance matches backtest expectations.
            </p>
          </div>

          <div className="reminders-list">
            {reminders.map(reminder => (
              <div key={reminder.strategy_id} className={`reminder-card ${reminder.overdue ? "overdue" : ""}`}>
                <div className="reminder-header">
                  <h3>{reminder.strategy_name}</h3>
                  <span className={`overdue-badge ${reminder.overdue ? "overdue" : "current"}`}>
                    {reminder.overdue ? `Overdue by ${reminder.days_since_validation - reminder.recommended_interval} days` : `${reminder.recommended_interval - reminder.days_since_validation} days remaining`}
                  </span>
                </div>
                <div className="reminder-meta">
                  <span>Last validated: {new Date(reminder.last_validation).toLocaleDateString()}</span>
                  <span>Interval: {reminder.recommended_interval} days</span>
                  <span className="drift-indicator">Drift: {reminder.performance_drift >= 0 ? "+" : ""}{reminder.performance_drift.toFixed(1)}%</span>
                </div>
                <div className="reminder-actions">
                  <button className="btn-primary" onClick={() => triggerRevalidation(reminder)}>
                    Revalidate Now
                  </button>
                  <button className="btn-secondary" onClick={() => {
                    // TODO: Show details
                  }}>
                    View History
                  </button>
                </div>
              </div>
            ))}
            {reminders.length === 0 && (
              <div className="empty-state">
                <p>No revalidation reminders at this time.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "settings" && (
        <div className="settings-tab">
          <h2>Divergence Settings</h2>
          
          <div className="settings-section">
            <h3>Divergence Thresholds</h3>
            <p className="settings-note">Adjust thresholds for flagging significant divergences between backtest and paper trading.</p>
            <div className="settings-grid">
              <div className="config-input-group">
                <label>PnL % Threshold <span className="suffix">%</span></label>
                <input
                  type="number"
                  step={0.5}
                  value={DIVERGENCE_THRESHOLDS.pnl_pct * 100}
                  onChange={e => { DIVERGENCE_THRESHOLDS.pnl_pct = parseFloat(e.target.value) / 100; }}
                />
              </div>
              <div className="config-input-group">
                <label>Win Rate Threshold <span className="suffix">%</span></label>
                <input
                  type="number"
                  step={1}
                  value={DIVERGENCE_THRESHOLDS.win_rate * 100}
                  onChange={e => { DIVERGENCE_THRESHOLDS.win_rate = parseFloat(e.target.value) / 100; }}
                />
              </div>
              <div className="config-input-group">
                <label>Max Drawdown Threshold <span className="suffix">%</span></label>
                <input
                  type="number"
                  step={0.5}
                  value={DIVERGENCE_THRESHOLDS.max_drawdown * 100}
                  onChange={e => { DIVERGENCE_THRESHOLDS.max_drawdown = parseFloat(e.target.value) / 100; }}
                />
              </div>
              <div className="config-input-group">
                <label>Sharpe Ratio Threshold <span className="suffix">%</span></label>
                <input
                  type="number"
                  step={5}
                  value={DIVERGENCE_THRESHOLDS.sharpe_ratio * 100}
                  onChange={e => { DIVERGENCE_THRESHOLDS.sharpe_ratio = parseFloat(e.target.value) / 100; }}
                />
              </div>
              <div className="config-input-group">
                <label>Profit Factor Threshold <span className="suffix">%</span></label>
                <input
                  type="number"
                  step={5}
                  value={DIVERGENCE_THRESHOLDS.profit_factor * 100}
                  onChange={e => { DIVERGENCE_THRESHOLDS.profit_factor = parseFloat(e.target.value) / 100; }}
                />
              </div>
            </div>
          </div>

          <div className="settings-section">
            <h3>Revalidation Intervals</h3>
            <p className="settings-note">Set how often strategies should be revalidated based on risk level.</p>
            <div className="settings-grid">
              <div className="config-input-group">
                <label>High Risk Interval (days)</label>
                <input
                  type="number"
                  step={1}
                  value={REVALIDATION_INTERVALS.high_risk}
                  onChange={e => { REVALIDATION_INTERVALS.high_risk = parseInt(e.target.value); }}
                />
              </div>
              <div className="config-input-group">
                <label>Medium Risk Interval (days)</label>
                <input
                  type="number"
                  step={1}
                  value={REVALIDATION_INTERVALS.medium_risk}
                  onChange={e => { REVALIDATION_INTERVALS.medium_risk = parseInt(e.target.value); }}
                />
              </div>
              <div className="config-input-group">
                <label>Low Risk Interval (days)</label>
                <input
                  type="number"
                  step={1}
                  value={REVALIDATION_INTERVALS.low_risk}
                  onChange={e => { REVALIDATION_INTERVALS.low_risk = parseInt(e.target.value); }}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}