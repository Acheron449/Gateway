interface RightInspectorProps {
  activeView: string;
  selectedSymbol: string;
}

const EMPTY_STATE_MESSAGES: Record<string, string> = {
  overview: "Select a view to see contextual information",
  scanner: "Select a symbol from the scanner to inspect",
  markets: "Select a symbol to view market details",
  calendar: "Upcoming economic events will appear here",
  strategies: "Select or create a strategy to see details",
  backtests: "Select a backtest run to see results",
  "paper-trading": "Paper trading details appear here",
  journal: "Select a trade to review",
};

export function RightInspector({ activeView, selectedSymbol }: RightInspectorProps) {
  if (!selectedSymbol) {
    return (
      <div className="inspector-empty">
        <div className="empty-icon">📋</div>
        <p className="empty-message">{EMPTY_STATE_MESSAGES[activeView] || EMPTY_STATE_MESSAGES.overview}</p>
      </div>
    );
  }

  return (
    <div className="inspector-content">
      <div className="inspector-header">
        <h2 className="inspector-title">{selectedSymbol}</h2>
        <span className="inspector-subtitle">{activeView} inspector</span>
      </div>

      <div className="inspector-sections">
        <section className="inspector-section">
          <h3 className="section-label">Price & Change</h3>
          <div className="price-display">
            <span className="price-value">$0.00</span>
            <span className="price-change neutral">0.00%</span>
          </div>
          <div className="price-meta">
            <span>Bid: $0.00</span>
            <span>Ask: $0.00</span>
            <span>Spread: 0.00%</span>
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Key Metrics</h3>
          <dl className="metrics-grid">
            <div><dt>Volume</dt><dd>—</dd></div>
            <div><dt>Avg Volume</dt><dd>—</dd></div>
            <div><dt>Market Cap</dt><dd>—</dd></div>
            <div><dt>P/E Ratio</dt><dd>—</dd></div>
            <div><dt>52W High</dt><dd>—</dd></div>
            <div><dt>52W Low</dt><dd>—</dd></div>
          </dl>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Next Events</h3>
          <div className="events-list">
            <div className="event-item">
              <span className="event-time">Today 10:00</span>
              <span className="event-title">Earnings Release</span>
              <span className="event-importance high">High</span>
            </div>
            <div className="event-item">
              <span className="event-time">Tomorrow 08:30</span>
              <span className="event-title">CPI Data</span>
              <span className="event-importance high">High</span>
            </div>
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Signals & Confidence</h3>
          <div className="signal-display">
            <div className="signal-bar">
              <span className="signal-label">Overall</span>
              <div className="signal-progress">
                <div className="signal-fill neutral" style={{ width: "50%" }}></div>
              </div>
              <span className="signal-value">50%</span>
            </div>
            <div className="signal-bar">
              <span className="signal-label">Technical</span>
              <div className="signal-progress">
                <div className="signal-fill neutral" style={{ width: "50%" }}></div>
              </div>
              <span className="signal-value">50%</span>
            </div>
            <div className="signal-bar">
              <span className="signal-label">Sentiment</span>
              <div className="signal-progress">
                <div className="signal-fill neutral" style={{ width: "50%" }}></div>
              </div>
              <span className="signal-value">50%</span>
            </div>
          </div>
        </section>

        <section className="inspector-section">
          <h3 className="section-label">Risk / Provenance</h3>
          <div className="provenance-info">
            <p className="provenance-item">Source: —</p>
            <p className="provenance-item">Fetched: —</p>
            <p className="provenance-item">Data Time: —</p>
            <p className="provenance-item">Delay: —</p>
          </div>
        </section>

        {activeView === "paper-trading" && (
          <section className="inspector-section order-preview">
            <h3 className="section-label">Paper Order Preview</h3>
            <div className="order-preview-content">
              <p className="preview-note">Use the Paper Trading tab to place orders</p>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}