import { ColorType, createChart } from "lightweight-charts";
import type {
  CandlestickData,
  IChartApi,
  ISeriesApi,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { LiveTradingUpdate } from "../../hooks/useSocket";
import type { HistoryCandle } from "../../types/market";

export interface MainChartProps {
  ticker: string;
  historyData: HistoryCandle[];
  loading: boolean;
  liveUpdate?: LiveTradingUpdate | null;
}

export function MainChart({ ticker, historyData, loading, liveUpdate }: MainChartProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<Array<SeriesMarker<Time>>>([]);

  useEffect(() => {
    const container = rootRef.current;
    if (!container || loading) return undefined;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0d1117" },
        textColor: "#c9d1d9",
      },
      grid: {
        vertLines: { color: "#21262d" },
        horzLines: { color: "#21262d" },
      },
      crosshair: { mode: 1 },
      timeScale: { borderColor: "#30363d" },
      rightPriceScale: { borderColor: "#30363d" },
    });

    const series = chart.addCandlestickSeries({
      borderVisible: false,
      upColor: "#3fb950",
      downColor: "#f85149",
      wickUpColor: "#3fb950",
      wickDownColor: "#f85149",
    });

    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = [];

    const mapped: CandlestickData[] = historyData.map((b) => ({
      time: b.time as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    series.setData(mapped);

    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            chart.applyOptions({
              width: container.clientWidth,
              height: container.clientHeight || 380,
            });
          })
        : null;
    ro?.observe(container);
    chart.applyOptions({
      width: container.clientWidth,
      height: container.clientHeight || 380,
    });

    return () => {
      ro?.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // rebuild chart whenever ticker switches or anchored history refreshes fully
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally reset chart on ticker/dataset pairing
  }, [ticker, loading, historyData]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !liveUpdate) return;

    series.update({
      ...liveUpdate.priceData,
      time: liveUpdate.priceData.time as UTCTimestamp,
    });

    if (liveUpdate.pattern_detected) {
      markersRef.current = [
        ...markersRef.current,
        {
          time: liveUpdate.time as UTCTimestamp,
          position: "aboveBar",
          shape: "arrowDown",
          color: "#f0883e",
          text: liveUpdate.pattern_label ?? "Pattern",
        },
      ];
      series.setMarkers(markersRef.current);
    }
  }, [liveUpdate]);

  return (
    <div
      ref={rootRef}
      style={{
        height: "min(420px, 52vh)",
        width: "100%",
        border: "1px solid #30363d",
        borderRadius: "8px",
        overflow: "hidden",
      }}
      aria-busy={loading}
    />
  );
}
