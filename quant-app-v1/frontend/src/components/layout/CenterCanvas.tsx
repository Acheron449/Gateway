import { useRef } from "react";
import { ChartContainer } from "../../components/ChartContainer";
import { AssetSelector } from "../../components/features/AssetSelector";
import { PaperTrading } from "../../components/features/PaperTrading";
import { AiTrading } from "../../components/features/AiTrading";
import { CalendarView } from "./CalendarView";
import { AiHarness } from "./AiHarness";
import { AgenticLab } from "./AgenticLab";
import { OverviewDashboard } from "../../components/features/OverviewDashboard";
import { ScannerV2 } from "../../components/features/ScannerV2";
import { StrategyStudio } from "./StrategyStudio";
import { TradeJournal } from "./TradeJournal";
import { RiskDashboard } from "./RiskDashboard";
import { DivergenceScorecards } from "./DivergenceScorecards";
import { ProviderSettings } from "./ProviderSettings";

interface CenterCanvasProps {
  activeView: string;
  selectedSymbol: string;
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
          <div className="view-header">
            <div className="view-title-group">
              <h1>Markets</h1>
              <AssetSelector value={selectedSymbol} onChange={() => {}} />
            </div>
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
    case "agentic-lab":
      return (
        <div className="canvas-view canvas-view-wide">
          <AgenticLab selectedSymbol={selectedSymbol} />
        </div>
      );
    case "backtests":
      return (
        <div className="canvas-view">
          <div className="view-header">
            <h1>Backtests</h1>
            <p className="view-description">Run and analyze backtests</p>
          </div>
          <div className="backtests-content">
            <div className="empty-state">Backtest runner coming soon. Credible backtesting with reproducible receipts.</div>
          </div>
        </div>
      );
    case "paper-trading":
      return (
        <div className="canvas-view canvas-view-wide">
          <div className="view-header">
            <h1>Paper Trading</h1>
            <p className="view-description">Simulated portfolio and order management</p>
          </div>
          <PaperTrading selectedSymbol={selectedSymbol} />
        </div>
      );
    case "live-trading":
      return (
        <div className="canvas-view canvas-view-wide">
          <div className="view-header">
            <h1>Live Trading</h1>
            <p className="view-description">
              Real-money orders through your broker — the same desk as paper trading,
              with account, positions, orders and fills fed by the live account
              (UI patterned after professional terminals such as nautilus_trader).
            </p>
          </div>
          <PaperTrading selectedSymbol={selectedSymbol} mode="live" />
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
    case "risk":
      return (
        <div className="canvas-view">
          <RiskDashboard />
        </div>
      );
    case "divergence":
      return (
        <div className="canvas-view">
          <DivergenceScorecards />
        </div>
      );
    case "settings":
      return (
        <div className="canvas-view">
          <ProviderSettings />
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

export function CenterCanvas({ activeView, selectedSymbol }: CenterCanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);

  return (
    <div className="center-canvas-inner" ref={canvasRef}>
      {getViewComponent(activeView, selectedSymbol)}
    </div>
  );
}