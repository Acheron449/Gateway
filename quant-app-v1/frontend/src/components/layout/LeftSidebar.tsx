import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { VIEWS, type View } from "../../lib/views";

interface LeftSidebarProps {
  activeView: View;
  /** Compact icon rail mode (drag handle collapsed the panel). */
  collapsed: boolean;
}

const GROUPS: { id: "workspace" | "myWork" | "settings"; label: string }[] = [
  { id: "workspace", label: "Workspace" },
  { id: "myWork", label: "My Work" },
  { id: "settings", label: "Settings" },
];

const WATCHLIST_DEFAULTS = [
  { id: "default", name: "Default", symbols: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"] },
  { id: "tech", name: "Tech Giants", symbols: ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN"] },
  { id: "etf", name: "Major ETFs", symbols: ["SPY", "QQQ", "IWM", "VTI", "ARKK", "XLF"] },
] as const;

/**
 * Left workspace sidebar. In rail mode (issue #7) only section icons show;
 * clicking a rail icon expands that section and navigates to its first view.
 */
export function LeftSidebar({ activeView, collapsed }: LeftSidebarProps) {
  const navigate = useNavigate();
  const [activeWatchlist, setActiveWatchlist] = useState("default");
  const [expandedSections, setExpandedSections] = useState({
    workspace: true,
    myWork: true,
    watchlists: true,
    settings: true,
  });

  const toggleSection = (section: "workspace" | "myWork" | "watchlists" | "settings") => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const goTo = (view: View) => navigate(`/app/${view}`);
  const currentWatchlist = WATCHLIST_DEFAULTS.find((w) => w.id === activeWatchlist) || WATCHLIST_DEFAULTS[0];

  if (collapsed) {
    return (
      <nav className="left-sidebar rail" aria-label="Workspace rail">
        {GROUPS.map((group) => {
          const views = VIEWS.filter((v) => v.group === group.id);
          const groupActive = views.some((v) => v.id === activeView);
          return (
            <div className="rail-group" key={group.id}>
              <div className="rail-divider" aria-hidden="true" />
              {views.map((view) => (
                <button
                  key={view.id}
                  className={`rail-icon ${activeView === view.id ? "active" : ""} ${groupActive ? "in-group" : ""}`}
                  onClick={() => goTo(view.id)}
                  title={view.label}
                  aria-label={view.label}
                >
                  <span aria-hidden="true">{view.icon}</span>
                </button>
              ))}
            </div>
          );
        })}
        <div className="rail-footer">
          <button
            className="rail-icon"
            onClick={() => navigate("/")}
            title="About Gateway"
            aria-label="About Gateway"
          >
            <span aria-hidden="true">⚡</span>
          </button>
        </div>
      </nav>
    );
  }

  return (
    <nav className="left-sidebar" aria-label="Workspace">
      {GROUPS.map((group) => {
        const sectionKey = group.id as "workspace" | "myWork" | "settings";
        const views = VIEWS.filter((v) => v.group === group.id);
        const isOpen = expandedSections[sectionKey];
        return (
          <div className="sidebar-section" key={group.id}>
            <button
              className="section-header"
              onClick={() => toggleSection(sectionKey)}
              aria-expanded={isOpen}
            >
              <span className="section-icon">{isOpen ? "▼" : "▶"}</span>
              <span className="section-title">{group.label}</span>
            </button>
            {isOpen && (
              <ul className="nav-list" role="listbox" aria-label={group.label}>
                {views.map((item) => (
                  <li key={item.id} role="option" aria-selected={activeView === item.id}>
                    <button
                      className={`nav-button ${activeView === item.id ? "active" : ""}`}
                      onClick={() => goTo(item.id)}
                    >
                      <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                      <span className="nav-label">{item.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}

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
                  className={`symbol-chip ${symbol === "AAPL" ? "active" : ""}`}
                  onClick={() => goTo("markets")}
                  role="option"
                  aria-selected={symbol === "AAPL"}
                  title={`Chart ${symbol}`}
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
          <kbd>⌘K</kbd> Search & commands
        </div>
      </div>
    </nav>
  );
}
