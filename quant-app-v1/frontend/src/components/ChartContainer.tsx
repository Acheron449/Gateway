import { useCallback, useEffect, useState } from "react";

import { useHistory, HISTORY_TFS, type HistoryTf } from "../hooks/useHistory";
import { useSocket } from "../hooks/useSocket";
import { useChartPrefs } from "../lib/chartPrefs";
import { useRefreshMs } from "../lib/refresh";
import type { PatternSignal } from "../types/market";

import { MainChart } from "./charts/MainChart";
import { IndicatorOverlay } from "./charts/IndicatorOverlay";
import { IndicatorsButton } from "./charts/IndicatorPanel";
import { ProviderSelect } from "./charts/ProviderSelect";
import { PatternList } from "./features/PatternList";
import { KronosForecast } from "./features/KronosForecast";

export interface ChartContainerProps {
  ticker: string;
}

/** Markets timeframe → pandas frequency string expected by /forecast/kronos. */
const KRONOS_FREQ_BY_TF: Record<string, string> = {
  "1h": "h",
  "1d": "D",
  "1wk": "W",
};

export function ChartContainer({ ticker }: ChartContainerProps) {
  const [timeframe, setTimeframe] = useState<HistoryTf>("1h");
  // Bumped by the "Now" button → MainChart recenters on the latest candle.
  const [nowSignal, setNowSignal] = useState(0);
  const [{ provider, indicators }] = useChartPrefs();
  // User-selected refresh rate (Settings → Data refresh) keeps the chart polled.
  const refreshMs = useRefreshMs();
  const { data, loading, error } = useHistory(ticker, timeframe, 500, provider, refreshMs);
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
        <button
          className="tf-button chart-now-btn"
          onClick={() => setNowSignal((n) => n + 1)}
          title="Jump back to the most recent candle"
        >
          ⏱ Now
        </button>
        <ProviderSelect />
        <IndicatorsButton />
        <IndicatorOverlay rsi={rsi} />
        <span className="chart-feed-note">Native candle chart · live via <code>/ws/trading</code></span>
      </div>
      <MainChart
        ticker={ticker}
        historyData={data}
        loading={loading}
        liveUpdate={liveUpdate}
        indicators={indicators}
        nowSignal={nowSignal}
      />
      <KronosForecast
        bars={data}
        ticker={ticker}
        frequency={KRONOS_FREQ_BY_TF[timeframe] ?? "D"}
      />
      <PatternList activePatterns={patterns} onZoomToPattern={handleZoomToPattern} />
    </div>
  );
}
