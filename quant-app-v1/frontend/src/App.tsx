import { BrowserRouter } from "react-router-dom";
import { useState, useCallback } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { LeftSidebar } from "./components/layout/LeftSidebar";
import { CenterCanvas } from "./components/layout/CenterCanvas";
import { RightInspector } from "./components/layout/RightInspector";
import { TopBar } from "./components/layout/TopBar";
import { CommandPalette } from "./components/layout/CommandPalette";
import { AuthProvider, useAuth } from "./context/AuthContext";
import "./styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: false,
    },
  },
});

type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal" | "risk" | "divergence" | "settings";

function AppContent() {
  const { user, isAuthenticated } = useAuth();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [activeView, setActiveView] = useState<View>("overview");
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");

  const handleNavigate = useCallback((view: View) => {
    setActiveView(view);
    setCommandPaletteOpen(false);
  }, []);

  const handleSymbolSelect = useCallback((symbol: string) => {
    setSelectedSymbol(symbol);
    setCommandPaletteOpen(false);
  }, []);

  return (
    <div className={`app-shell view-accent-${activeView}`}>
      <TopBar
        activeView={activeView}
        setActiveView={setActiveView}
        selectedSymbol={selectedSymbol}
        setSelectedSymbol={setSelectedSymbol}
        user={user}
        isAuthenticated={isAuthenticated}
      />
      <div className="app-body">
        <LeftSidebar
          activeView={activeView}
          setActiveView={setActiveView}
          selectedSymbol={selectedSymbol}
          setSelectedSymbol={setSelectedSymbol}
        />
        <CenterCanvas
          activeView={activeView}
          selectedSymbol={selectedSymbol}
        />
        <RightInspector
          activeView={activeView}
          selectedSymbol={selectedSymbol}
        />
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
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}