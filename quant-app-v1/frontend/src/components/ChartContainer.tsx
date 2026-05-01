import { useCallback, useEffect, useState } from "react";

import { useHistory } from "../hooks/useHistory";
import { useSocket } from "../hooks/useSocket";
import type { PatternSignal } from "../types/market";

import { MainChart } from "./charts/MainChart";
import { IndicatorOverlay } from "./charts/IndicatorOverlay";
import { PatternList } from "./features/PatternList";

export interface ChartContainerProps {
  ticker: string;
}

/** Single `/ws/trading` subscription shared by the chart, RSI chip, and optional pattern feed. */
export function ChartContainer({ ticker }: ChartContainerProps) {
  const { data, loading, error } = useHistory(ticker);
  const liveUpdate = useSocket(ticker);
  const [patterns, setPatterns] = useState<PatternSignal[]>([]);

  useEffect(() => {
    setPatterns([]);
  }, [ticker]);

  useEffect(() => {
    if (!liveUpdate?.pattern_detected) return;
    const label = liveUpdate.pattern_label ?? "Pattern signal";
    const sentiment = typeof liveUpdate.rsi === "number" && liveUpdate.rsi >= 50 ? 1 : -1;
    setPatterns((prev) =>
      [{ name: label, sentiment, timestamp: liveUpdate.time }, ...prev].slice(0, 30),
    );
  }, [liveUpdate]);

  const handleZoomToPattern = useCallback((ts: number) => {
    window.console.info("zoomToPattern — connect chart timeScale", ts);
  }, []);

  const rsi = liveUpdate?.rsi ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
      {error ? (
        <div
          role="alert"
          style={{
            padding: "0.5rem 0.65rem",
            borderRadius: "6px",
            border: "1px solid #a371f7",
            background: "#1c1427",
            color: "#f0883e",
            fontSize: "0.875rem",
          }}
        >
          History: {error}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: "0.65rem", flexWrap: "wrap", alignItems: "center" }}>
        <IndicatorOverlay rsi={rsi} />
        <span style={{ color: "#6e7681", fontSize: "0.8rem" }}>
          Live stream: <code>/ws/trading</code>
        </span>
      </div>
      <MainChart ticker={ticker} historyData={data} loading={loading} liveUpdate={liveUpdate} />
      <PatternList activePatterns={patterns} onZoomToPattern={handleZoomToPattern} />
    </div>
  );
}
