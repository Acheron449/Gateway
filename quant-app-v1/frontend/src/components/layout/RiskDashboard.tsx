import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../../lib/constants";

interface RiskMetrics {
  portfolio_value: number;
  cash: number;
  equity: number;
  buying_power: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  max_drawdown: number;
  current_drawdown: number;
  open_positions: number;
  gross_exposure: number;
  net_exposure: number;
  concentration_risk: { symbol: string; pct: number }[];
  var_95: number;
  var_99: number;
}

interface RiskAlert {
  id: string;
  type: "warning" | "critical" | "info";
  message: string;
  timestamp: string;
  acknowledged: boolean;
}

interface RiskConfig {
  max_position_pct: number;
  max_sector_pct: number;
  max_gross_exposure: number;
  max_drawdown_pct: number;
  daily_loss_limit_pct: number;
  var_limit_95: number;
  kill_switch_active: boolean;
}

const ALERT_TYPE_COLORS = {
  warning: "bg-yellow-100 text-yellow-800 border-yellow-300",
  critical: "bg-red-100 text-red-800 border-red-300",
  info: "bg-blue-100 text-blue-800 border-blue-300",
};

export function RiskDashboard() {
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [alerts, setAlerts] = useState<RiskAlert[]>([]);
  const [config, setConfig] = useState<RiskConfig | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "positions" | "alerts" | "config">("overview");

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/risk/metrics`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setMetrics(data);
    } catch (err) {
      console.error("Failed to load metrics:", err);
    }
  }, []);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/risk/alerts`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setAlerts(data.alerts);
    } catch (err) {
      console.error("Failed to load alerts:", err);
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/risk/config`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setConfig(data);
    } catch (err) {
      console.error("Failed to load config:", err);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
    fetchAlerts();
    fetchConfig();
    // Refresh metrics every 30 seconds
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, [fetchMetrics, fetchAlerts, fetchConfig]);

  const acknowledgeAlert = async (alertId: string) => {
    try {
      await fetch(`${API_BASE}/risk/alerts/${alertId}/acknowledge`, { method: "POST" });
      setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, acknowledged: true } : a));
    } catch (err) {
      console.error("Failed to acknowledge alert:", err);
    }
  };

  const updateConfig = async (updates: Partial<RiskConfig>) => {
    if (!config) return;
    try {
      const res = await fetch(`${API_BASE}/risk/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...config, ...updates }),
      });
      if (!res.ok) throw new Error(await res.text());
      setConfig({ ...config, ...updates });
    } catch (err) {
      console.error("Failed to update config:", err);
    }
  };

  const toggleKillSwitch = async () => {
    if (!config) return;
    try {
      await fetch(`${API_BASE}/risk/kill-switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !config.kill_switch_active }),
      });
      setConfig({ ...config, kill_switch_active: !config.kill_switch_active });
    } catch (err) {
      console.error("Failed to toggle kill switch:", err);
    }
  };

  const criticalAlerts = alerts.filter(a => a.type === "critical" && !a.acknowledged);
  const warningAlerts = alerts.filter(a => a.type === "warning" && !a.acknowledged);
  const infoAlerts = alerts.filter(a => a.type === "info" && !a.acknowledged);

  return (
    <div className="risk-dashboard">
      <div className="dashboard-header">
        <h1>Risk Dashboard</h1>
        <div className="dashboard-actions">
          {config?.kill_switch_active && (
            <div className="kill-switch-banner">
              ⚠ KILL SWITCH ACTIVE - All new orders blocked
            </div>
          )}
          <div className="dashboard-tabs">
            <button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")}>Overview</button>
            <button className={activeTab === "positions" ? "active" : ""} onClick={() => setActiveTab("positions")}>Positions</button>
            <button className={activeTab === "alerts" ? "active" : ""} onClick={() => setActiveTab("alerts")}>Alerts ({criticalAlerts.length + warningAlerts.length})</button>
            <button className={activeTab === "config" ? "active" : ""} onClick={() => setActiveTab("config")}>Config</button>
          </div>
        </div>
      </div>

      {activeTab === "overview" && metrics && (
        <div className="dashboard-overview">
          <div className="metrics-grid">
            <MetricCard
              label="Portfolio Value"
              value={`$${metrics.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              change={metrics.daily_pnl_pct}
              changeLabel="Daily P&L"
            />
            <MetricCard
              label="Cash"
              value={`$${metrics.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            />
            <MetricCard
              label="Buying Power"
              value={`$${metrics.buying_power.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            />
            <MetricCard
              label="Daily P&L"
              value={`$${metrics.daily_pnl >= 0 ? "+" : ""}${metrics.daily_pnl.toFixed(2)}`}
              subValue={`${metrics.daily_pnl_pct >= 0 ? "+" : ""}${metrics.daily_pnl_pct.toFixed(2)}%`}
              isPositive={metrics.daily_pnl >= 0}
            />
            <MetricCard
              label="Current Drawdown"
              value={`${metrics.current_drawdown.toFixed(2)}%`}
              subValue={`Max: ${metrics.max_drawdown.toFixed(2)}%`}
              isPositive={metrics.current_drawdown < metrics.max_drawdown * 0.5}
            />
            <MetricCard
              label="VaR (95%)"
              value={`$${metrics.var_95.toLocaleString()}`}
            />
            <MetricCard
              label="Open Positions"
              value={metrics.open_positions.toString()}
            />
            <MetricCard
              label="Gross Exposure"
              value={`${(metrics.gross_exposure * 100).toFixed(1)}%`}
              isPositive={metrics.gross_exposure < (config?.max_gross_exposure || 1)}
            />
          </div>

          <div className="charts-section">
            <div className="chart-card">
              <h3>Equity Curve</h3>
              <div className="chart-placeholder">Equity curve chart would go here</div>
            </div>
            <div className="chart-card">
              <h3>Drawdown</h3>
              <div className="chart-placeholder">Drawdown chart would go here</div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "positions" && metrics && (
        <div className="positions-tab">
          <h2>Position Risk Analysis</h2>
          <div className="positions-table">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Quantity</th>
                  <th>Entry</th>
                  <th>Current</th>
                  <th>Unrealized P&L</th>
                  <th>% of Portfolio</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {metrics.concentration_risk.map(pos => (
                  <tr key={pos.symbol}>
                    <td className="symbol-cell">{pos.symbol}</td>
                    <td>Long</td>
                    <td>—</td>
                    <td>—</td>
                    <td>—</td>
                    <td>—</td>
                    <td>{pos.pct.toFixed(2)}%</td>
                    <td>
                      <span className={pos.pct > 10 ? "risk-high" : pos.pct > 5 ? "risk-medium" : "risk-low"}>
                        {pos.pct > 10 ? "High" : pos.pct > 5 ? "Medium" : "Low"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="exposure-summary">
            <h3>Exposure Summary</h3>
            <div className="exposure-metrics">
              <div className="metric">
                <span>Gross Exposure</span>
                <span>{(metrics.gross_exposure * 100).toFixed(1)}%</span>
                <span className={metrics.gross_exposure < (config?.max_gross_exposure || 1) ? "ok" : "warning"}>
                  {metrics.gross_exposure < (config?.max_gross_exposure || 1) ? "Within Limit" : "EXCEEDS LIMIT"}
                </span>
              </div>
              <div className="metric">
                <span>Net Exposure</span>
                <span>{(metrics.net_exposure * 100).toFixed(1)}%</span>
              </div>
              <div className="metric">
                <span>Largest Position</span>
                <span>{metrics.concentration_risk[0]?.pct.toFixed(2) || 0}%</span>
                <span className={(metrics.concentration_risk[0]?.pct || 0) > 10 ? "warning" : "ok"}>
                  {(metrics.concentration_risk[0]?.pct || 0) > 10 ? "High Concentration" : "OK"}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "alerts" && (
        <div className="alerts-tab">
          <div className="alerts-header">
            <h2>Risk Alerts</h2>
            <div className="alert-summary">
              <span className="alert-count critical">{criticalAlerts.length} Critical</span>
              <span className="alert-count warning">{warningAlerts.length} Warning</span>
              <span className="alert-count info">{infoAlerts.length} Info</span>
            </div>
          </div>

          <div className="alerts-list">
            {[
              ...criticalAlerts.map(a => ({...a, priority: 0})),
              ...warningAlerts.map(a => ({...a, priority: 1})),
              ...infoAlerts.map(a => ({...a, priority: 2})),
            ].sort((a, b) => a.priority - b.priority).map(alert => (
              <div key={alert.id} className={`alert-item ${ALERT_TYPE_COLORS[alert.type]} ${alert.acknowledged ? "acknowledged" : ""}`}>
                <div className="alert-content">
                  <span className="alert-type">{alert.type.toUpperCase()}</span>
                  <span className="alert-message">{alert.message}</span>
                  <span className="alert-time">{new Date(alert.timestamp).toLocaleString()}</span>
                </div>
                {!alert.acknowledged && (
                  <button className="btn-acknowledge" onClick={() => acknowledgeAlert(alert.id)}>
                    Acknowledge
                  </button>
                )}
              </div>
            ))}
            {alerts.length === 0 && (
              <div className="empty-state">No active alerts</div>
            )}
          </div>
        </div>
      )}

      {activeTab === "config" && config && (
        <div className="config-tab">
          <h2>Risk Configuration</h2>
          
          <div className="config-section">
            <h3>Position Limits</h3>
            <div className="config-grid">
              <ConfigInput
                label="Max Position %"
                value={config.max_position_pct * 100}
                step={0.1}
                onChange={v => updateConfig({ max_position_pct: v / 100 })}
                suffix="%"
              />
              <ConfigInput
                label="Max Sector %"
                value={config.max_sector_pct * 100}
                step={0.1}
                onChange={v => updateConfig({ max_sector_pct: v / 100 })}
                suffix="%"
              />
              <ConfigInput
                label="Max Gross Exposure"
                value={config.max_gross_exposure * 100}
                step={0.1}
                onChange={v => updateConfig({ max_gross_exposure: v / 100 })}
                suffix="%"
              />
            </div>
          </div>

          <div className="config-section">
            <h3>Loss Limits</h3>
            <div className="config-grid">
              <ConfigInput
                label="Max Drawdown %"
                value={config.max_drawdown_pct * 100}
                step={0.1}
                onChange={v => updateConfig({ max_drawdown_pct: v / 100 })}
                suffix="%"
              />
              <ConfigInput
                label="Daily Loss Limit %"
                value={config.daily_loss_limit_pct * 100}
                step={0.1}
                onChange={v => updateConfig({ daily_loss_limit_pct: v / 100 })}
                suffix="%"
              />
              <ConfigInput
                label="VaR Limit (95%)"
                value={config.var_limit_95}
                step={1000}
                onChange={v => updateConfig({ var_limit_95: v })}
              />
            </div>
          </div>

          <div className="config-section">
            <h3>Kill Switch</h3>
            <div className="kill-switch-control">
              <label className={`kill-switch ${config.kill_switch_active ? "active" : ""}`}>
                <input
                  type="checkbox"
                  checked={config.kill_switch_active}
                  onChange={() => toggleKillSwitch()}
                />
                <span className="slider"></span>
                <span className="kill-switch-label">
                  {config.kill_switch_active ? "ACTIVE - All orders blocked" : "INACTIVE - Normal operation"}
                </span>
              </label>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, subValue, change, changeLabel, isPositive = true }: {
  label: string;
  value: string;
  subValue?: string;
  change?: number;
  changeLabel?: string;
  isPositive?: boolean;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {subValue && <div className="metric-sub">{subValue}</div>}
      {change !== undefined && changeLabel && (
        <div className={`metric-change ${isPositive ? "positive" : "negative"}`}>
          {change >= 0 ? "+" : ""}{change.toFixed(2)}% {changeLabel}
        </div>
      )}
    </div>
  );
}

function ConfigInput({ label, value, step, onChange, suffix }: {
  label: string;
  value: number;
  step: number;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  return (
    <div className="config-input-group">
      <label>{label}{suffix && <span className="suffix">{suffix}</span>}</label>
      <input
        type="number"
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
      />
    </div>
  );
}