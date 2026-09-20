import { useState } from "react";
import Shell from "./components/layout/Shell";
import { ChartContainer } from "./components/ChartContainer";
import { Scanner } from "./components/Scanner";
import ScannerV2 from "./components/features/ScannerV2";
import { AssetSelector } from "./components/features/AssetSelector";
import { NewsTerminal } from "./components/features/NewsTerminal";
import { PaperTrading } from "./components/features/PaperTrading";
import useWorkspace from "./hooks/useWorkspace";

export default function App() {
  const [ticker, setTicker] = useState("AAPL");
  const [activeKey, setActiveKey] = useState("overview");
  const [activeTab, setActiveTab] = useState<"charts" | "paper">("charts");

  const ws = useWorkspace(ticker);

  const renderContent = () => {
    if (activeKey === "overview") {
      return (
        <>
          <header style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "flex-end", marginBottom: 12 }}>
            <AssetSelector value={ticker} onChange={setTicker} />
            <Scanner onPickSymbol={setTicker} />
            <div style={{ display: "flex", gap: "0.5rem", marginLeft: "auto" }}>
              <button
                onClick={() => setActiveTab("charts")}
                className={`px-4 py-2 rounded-t-lg ${activeTab === "charts" ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-700 hover:bg-gray-300"}`}
              >
                Charts
              </button>
              <button
                onClick={() => setActiveTab("paper")}
                className={`px-4 py-2 rounded-t-lg ${activeTab === "paper" ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-700 hover:bg-gray-300"}`}
              >
                Paper Trading
              </button>
            </div>
          </header>
          {activeTab === "charts" && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                {["research", "strategy", "backtest"].map((t) => (
                  <button key={t} onClick={() => ws.setTab(t)} style={{ padding: "0.35rem 0.7rem", borderRadius: 6, border: "1px solid rgba(255,255,255,0.12)", background: ws.tab === t ? "#633cff" : "#0d1117", color: "#e6edf3", fontSize: 12, cursor: "pointer", textTransform: "capitalize" }}>{t}</button>
                ))}
              </div>
              <ChartContainer ticker={ticker} />
              <NewsTerminal ticker={ticker} />
            </>
          )}
          {activeTab === "paper" && <PaperTrading />}
        </>
      );
    }
    if (activeKey === "scanner") {
      return <ScannerV2 />;
    }
    if (activeKey === "paper") {
      return <PaperTrading />;
    }
    return (
      <div style={{ color: "#8b949e" }}>
        <h2 style={{ fontSize: 18, marginBottom: 8 }}>{activeKey}</h2>
        <p>Placeholder for {activeKey} — Slice 1.{activeKey === "markets" ? 2 : 3} delivers full workspace.</p>
      </div>
    );
  };

  return (
    <Shell activeKey={activeKey} onNavigate={setActiveKey}>
      {renderContent()}
    </Shell>
  );
}
