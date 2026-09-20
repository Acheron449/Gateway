import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";

type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal";

interface TopBarProps {
  activeView: View;
  setActiveView: (view: View) => void;
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
}

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "🏠" },
  { id: "scanner", label: "Scanner", icon: "🔍" },
  { id: "markets", label: "Markets", icon: "📈" },
  { id: "calendar", label: "Calendar", icon: "📅" },
  { id: "strategies", label: "Strategies", icon: "🎯" },
  { id: "backtests", label: "Backtests", icon: "📊" },
  { id: "paper-trading", label: "Paper Trading", icon: "📝" },
  { id: "journal", label: "Journal", icon: "📓" },
] as const;

export function TopBar({
  activeView,
  setActiveView,
  selectedSymbol,
  setSelectedSymbol,
}: TopBarProps) {
  const navigate = useNavigate();
  const [symbolInput, setSymbolInput] = useState(selectedSymbol);
  const symbolInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSymbolInput(selectedSymbol);
  }, [selectedSymbol]);

  const handleSymbolSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const symbol = symbolInput.trim().toUpperCase();
    if (symbol) {
      setSelectedSymbol(symbol);
      navigate(`/${activeView}?symbol=${symbol}`);
    }
  }, [symbolInput, activeView, navigate, setSelectedSymbol]);

  const handleNavClick = useCallback((viewId: View) => {
    setActiveView(viewId);
    navigate(`/${viewId}?symbol=${selectedSymbol}`);
  }, [navigate, selectedSymbol, setActiveView]);

  return (
    <header className="top-bar" role="banner">
      <div className="top-bar-left">
        <div className="app-title" onClick={() => navigate("/overview?symbol=" + selectedSymbol)} title="Go to Overview">
          <span className="app-icon">⚡</span>
          <span className="app-name">Gateway</span>
        </div>
        <nav className="main-nav" role="navigation" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? "active" : ""}`}
              onClick={() => handleNavClick(item.id as View)}
              aria-current={activeView === item.id ? "page" : undefined}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </button>
          ))}
        </nav>
      </div>

      <div className="top-bar-center">
        <form onSubmit={handleSymbolSubmit} className="symbol-search">
          <label htmlFor="symbol-input" className="sr-only">Symbol</label>
          <input
            ref={symbolInputRef}
            id="symbol-input"
            type="text"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            placeholder="Symbol (⌘K to search)"
            className="symbol-input"
            aria-label="Search symbol"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                (e.target as HTMLInputElement).blur();
              }
            }}
          />
          <span className="search-hint" aria-hidden="true">⌘K</span>
        </form>
      </div>

      <div className="top-bar-right">
        <div className="execution-mode">
          <span className="mode-badge paper">Paper</span>
        </div>
        <div className="user-menu">
          <button className="user-avatar" aria-label="User menu">
            <span className="avatar-initial">U</span>
          </button>
        </div>
      </div>
    </header>
  );
}