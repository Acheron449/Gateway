import { ColorType, createChart } from "lightweight-charts";
import type {
  CandlestickData,
  HistogramData,
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
  eventMarkers?: SeriesMarker<Time>[];
}

function markerTime(marker: SeriesMarker<Time>): number {
  return typeof marker.time === "number" ? marker.time : 0;
}

function mergeMarkers(
  eventMarkers: SeriesMarker<Time>[],
  patternMarkers: SeriesMarker<Time>[],
): SeriesMarker<Time>[] {
  return [...eventMarkers, ...patternMarkers].sort((a, b) => markerTime(a) - markerTime(b));
}

export function MainChart({
  ticker,
  historyData,
  loading,
  liveUpdate,
  eventMarkers = [],
}: MainChartProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const patternMarkersRef = useRef<SeriesMarker<Time>[]>([]);
  const eventMarkersRef = useRef<SeriesMarker<Time>[]>([]);

  useEffect(() => {
    eventMarkersRef.current = eventMarkers;
    const series = seriesRef.current;
    if (series) {
      series.setMarkers(mergeMarkers(eventMarkers, patternMarkersRef.current));
    }
  }, [eventMarkers]);

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

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    chartRef.current = chart;
    seriesRef.current = series;
    volumeSeriesRef.current = volumeSeries;
    patternMarkersRef.current = [];
    eventMarkersRef.current = eventMarkers;

    const mapped: CandlestickData[] = historyData.map((b) => ({
      time: b.time as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    series.setData(mapped);
    series.setMarkers(eventMarkers);

    const volumeData: HistogramData[] = historyData
      .filter((b) => typeof b.volume === "number" && Number.isFinite(b.volume) && b.volume > 0)
      .map((b) => ({
        time: b.time as UTCTimestamp,
        value: b.volume as number,
        color: b.close >= b.open ? "rgba(63,185,80,0.45)" : "rgba(248,81,73,0.45)",
      }));
    volumeSeries.setData(volumeData);

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
      volumeSeriesRef.current = null;
    };
  }, [ticker, loading, historyData]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !liveUpdate) return;

    series.update({
      ...liveUpdate.priceData,
      time: liveUpdate.priceData.time as UTCTimestamp,
    });

    if (!liveUpdate.pattern_detected) return;

    const marker: SeriesMarker<Time> = {
      time: liveUpdate.time as UTCTimestamp,
      position: "aboveBar",
      shape: "arrowDown",
      color: "#f0883e",
      text: liveUpdate.pattern_label ?? "Pattern",
    };
    const exists = patternMarkersRef.current.some(
      (current) => markerTime(current) === markerTime(marker) && current.text === marker.text,
    );
    if (exists) return;

    patternMarkersRef.current = [...patternMarkersRef.current, marker];
    series.setMarkers(mergeMarkers(eventMarkersRef.current, patternMarkersRef.current));
  }, [liveUpdate]);

  return (
    <div
      ref={rootRef}
      className="main-chart"
      style={{
        height: "min(460px, 56vh)",
        width: "100%",
        border: "1px solid var(--border-primary, #30363d)",
        borderRadius: "10px",
        overflow: "hidden",
        position: "relative",
      }}
      aria-busy={loading}
    >
      {loading && (
        <div className="main-chart-status">
          <div className="chart-spinner" aria-hidden="true" />
          <span>Loading {ticker} candles…</span>
        </div>
      )}
      {!loading && historyData.length === 0 && (
        <div className="main-chart-status">
          <span className="main-chart-empty-icon" aria-hidden="true">📈</span>
          <span>No chart data for <strong>{ticker}</strong></span>
          <span className="main-chart-empty-hint">
            The market may be closed, the symbol unknown, or the data feed unreachable. Try another timeframe.
          </span>
        </div>
      )}
    </div>
  );
}
