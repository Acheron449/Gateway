import { useCallback, useEffect, useState } from "react";

import { useHistory, HISTORY_TFS, type HistoryTf } from "../hooks/useHistory";
import { useSocket } from "../hooks/useSocket";
import type { PatternSignal } from "../types/market";

import { MainChart } from "./charts/MainChart";
import { IndicatorOverlay } from "./charts/IndicatorOverlay";
import { PatternList } from "./features/PatternList";
import { KronosForecast } from "./features/KronosForecast";

export interface ChartContainerProps {
  ticker: string;
}

export function ChartContainer({ ticker }: ChartContainerProps) {
  const [timeframe, setTimeframe] = useState<HistoryTf>("1h");
  const { data, loading, error } = useHistory(ticker, timeframe);
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

  // News and calendar events render in the right inspector / overview feed
  // instead of being drawn on the chart.

  const handleZoomToPattern = useCallback((ts: number) => {
    window.console.info("zoomToPattern — connect chart timeScale", ts);
  }, []);

  const rsi = liveUpdate?.rsi ?? null;

  return (
    <div className="chart-container">
      {error ? (
        <div className="chart-error" role="alert">
          Chart data: {error}
        </div>
      ) : null}
      <div className="chart-toolbar">
        <div className="tf-selector" role="group" aria-label="Chart timeframe">
          {HISTORY_TFS.map((tf) => (
            <button
              key={tf}
              className={`tf-button ${timeframe === tf ? "active" : ""}`}
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
        <IndicatorOverlay rsi={rsi} />
        <span className="chart-feed-note">Native candle chart · live via <code>/ws/trading</code></span>
      </div>
      <MainChart
        ticker={ticker}
        historyData={data}
        loading={loading}
        liveUpdate={liveUpdate}
      />
      <KronosForecast bars={data} />
      <PatternList activePatterns={patterns} onZoomToPattern={handleZoomToPattern} />
    </div>
  );
}
