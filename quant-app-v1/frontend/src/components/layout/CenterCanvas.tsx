import { useRef } from "react";
import { ChartContainer } from "../../components/ChartContainer";
import { Scanner } from "../../components/Scanner";
import { AssetSelector } from "../../components/features/AssetSelector";
import { PaperTrading } from "../../components/features/PaperTrading";

interface CenterCanvasProps {
  activeView: string;
  selectedSymbol: string;
}

const VIEW_COMPONENTS: Record<string, React.ReactNode> = {
  overview: (
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
  ),
  scanner: (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Scanner</h1>
        <p className="view-description">Search and filter instruments</p>
      </div>
      <Scanner onPickSymbol={(symbol) => window.dispatchEvent(new CustomEvent("symbol-select", { detail: symbol }))} />
    </div>
  ),
  markets: (
    <div className="canvas-view">
      <div className="view-header">
        <div className="view-title-group">
          <h1>Markets</h1>
          <AssetSelector value={""} onChange={() => {}} />
        </div>
      </div>
      <div className="markets-content">
        <ChartContainer ticker="" />
      </div>
    </div>
  ),
  calendar: (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Calendar</h1>
        <p className="view-description">Economic events and earnings calendar</p>
      </div>
      <div className="calendar-content">
        <div className="empty-state">Calendar view coming soon. Integrate with licensed economic calendar provider.</div>
      </div>
    </div>
  ),
  strategies: (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Strategies</h1>
        <p className="view-description">Create, test, and manage trading strategies</p>
      </div>
      <div className="strategies-content">
        <div className="empty-state">Strategy Studio coming soon. Build visual strategies with typed specifications.</div>
      </div>
    </div>
  ),
  backtests: (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Backtests</h1>
        <p className="view-description">Run and analyze backtests</p>
      </div>
      <div className="backtests-content">
        <div className="empty-state">Backtest runner coming soon. Credible backtesting with reproducible receipts.</div>
      </div>
    </div>
  ),
  "paper-trading": (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Paper Trading</h1>
        <p className="view-description">Simulated portfolio and order management</p>
      </div>
      <PaperTrading />
    </div>
  ),
  journal: (
    <div className="canvas-view">
      <div className="view-header">
        <h1>Journal</h1>
        <p className="view-description">Trade journal and post-trade review</p>
      </div>
      <div className="journal-content">
        <div className="empty-state">Trade journal coming soon. Connect hypothesis, execution, and review.</div>
      </div>
    </div>
  ),
};

export function CenterCanvas({ activeView, selectedSymbol: _selectedSymbol }: CenterCanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);

  return (
    <div className="center-canvas-inner" ref={canvasRef}>
      {VIEW_COMPONENTS[activeView] || VIEW_COMPONENTS.overview}
    </div>
  );
}