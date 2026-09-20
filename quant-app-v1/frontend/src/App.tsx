import { useState } from "react";

import { ChartContainer } from "./components/ChartContainer";
import { Scanner } from "./components/Scanner";
import { AssetSelector } from "./components/features/AssetSelector";
import { NewsTerminal } from "./components/features/NewsTerminal";
import { PaperTrading } from "./components/features/PaperTrading";

export default function App() {
  const [ticker, setTicker] = useState("AAPL");
  const [activeTab, setActiveTab] = useState<"charts" | "paper">("charts");

  return (
    <div style={{ padding: "1rem", maxWidth: "1400px", margin: "0 auto", display: "grid", gap: "1rem" }}>
      <header style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "flex-end" }}>
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
          <ChartContainer ticker={ticker} />
          <NewsTerminal ticker={ticker} />
        </>
      )}
      {activeTab === "paper" && <PaperTrading />}
    </div>
  );
}
