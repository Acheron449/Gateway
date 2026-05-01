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
import type { CandleData, HistoryCandle, LiveUpdate } from "../../types/market";

export interface MainChartProps {
  ticker: string;
  /** Backward-compatible historical prop from current container */
  historyData?: HistoryCandle[];
  /** Alternate prop from requested snippet */
  initialData?: CandleData[];
  loading?: boolean;
  /** If provided, component uses parent live feed and skips internal socket stream */
  liveUpdate?: LiveTradingUpdate | null;
}

export function MainChart({
  ticker,
  historyData,
  initialData,
  loading = false,
  liveUpdate,
}: MainChartProps) {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<Array<SeriesMarker<Time>>>([]);
  const activeTickerRef = useRef<string>(ticker.toUpperCase());

  useEffect(() => {
    activeTickerRef.current = ticker.toUpperCase();
  }, [ticker]);

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || loading) return undefined;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "#0d1117" },
        textColor: "#d1d4dc",
      },
      grid: {
        vertLines: { color: "rgba(42, 46, 57, 0.5)" },
        horzLines: { color: "rgba(42, 46, 57, 0.5)" },
      },
      crosshair: { mode: 0 },
      timeScale: { borderColor: "#485c7b", timeVisible: true, secondsVisible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = [];

    const source = initialData ?? historyData ?? [];
    const mapped: CandlestickData[] = source.map((b) => ({
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
              height: container.clientHeight || 600,
            });
          })
        : null;
    ro?.observe(container);
    chart.applyOptions({
      width: container.clientWidth,
      height: container.clientHeight || 600,
    });

    return () => {
      ro?.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [ticker, loading, historyData, initialData]);

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

  useEffect(() => {
    // If parent already provides live updates, avoid duplicate websocket updates.
    if (typeof liveUpdate !== "undefined") return;

    const socket = new WebSocket("ws://localhost:8000/ws/trading");
    socket.onmessage = (event: MessageEvent) => {
      const series = seriesRef.current;
      if (!series) return;

      try {
        const update = JSON.parse(event.data as string) as LiveUpdate & {
          symbol?: string;
          price?: number;
          time?: number;
        };
        const incomingSymbol = (update.ticker ?? update.symbol ?? "").toUpperCase();
        if (incomingSymbol !== activeTickerRef.current) return;

        if (update.priceData) {
          series.update(update.priceData as CandlestickData);
        } else if (typeof update.price === "number") {
          const now = Math.floor(Date.now() / 1000) as UTCTimestamp;
          const t = (typeof update.time === "number" ? update.time : now) as UTCTimestamp;
          series.update({
            time: t,
            open: update.price,
            high: update.price,
            low: update.price,
            close: update.price,
          });
        }
      } catch {
        // Ignore malformed websocket payloads.
      }
    };

    return () => socket.close();
  }, [liveUpdate]);

  return (
    <div
      className="relative w-full h-full border border-gray-800 rounded-lg overflow-hidden bg-[#0d1117]"
      style={{ border: "1px solid #30363d", borderRadius: "8px", overflow: "hidden" }}
      aria-busy={loading}
    >
      <div
        className="absolute top-4 left-4 z-10 flex items-center gap-2"
        style={{ position: "absolute", top: 16, left: 16, zIndex: 10, display: "flex", gap: 8 }}
      >
        <span className="text-xl font-bold text-white" style={{ fontSize: "1.125rem", fontWeight: 700 }}>
          {ticker}
        </span>
        <span
          className="px-2 py-1 text-xs font-mono bg-green-500/20 text-green-400 rounded"
          style={{
            padding: "2px 8px",
            fontSize: "0.75rem",
            borderRadius: 6,
            background: "rgba(63, 185, 80, 0.2)",
            color: "#3fb950",
          }}
        >
          LIVE
        </span>
      </div>
      <div ref={chartContainerRef} className="w-full h-[600px]" style={{ width: "100%", height: "600px" }} />
    </div>
  );
}
