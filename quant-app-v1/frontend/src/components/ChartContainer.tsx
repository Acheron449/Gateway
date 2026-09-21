import { useCallback, useEffect, useState } from "react";
import type { SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import { useHistory } from "../hooks/useHistory";
import { useSocket } from "../hooks/useSocket";
import { API_BASE } from "../lib/constants";
import type { PatternSignal } from "../types/market";

import { MainChart } from "./charts/MainChart";
import { IndicatorOverlay } from "./charts/IndicatorOverlay";
import { PatternList } from "./features/PatternList";
import { KronosForecast } from "./features/KronosForecast";

export interface ChartContainerProps {
  ticker: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toUtcTimestamp(value: unknown): UTCTimestamp | null {
  let milliseconds: number | null = null;

  if (typeof value === "string") {
    const parsed = Date.parse(value);
    milliseconds = Number.isFinite(parsed) ? parsed : null;
  } else if (typeof value === "number" && Number.isFinite(value)) {
    milliseconds = value > 10_000_000_000 ? value : value * 1000;
  }

  if (milliseconds === null) return null;
  return Math.floor(milliseconds / 1000) as UTCTimestamp;
}

function buildEventMarkers(newsPayload: unknown, calendarPayload: unknown): SeriesMarker<Time>[] {
  const newsItems = isRecord(newsPayload) && Array.isArray(newsPayload.items) ? newsPayload.items : [];
  const calendarEvents = isRecord(calendarPayload) && Array.isArray(calendarPayload.events) ? calendarPayload.events : [];
  const markers: SeriesMarker<Time>[] = [];

  for (const item of newsItems) {
    if (!isRecord(item)) continue;
    const time = toUtcTimestamp(item.published_at);
    const headline = typeof item.headline === "string" ? item.headline.trim() : "";
    if (time === null || !headline) continue;

    markers.push({
      time,
      position: "aboveBar",
      shape: "circle",
      color: "#58a6ff",
      text: `News: ${headline}`,
    });
  }

  for (const event of calendarEvents) {
    if (!isRecord(event)) continue;
    const time = toUtcTimestamp(event.scheduled_at);
    const title = typeof event.title === "string" ? event.title.trim() : "";
    if (time === null || !title) continue;

    markers.push({
      time,
      position: "belowBar",
      shape: "square",
      color: "#d29922",
      text: `Calendar: ${title}`,
    });
  }

  return markers.sort((a, b) => (a.time as UTCTimestamp) - (b.time as UTCTimestamp));
}

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  try {
    const response = await fetch(url, { signal });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export function ChartContainer({ ticker }: ChartContainerProps) {
  const { data, loading, error } = useHistory(ticker);
  const liveUpdate = useSocket(ticker);
  const [patterns, setPatterns] = useState<PatternSignal[]>([]);
  const [eventMarkers, setEventMarkers] = useState<SeriesMarker<Time>[]>([]);

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

  useEffect(() => {
    const symbol = ticker?.trim().toUpperCase();
    if (!symbol) {
      setEventMarkers([]);
      return undefined;
    }

    const controller = new AbortController();
    let active = true;

    void (async () => {
      const [newsPayload, calendarPayload] = await Promise.allSettled([
        fetchJson(`${API_BASE}/news?symbol=${encodeURIComponent(symbol)}&limit=20`, controller.signal),
        fetchJson(`${API_BASE}/news/calendar?limit=50`, controller.signal),
      ]);

      if (!active) return;

      const newsValue = newsPayload.status === "fulfilled" ? newsPayload.value : null;
      const calendarValue = calendarPayload.status === "fulfilled" ? calendarPayload.value : null;
      setEventMarkers(buildEventMarkers(newsValue, calendarValue));
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [ticker]);

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
      <MainChart
        ticker={ticker}
        historyData={data}
        loading={loading}
        liveUpdate={liveUpdate}
        eventMarkers={eventMarkers}
      />
      <KronosForecast bars={data} />
      <PatternList activePatterns={patterns} onZoomToPattern={handleZoomToPattern} />
    </div>
  );
}
