import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../../lib/constants";
import { type BtRun } from "../../lib/backtestTypes";
import { LastUpdated } from "../../lib/LastUpdated";

const ChartContainer = lazy(() =>
  import("../../components/ChartContainer").then((module) => ({ default: module.ChartContainer })),
);
const AssetSelector = lazy(() =>
  import("../../components/features/AssetSelector").then((module) => ({ default: module.AssetSelector })),
);
const PaperTrading = lazy(() =>
  import("../../components/features/PaperTrading").then((module) => ({ default: module.PaperTrading })),
);
const TradingAccountStatus = lazy(() =>
  import("../../components/features/TradingAccountStatus").then((module) => ({
    default: module.TradingAccountStatus,
  })),
);
const AiTrading = lazy(() =>
  import("../../components/features/AiTrading").then((module) => ({ default: module.AiTrading })),
);
const CalendarView = lazy(() =>
  import("./CalendarView").then((module) => ({ default: module.CalendarView })),
);
const AiHarness = lazy(() =>
  import("./AiHarness").then((module) => ({ default: module.AiHarness })),
);
const AgenticLab = lazy(() =>
  import("./AgenticLab").then((module) => ({ default: module.AgenticLab })),
);
const OverviewDashboard = lazy(() =>
  import("../../components/features/OverviewDashboard").then((module) => ({
    default: module.OverviewDashboard,
  })),
);
const ScannerV2 = lazy(() =>
  import("../../components/features/ScannerV2").then((module) => ({ default: module.ScannerV2 })),
);
const StrategyStudio = lazy(() =>
  import("./StrategyStudio").then((module) => ({ default: module.StrategyStudio })),
);
const BacktestReports = lazy(() =>
  import("../features/BacktestReports").then((module) => ({ default: module.BacktestReports })),
);
const OptionsCalculator = lazy(() =>
  import("../features/OptionsCalculator").then((module) => ({ default: module.OptionsCalculator })),
);
const MonteCarloView = lazy(() =>
  import("../features/MonteCarloView").then((module) => ({ default: module.MonteCarloView })),
);
const OrderBookPanel = lazy(() =>
  import("../features/OrderBookPanel").then((module) => ({ default: module.OrderBookPanel })),
);
const RiskDashboard = lazy(() =>
  import("./RiskDashboard").then((module) => ({ default: module.RiskDashboard })),
);
const TradeJournal = lazy(() =>
  import("./TradeJournal").then((module) => ({ default: module.TradeJournal })),
);
const ProviderSettings = lazy(() =>
  import("./ProviderSettings").then((module) => ({ default: module.ProviderSettings })),
);
const IdleScreen = lazy(() =>
  import("./IdleScreen").then((module) => ({ default: module.IdleScreen })),
);

interface CenterCanvasProps {
  activeView: string;
  selectedSymbol: string;
}

