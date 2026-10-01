import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../context/AuthContext";
import { useAuthUI } from "../../context/AuthUIContext";
import { SymbolTicker } from "./SymbolTicker";
import type { View } from "../../lib/views";

interface TopBarProps {
  activeView: View;
  selectedSymbol: string;
  onSymbolSelect: (symbol: string) => void;
  onOpenSearch: () => void;
}

/**
 * Slim ticker topbar (issue #9): brand → scrolling symbol strip with green/red
 * arrows, then a search magnifier (issue #4) and auth controls on the right.
 */
export function TopBar({ activeView, selectedSymbol, onSymbolSelect, onOpenSearch }: TopBarProps) {
  const { user, isAuthenticated, logout } = useAuth();
  const { openAuth } = useAuthUI();
  const navigate = useNavigate();

  const handleLogout = useCallback(() => {
    logout();
    navigate("/");
  }, [logout, navigate]);

  const initial = user?.name?.[0]?.toUpperCase() || user?.email?.[0]?.toUpperCase() || "U";

  return (
    <header className="top-bar" role="banner">
      <div className="top-bar-brand" onClick={() => navigate("/app/overview")} title="Overview">
        <span className="app-icon">⚡</span>
        <span className="app-name">Gateway</span>
      </div>

      <SymbolTicker
        selectedSymbol={selectedSymbol}
        onSelect={onSymbolSelect}
        contextView={activeView}
      />

      <div className="top-bar-actions">
        <button
          className="search-trigger"
          onClick={onOpenSearch}
          aria-label="Search symbols and commands"
          title="Search (⌘K)"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <line x1="16.5" y1="16.5" x2="21" y2="21" />
          </svg>
          <kbd className="search-kbd">⌘K</kbd>
        </button>

        {isAuthenticated && user ? (
          <div className="user-menu">
            <button className="user-avatar" aria-label="User menu" title={user.email} onClick={handleLogout}>
              <span className="avatar-initial">{initial}</span>
            </button>
          </div>
        ) : (
          <button className="signin-button" onClick={() => openAuth("login")}>
            Sign in
          </button>
        )}
      </div>
    </header>
  );
}
