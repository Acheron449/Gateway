import { BrowserRouter } from "react-router-dom";
import { useState, useEffect, useCallback } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { LeftSidebar } from "./components/layout/LeftSidebar";
import { CenterCanvas } from "./components/layout/CenterCanvas";
import { RightInspector } from "./components/layout/RightInspector";
import { CommandPalette } from "./components/layout/CommandPalette";
import { TopBar } from "./components/layout/TopBar";

import "./styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: false,
    },
  },
});

type Panel = "left" | "right";
type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal";

export default function App() {
  const [collapsedPanels, setCollapsedPanels] = useState<Set<Panel>>(new Set());
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [activeView, setActiveView] = useState<View>("overview");
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");

  const togglePanel = useCallback((panel: Panel) => {
    setCollapsedPanels((prev) => {
      const next = new Set(prev);
      if (next.has(panel)) {
        next.delete(panel);
      } else {
        next.add(panel);
      }
      return next;
    });
  }, []);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setCommandPaletteOpen(true);
    }
    if (e.key === "Escape") {
      setCommandPaletteOpen(false);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const isLeftCollapsed = collapsedPanels.has("left");
  const isRightCollapsed = collapsedPanels.has("right");

  const handleNavigate = useCallback((view: View) => {
    setActiveView(view);
    setCommandPaletteOpen(false);
  }, []);

  const handleSymbolSelect = useCallback((symbol: string) => {
    setSelectedSymbol(symbol);
    setCommandPaletteOpen(false);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="app-shell">
          <TopBar
            activeView={activeView}
            setActiveView={setActiveView}
            selectedSymbol={selectedSymbol}
            setSelectedSymbol={setSelectedSymbol}
          />
          <div className={`app-body ${isLeftCollapsed ? "left-collapsed" : ""} ${isRightCollapsed ? "right-collapsed" : ""}`}>
            {!isLeftCollapsed && (
              <aside className="panel left-panel" role="navigation" aria-label="Workspace">
                <LeftSidebar
                  activeView={activeView}
                  setActiveView={setActiveView}
                  selectedSymbol={selectedSymbol}
                  setSelectedSymbol={setSelectedSymbol}
                />
              </aside>
            )}
            <button
              className={`panel-toggle left-toggle ${isLeftCollapsed ? "collapsed" : ""}`}
              onClick={() => togglePanel("left")}
              aria-label={isLeftCollapsed ? "Expand workspace" : "Collapse workspace"}
              aria-expanded={!isLeftCollapsed}
            >
              {isLeftCollapsed ? "◀" : "▶"}
            </button>

            <main className="center-canvas" role="main" aria-label="Research canvas">
              <CenterCanvas
                activeView={activeView}
                selectedSymbol={selectedSymbol}
              />
            </main>

            {!isRightCollapsed && (
              <aside className="panel right-panel" role="complementary" aria-label="Decision inspector">
                <RightInspector
                  activeView={activeView}
                  selectedSymbol={selectedSymbol}
                />
              </aside>
            )}
            <button
              className={`panel-toggle right-toggle ${isRightCollapsed ? "collapsed" : ""}`}
              onClick={() => togglePanel("right")}
              aria-label={isRightCollapsed ? "Expand inspector" : "Collapse inspector"}
              aria-expanded={!isRightCollapsed}
            >
              {isRightCollapsed ? "▶" : "◀"}
            </button>
          </div>

          {commandPaletteOpen && (
            <CommandPalette
              onClose={() => setCommandPaletteOpen(false)}
              onNavigate={handleNavigate}
              onSymbolSelect={handleSymbolSelect}
              activeView={activeView}
              selectedSymbol={selectedSymbol}
            />
          )}
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}