function AgenticLabView({ selectedSymbol }: { selectedSymbol: string }) {
  const [runs, setRuns] = useState<BtRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const loadRuns = useCallback(async () => {
    setError(null);
    try {
      const token = localStorage.getItem("gateway_auth_token");
      const response = await fetch(`${API_BASE}/agentic-lab/runs?limit=50`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json() as { runs?: BtRun[] };
      setRuns(data.runs ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load lab runs");
    }
  }, []);
  useEffect(() => { void loadRuns(); }, [loadRuns]);
  return <AgenticLab selectedSymbol={selectedSymbol} runs={runs} error={error} onRefresh={loadRuns} />;
}

function getViewComponent(activeView: string, selectedSymbol: string) {
  switch (activeView) {
    case "overview":
      // Reference-style overview: ticker strip, chart, movers, news,
      // filings, risk, watchlist and heat map (see OverviewDashboard).
      return <OverviewDashboard selectedSymbol={selectedSymbol} />;
    case "scanner":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Scanner</h1>
            <p className="view-description">Search and filter instruments</p>
            <LastUpdated />
          </div>
          <ScannerV2
            onPickSymbol={(symbol: string) => window.dispatchEvent(new CustomEvent("symbol-select", { detail: symbol }))}
            selectedSymbol={selectedSymbol}
          />
        </div>
      );
    case "markets":
      return (
        <div className="canvas-view">
          <div className="view-header">              <div className="view-title-group">
                <h1>Markets</h1>
                <AssetSelector value={selectedSymbol} onChange={() => {}} />
              </div>
              <LastUpdated />
          </div>
          <div className="markets-content">
            <ChartContainer ticker={selectedSymbol} />
          </div>
        </div>
      );
    case "calendar":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Calendar</h1>
            <p className="view-description">Economic events and earnings calendar</p>
            <LastUpdated />
          </div>
          <CalendarView />
        </div>
      );
    case "harness":
      return (
        <div className="canvas-view canvas-view-wide">
          <AiHarness selectedSymbol={selectedSymbol} />
        </div>
      );
    case "strategies":
      return (
        <div className="canvas-view">
          <StrategyStudio />
        </div>
      );
    case "backtests":
      return <BacktestReports selectedSymbol={selectedSymbol} />;
    case "orderbook":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Order book</h1>
            <p className="view-description">
              A simulated ladder for {selectedSymbol} built from its last daily bars — a model output,
              not exchange data.
            </p>
          </div>
          <OrderBookPanel symbol={selectedSymbol} />
        </div>
      );
    case "monte-carlo":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Monte Carlo</h1>
            <p className="view-description">
              Percentile fan, tail loss, drawdown and ruin risk from resampling {selectedSymbol}'s own daily
              returns — a simulation, not a forecast.
            </p>
          </div>
          <MonteCarloView symbol={selectedSymbol} />
        </div>
      );
    case "options":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Options pricing</h1>
            <p className="view-description">
              European Black-Scholes value, greeks and implied volatility — a calculator over inputs you supply,
              not an options feed.
            </p>
          </div>
          <OptionsCalculator />
        </div>
      );
    case "agentic-lab":
      return (
        <div className="canvas-view canvas-view-wide">
          <AgenticLabView selectedSymbol={selectedSymbol} />
        </div>
      );
    case "paper-trading":
      return (
        <div className="canvas-view canvas-view-wide canvas-view-trading">
          <div className="trading-view-header view-header">
            <div className="trading-view-title">
              <h1>Paper Trading</h1>
              <p className="view-description">Simulated portfolio and order management</p>
            </div>
            <TradingAccountStatus mode="paper" />
          </div>
          <PaperTrading selectedSymbol={selectedSymbol} />
        </div>
      );
    case "risk":
      return <RiskDashboard />;
    case "live-trading":
      return (
        <div className="canvas-view canvas-view-wide canvas-view-trading">
          <div className="trading-view-header view-header">
            <div className="trading-view-title">
              <h1>Live execution unavailable</h1>
              <p className="view-description">
                Broker account and order routes are disabled until authenticated account ownership
                and durable order recovery are implemented. Use the separately labeled simulated-paper desk.
              </p>
            </div>
          </div>
          <section className="desk-card" role="status" aria-label="Broker execution unavailable">
            <h2>Live execution unavailable</h2>
            <p>No broker account data or order actions are available in this build.</p>
          </section>
        </div>
      );
    case "ai-trading":
      return (
        <div className="canvas-view canvas-view-wide">
          <div className="view-header">
            <h1>AI Trading</h1>
            <p className="view-description">
              Let the AI allocate funds and trade using lessons from past trades, data and backtests
            </p>
            <LastUpdated />
          </div>
          <AiTrading selectedSymbol={selectedSymbol} />
        </div>
      );
    case "journal":
      return (
        <div className="canvas-view">
          <TradeJournal />
        </div>
      );
    case "settings":
      return (
        <div className="canvas-view">
          <ProviderSettings />
          {/* Credentials page: black out after 15s without input. */}
          <IdleScreen />
        </div>
      );
    default:
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Overview</h1>
            <p className="view-description">Market overview and quick access</p>
          </div>
          <div className="overview-grid">
            <div className="overview-card">
              <h3>Quick Actions</h3>
              <div className="quick-actions">
                <button className="action-button">New Strategy</button>
                <button className="action-button">Run Backtest</button>
                <button className="action-button">View Journal</button>
              </div>
            </div>
            <div className="overview-card">
              <h3>Recent Activity</h3>
              <p className="empty-state">No recent activity</p>
            </div>
            <div className="overview-card">
              <h3>Performance Summary</h3>
              <p className="empty-state">Run a backtest to see performance</p>
            </div>
          </div>
        </div>
      );
  }
}

function CanvasLoading() {
  return (
    <div className="route-loading route-loading--inline" role="status" aria-live="polite">
      <span>Loading view…</span>
    </div>
  );
}

export function CenterCanvas({ activeView, selectedSymbol }: CenterCanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);

  // Trading desks own their own scrolling: the page itself stays put and only
  // the rail/watchlist/ticket/quote panels scroll internally.
  const fixed = activeView === "paper-trading" || activeView === "live-trading";

  return (
    <div
      className={`center-canvas-inner${fixed ? " center-canvas-fixed" : ""}`}
      ref={canvasRef}
    >
      <Suspense fallback={<CanvasLoading />}>
        {getViewComponent(activeView, selectedSymbol)}
      </Suspense>
    </div>
  );
}