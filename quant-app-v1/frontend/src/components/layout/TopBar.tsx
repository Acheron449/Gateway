import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../context/AuthContext";

type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal" | "risk" | "divergence" | "settings";

interface TopBarProps {
  activeView: View;
  setActiveView: (view: View) => void;
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
  user: { id: string; email: string; name?: string } | null;
  isAuthenticated: boolean;
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
  { id: "risk", label: "Risk", icon: "⚠️" },
  { id: "divergence", label: "Divergence", icon: "📉" },
  { id: "settings", label: "Settings", icon: "🔧" },
] as const;

export function TopBar({
  activeView,
  setActiveView,
  selectedSymbol,
  setSelectedSymbol,
  user,
  isAuthenticated,
}: TopBarProps) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [symbolInput, setSymbolInput] = useState(selectedSymbol);
  const symbolInputRef = useRef<HTMLInputElement>(null);
  const [showUserMenu, setShowUserMenu] = useState(false);

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

  const handleLogout = useCallback(() => {
    logout();
    setShowUserMenu(false);
    navigate("/overview");
  }, [logout, navigate]);

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
          {isAuthenticated && user ? (
            <>
              <button
                className="user-avatar"
                aria-label="User menu"
                onClick={() => setShowUserMenu(!showUserMenu)}
              >
                <span className="avatar-initial">{user.name?.[0]?.toUpperCase() || user.email?.[0]?.toUpperCase() || "U"}</span>
              </button>
              {showUserMenu && (
                <div className="user-dropdown">
                  <div className="user-dropdown-header">
                    <span className="user-dropdown-name">{user.name || user.email}</span>
                    <span className="user-dropdown-email">{user.email}</span>
                  </div>
                  <button className="user-dropdown-item" onClick={handleLogout}>
                    <span>🚪</span> Logout
                  </button>
                </div>
              )}
            </>
          ) : (
            <button className="user-avatar" aria-label="Login" onClick={() => navigate("/login")}>
              <span className="avatar-initial">👤</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}