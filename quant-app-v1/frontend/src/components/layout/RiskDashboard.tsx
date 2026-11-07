import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE } from "../../lib/constants";
import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";

/**
 * Risk Dashboard — equity, drawdown and exposure for the signed-in account's
 * paper portfolio. Every number comes from `GET /portfolio/risk`, which
 * replays the portfolio's own ledger and fill events server-side; nothing on
 * this page is generated in the browser.
 */

interface EquityPoint {
  time: string;
  equity: number;
  cash: number;
}

interface DrawdownPoint {
  time: string;
  drawdown: number;
}

interface RiskPosition {
  instrument_id: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  pct_of_equity: number;
}

interface PortfolioRisk {
  portfolio_id: string;
  generated_at: string;
  equity: number;
  cash: number;
  buying_power: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  total_return_pct: number;
  max_drawdown: number;
  current_drawdown: number;
  open_positions: number;
  gross_exposure: number;
  net_exposure: number;
  var_95: number;
  var_99: number;
  var_95_amount: number;
  var_99_amount: number;
  concentration_risk: { symbol: string; pct: number }[];
  equity_curve: EquityPoint[];
  drawdown_curve: DrawdownPoint[];
  positions: RiskPosition[];
  series_note: string;
}

function money(value: number): string {
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function signedPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toneClass(value: number): string {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Equity path with the first value as a dashed reference. */
function EquityChart({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) {
    return <p className="report-empty">No equity path recorded yet — place a simulated fill to start the curve.</p>;
  }
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(max * 0.01, 1);
  const width = 720;
  const height = 170;
  const x = (index: number) => (index / (points.length - 1)) * width;
  const y = (value: number) => height - ((value - min) / span) * (height - 14) - 7;
  const path = points.map((point, index) => `${x(index).toFixed(1)},${y(point.equity).toFixed(1)}`).join(" ");
  const baseline = y(points[0]!.equity);
  const up = points[points.length - 1]!.equity >= points[0]!.equity;

  return (
    <svg
      className="report-chart risk-chart risk-equity-chart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Equity curve"
      data-equity-points={points.length}
    >
      <line x1={0} y1={baseline} x2={width} y2={baseline} className="report-chart-base" />
      <polyline points={path} className={`report-chart-line ${up ? "" : "down"}`} />
    </svg>
  );
}

/** Drawdown from the running peak, drawn downward from zero. */
function DrawdownChart({ points }: { points: DrawdownPoint[] }) {
  if (points.length < 2) {
    return <p className="report-empty">No drawdown path recorded yet.</p>;
  }
  const worst = Math.min(...points.map((point) => point.drawdown));
  const span = Math.abs(worst) || 1;
  const width = 720;
  const height = 120;
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = (Math.abs(point.drawdown) / span) * (height - 10) + 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const area = `0,0 ${path} ${width},0`;

  return (
    <svg
      className="report-chart report-drawdown risk-chart risk-drawdown-chart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Drawdown curve"
      data-drawdown-points={points.length}
    >
      <polygon points={area} className="report-drawdown-area" />
      <polyline points={path} className="report-chart-line down" />
    </svg>
  );
}

function Metric({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <div className="risk-metric">
      <span className="risk-metric-label">{label}</span>
      <span className={`risk-metric-value ${tone ?? ""}`}>{value}</span>
      {note && <span className="risk-metric-note">{note}</span>}
    </div>
  );
}

export function RiskDashboard() {
  const { token, isAuthenticated } = useAuth();
  const { openAuth } = useAuthUI();
  const [risk, setRisk] = useState<PortfolioRisk | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRisk = useCallback(async () => {
    if (!token) {
      setRisk(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/portfolio/risk`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail || `HTTP ${response.status}`);
      }
      setRisk((await response.json()) as PortfolioRisk);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the risk series");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void loadRisk();
  }, [loadRisk]);

  const concentration = useMemo(() => risk?.concentration_risk ?? [], [risk]);
  const positions = useMemo(() => risk?.positions ?? [], [risk]);

  return (
    <div className="canvas-view risk-dashboard">
      <div className="view-header">
        <h1>Risk</h1>
        <p className="view-description">
          Equity, drawdown and exposure for your paper portfolio, replayed from its recorded fills and cash
          flows — no hypothetical numbers.
        </p>
      </div>

      {!isAuthenticated && (
        <section className="risk-signin" aria-label="Sign in required">
          <h2>Sign in to see your risk</h2>
          <p>The equity curve and drawdown path belong to your own paper portfolio, so they need an account.</p>
          <button type="button" className="btn-primary" onClick={() => openAuth("login")}>
            Sign in
          </button>
        </section>
      )}

      {isAuthenticated && loading && !risk && <p className="risk-note">Loading risk series…</p>}

      {isAuthenticated && error && (
        <section className="risk-error" role="alert">
          <strong>Could not load the risk series.</strong>
          <span>{error}</span>
          <button type="button" className="btn-secondary" onClick={() => void loadRisk()}>
            Retry
          </button>
        </section>
      )}

      {isAuthenticated && risk && (
        <>
          <div className="risk-metrics">
            <Metric label="Portfolio equity" value={money(risk.equity)} note={risk.portfolio_id} />
            <Metric label="Cash" value={money(risk.cash)} note={`Buying power ${money(risk.buying_power)}`} />
            <Metric
              label="Daily P&L"
              value={money(risk.daily_pnl)}
              note={signedPct(risk.daily_pnl_pct)}
              tone={toneClass(risk.daily_pnl)}
            />
            <Metric
              label="Total return"
              value={signedPct(risk.total_return_pct)}
              tone={toneClass(risk.total_return_pct)}
            />
            <Metric
              label="Current drawdown"
              value={`${risk.current_drawdown.toFixed(2)}%`}
              note={`Max ${risk.max_drawdown.toFixed(2)}%`}
              tone={risk.current_drawdown > 0 ? "down" : ""}
            />
            <Metric
              label="Gross exposure"
              value={`${(risk.gross_exposure * 100).toFixed(1)}%`}
              note={`Net ${(risk.net_exposure * 100).toFixed(1)}% · ${risk.open_positions} open`}
            />
            <Metric
              label="VaR (95%)"
              value={money(risk.var_95_amount)}
              note={`${risk.var_95.toFixed(2)}% daily · 99% ${risk.var_99.toFixed(2)}%`}
            />
          </div>

          <div className="risk-charts">
            <figure>
              <figcaption>Equity curve</figcaption>
              <EquityChart points={risk.equity_curve} />
              <div className="risk-chart-axis">
                <span>{shortDate(risk.equity_curve[0]!.time)}</span>
                <span>{shortDate(risk.equity_curve[risk.equity_curve.length - 1]!.time)}</span>
              </div>
            </figure>
            <figure>
              <figcaption>Drawdown from peak</figcaption>
              <DrawdownChart points={risk.drawdown_curve} />
              <div className="risk-chart-axis">
                <span>{risk.max_drawdown.toFixed(2)}% worst</span>
                <span>{risk.current_drawdown.toFixed(2)}% current</span>
              </div>
            </figure>
          </div>

          <p className="risk-note">{risk.series_note}</p>

          <section className="risk-positions" aria-label="Open positions">
            <h2>Positions</h2>
            {positions.length === 0 ? (
              <p className="report-empty">No open positions in this portfolio.</p>
            ) : (
              <table className="report-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Quantity</th>
                    <th>Avg cost</th>
                    <th>Market value</th>
                    <th>Unrealized</th>
                    <th>% of equity</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((position) => (
                    <tr key={position.instrument_id}>
                      <th scope="row">{position.instrument_id}</th>
                      <td>{position.quantity.toLocaleString()}</td>
                      <td>{money(position.avg_cost)}</td>
                      <td>{money(position.market_value)}</td>
                      <td className={toneClass(position.unrealized_pnl)}>{money(position.unrealized_pnl)}</td>
                      <td>{position.pct_of_equity.toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="risk-positions" aria-label="Concentration">
            <h2>Concentration</h2>
            {concentration.length === 0 ? (
              <p className="report-empty">Nothing held, so there is no concentration to report.</p>
            ) : (
              <table className="report-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>% of equity</th>
                  </tr>
                </thead>
                <tbody>
                  {concentration.map((row) => (
                    <tr key={row.symbol}>
                      <th scope="row">{row.symbol}</th>
                      <td>{row.pct.toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
