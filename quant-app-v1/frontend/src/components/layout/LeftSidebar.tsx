import { useState } from "react";

type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal";

interface LeftSidebarProps {
  activeView: View;
  setActiveView: (view: View) => void;
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
}

const WATCHLIST_DEFAULTS = [
  { id: "default", name: "Default", symbols: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"] },
  { id: "tech", name: "Tech Giants", symbols: ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN"] },
  { id: "etf", name: "Major ETFs", symbols: ["SPY", "QQQ", "IWM", "VTI", "ARKK", "XLF"] },
] as const;

export function LeftSidebar({
  activeView,
  setActiveView,
  selectedSymbol,
  setSelectedSymbol,
}: LeftSidebarProps) {
  const [activeWatchlist, setActiveWatchlist] = useState("default");
  const [expandedSections, setExpandedSections] = useState({
    workspace: true,
    myWork: true,
    watchlists: true,
  });

  const toggleSection = (section: "workspace" | "myWork" | "watchlists") => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const currentWatchlist = WATCHLIST_DEFAULTS.find((w) => w.id === activeWatchlist) || WATCHLIST_DEFAULTS[0];

  return (
    <div className="left-sidebar">
      <div className="sidebar-section">
        <button
          className="section-header"
          onClick={() => toggleSection("workspace")}
          aria-expanded={expandedSections.workspace}
        >
          <span className="section-icon">{expandedSections.workspace ? "▼" : "▶"}</span>
          <span className="section-title">Workspace</span>
        </button>
        {expandedSections.workspace && (
          <ul className="nav-list" role="listbox" aria-label="Workspace views">
            {[
              { id: "overview", label: "Overview", icon: "🏠" },
              { id: "scanner", label: "Scanner", icon: "🔍" },
              { id: "markets", label: "Markets", icon: "📈" },
              { id: "calendar", label: "Calendar", icon: "📅" },
            ].map((item) => (
              <li key={item.id} role="option" aria-selected={activeView === item.id}>
                <button
                  className={`nav-button ${activeView === item.id ? "active" : ""}`}
                  onClick={() => setActiveView(item.id as View)}
                >
                  <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                  <span className="nav-label">{item.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sidebar-section">
        <button
          className="section-header"
          onClick={() => toggleSection("myWork")}
          aria-expanded={expandedSections.myWork}
        >
          <span className="section-icon">{expandedSections.myWork ? "▼" : "▶"}</span>
          <span className="section-title">My Work</span>
        </button>
        {expandedSections.myWork && (
          <ul className="nav-list" role="listbox" aria-label="My Work">
            {[
              { id: "strategies", label: "Strategies", icon: "🎯" },
              { id: "backtests", label: "Backtests", icon: "📊" },
              { id: "paper-trading", label: "Paper Trading", icon: "📝" },
              { id: "journal", label: "Journal", icon: "📓" },
            ].map((item) => (
              <li key={item.id} role="option" aria-selected={activeView === item.id}>
                <button
                  className={`nav-button ${activeView === item.id ? "active" : ""}`}
                  onClick={() => setActiveView(item.id as View)}
                >
                  <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                  <span className="nav-label">{item.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sidebar-section">
        <div className="section-header-row">
          <button
            className="section-header"
            onClick={() => toggleSection("watchlists")}
            aria-expanded={expandedSections.watchlists}
          >
            <span className="section-icon">{expandedSections.watchlists ? "▼" : "▶"}</span>
            <span className="section-title">Watchlists</span>
          </button>
          <button className="icon-button" aria-label="Add watchlist" title="New watchlist">
            +
          </button>
        </div>
        {expandedSections.watchlists && (
          <>
            <ul className="watchlist-tabs" role="tablist" aria-label="Watchlists">
              {WATCHLIST_DEFAULTS.map((wl) => (
                <li key={wl.id} role="tab" aria-selected={activeWatchlist === wl.id}>
                  <button
                    className={`watchlist-tab ${activeWatchlist === wl.id ? "active" : ""}`}
                    onClick={() => setActiveWatchlist(wl.id)}
                  >
                    {wl.name}
                  </button>
                </li>
              ))}
            </ul>
            <div className="watchlist-symbols" role="listbox" aria-label={`Symbols in ${currentWatchlist.name}`}>
              {currentWatchlist.symbols.map((symbol) => (
                <button
                  key={symbol}
                  className={`symbol-chip ${selectedSymbol === symbol ? "active" : ""}`}
                  onClick={() => setSelectedSymbol(symbol)}
                  role="option"
                  aria-selected={selectedSymbol === symbol}
                >
                  {symbol}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="sidebar-footer">
        <div className="shortcuts-hint">
          <kbd>⌘K</kbd> Command palette
        </div>
      </div>
    </div>
  );
}