import { useRef } from "react";
import { ChartContainer } from "../../components/ChartContainer";
import { AssetSelector } from "../../components/features/AssetSelector";
import { PaperTrading } from "../../components/features/PaperTrading";
import { CalendarView } from "./CalendarView";
import { NewsFeed } from "../../components/features/NewsFeed";
import { ScannerV2 } from "../../components/features/ScannerV2";
import { StrategyStudio } from "./StrategyStudio";
import { TradeJournal } from "./TradeJournal";
import { RiskDashboard } from "./RiskDashboard";
import { DivergenceScorecards } from "./DivergenceScorecards";

interface CenterCanvasProps {
  activeView: string;
  selectedSymbol: string;
}

function getViewComponent(activeView: string, selectedSymbol: string) {
  switch (activeView) {
    case "overview":
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
                <button className="action-button">Place Order</button>
                <button className="action-button">View Journal</button>
              </div>
            </div>
            <div className="overview-card">
              <h3>Market News</h3>
              <NewsFeed />
            </div>
            <div className="overview-card">
              <h3>Performance Summary</h3>
              <p className="empty-state">Run a backtest to see performance</p>
            </div>
          </div>
        </div>
      );
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
    case "strategies":
      return (
        <div className="canvas-view">
          <StrategyStudio />
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
        <div className="canvas-view">
          <div className="view-header">
            <h1>Paper Trading</h1>
            <p className="view-description">Simulated portfolio and order management</p>
          </div>
          <PaperTrading />
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
                <button className="action-button">Place Order</button>
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