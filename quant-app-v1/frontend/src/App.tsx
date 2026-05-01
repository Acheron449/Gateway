import { useState } from "react";

import { ChartContainer } from "./components/ChartContainer";
import { Scanner } from "./components/Scanner";
import { AssetSelector } from "./components/features/AssetSelector";
import { NewsTerminal } from "./components/features/NewsTerminal";

export default function App() {
  const [ticker, setTicker] = useState("AAPL");

  return (
    <div style={{ padding: "1rem", maxWidth: "1200px", margin: "0 auto", display: "grid", gap: "1rem" }}>
      <header style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "flex-end" }}>
        <AssetSelector value={ticker} onChange={setTicker} />
        <Scanner onPickSymbol={setTicker} />
      </header>
      <ChartContainer ticker={ticker} />
      <NewsTerminal ticker={ticker} />
    </div>
  );
}
