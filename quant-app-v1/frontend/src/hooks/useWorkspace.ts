import { useState, useEffect } from "react";
export default function useWorkspace(symbol: string) {
  const [tab, setTab] = useState("research");
  const [timeframe, setTimeframe] = useState("1D");
  const [indicators, setIndicators] = useState<string[]>([]);
  const [inspectorWidth, setInspectorWidth] = useState(320);
  useEffect(() => { try { const s = JSON.parse(localStorage.getItem("gw_ws_" + symbol) || "{}"); if (s.tab) setTab(s.tab); } catch {} }, [symbol]);
  useEffect(() => { localStorage.setItem("gw_ws_" + symbol, JSON.stringify({ tab, timeframe, indicators, inspectorWidth })); }, [tab, timeframe, indicators, inspectorWidth, symbol]);
  return { tab, setTab, timeframe, setTimeframe, indicators, setIndicators, inspectorWidth, setInspectorWidth };
}
