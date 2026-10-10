import { useEffect, useMemo, useRef, useState } from "react";

import type { LiveTradingUpdate } from "../../hooks/useSocket";
import {
  computeIndicators,
  type ComputedIndicator,
  type IndicatorLine,
} from "../../lib/indicators";
import type { HistoryCandle } from "../../types/market";

export interface ChartMarker {
  time: number;
  position?: "aboveBar" | "belowBar";
  color?: string;
  text?: string;
}

export interface MainChartProps {
  ticker: string;
  historyData: HistoryCandle[];
  loading: boolean;
  liveUpdate?: LiveTradingUpdate | null;
  eventMarkers?: ChartMarker[];
  /** Active indicator ids chosen in the indicator panel (overlay + subpanes). */
  indicators?: readonly string[];
  /**
   * Bump this counter to jump the viewport back to the most recent candle
   * (the chart's "Now" button). Any value change recenters on the latest bar.
   */
  nowSignal?: number;
  /** Fill the dimensions allocated by the parent, used by the resizable trading desk. */
  fillContainer?: boolean;
}

const UP_COLOR = "#3fb950";
const DOWN_COLOR = "#f85149";
const BG = "#0d1117";
const GRID = "#1c2128";
const AXIS_TEXT = "#8b949e";
const BORDER = "#30363d";
const DEFAULT_VISIBLE = 120;
const PRICE_AXIS_W = 64;
const TIME_AXIS_H = 24;
const MIN_SPAN = 20;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtPrice(value: number): string {
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  if (abs >= 1) return value.toFixed(2);
  if (abs >= 0.1) return value.toFixed(3);
  if (abs >= 0.01) return value.toFixed(4);
  return value.toPrecision(4);
}

function fmtVolume(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return `${Math.round(value)}`;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function shortTime(ts: number): string {
  const date = new Date(ts * 1000);
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function shortDate(ts: number): string {
  const date = new Date(ts * 1000);
  return `${date.getDate()} ${MONTHS[date.getMonth()] ?? ""}`;
}

function fullStamp(ts: number, intraday: boolean): string {
  const date = new Date(ts * 1000);
  const day = `${date.getDate()} ${MONTHS[date.getMonth()] ?? ""} ${date.getFullYear()}`;
  return intraday ? `${day}, ${pad2(date.getHours())}:${pad2(date.getMinutes())}` : day;
}

function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const exponent = Math.floor(Math.log10(raw));
  const fraction = raw / 10 ** exponent;
  const nice = fraction < 1.5 ? 1 : fraction < 3 ? 2 : fraction < 7 ? 5 : 10;
  return nice * 10 ** exponent;
}

function priceTicks(min: number, max: number, target: number): number[] {
  const step = niceStep((max - min) / Math.max(target - 1, 1));
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 0.001; value += step) {
    ticks.push(Number(value.toFixed(10)));
    if (ticks.length > 40) break;
  }
  return ticks;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

interface PaneBox {
  top: number;
  height: number;
  computed?: ComputedIndicator;
}

interface TooltipState {
  x: number;
  y: number;
  rows: Array<{ label: string; value: string; color?: string }>;
}

/**
 * Hand-built interactive trading chart (no third-party charting widget):
 * candles + volume, wheel zoom, drag pan, crosshair with tooltip, overlays
 * and one subpane per selected oscillator-style indicator.
 */
export function MainChart({
  ticker,
  historyData,
  loading,
  liveUpdate,
  eventMarkers = [],
  indicators = [],
  nowSignal = 0,
  fillContainer = false,
}: MainChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const barsRef = useRef<HistoryCandle[]>([]);
  const computedRef = useRef<ComputedIndicator[]>([]);
  const patternMarkersRef = useRef<ChartMarker[]>([]);
  const viewRef = useRef<{ start: number; end: number } | null>(null);
  const crossRef = useRef<{ x: number; y: number; index: number } | null>(null);
  const dragRef = useRef<{ x: number; start: number; end: number } | null>(null);
  const tickerRef = useRef(ticker);
  const drawRef = useRef<() => void>(() => undefined);
  const frameRef = useRef(0);
  const frameFallbackRef = useRef(0);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  tickerRef.current = ticker;

  const computed = useMemo(
    () => computeIndicators(indicators, historyData),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [indicators, historyData],
  );

  const scheduleDraw = (): void => {
    if (frameRef.current) return;
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = 0;
      if (frameFallbackRef.current) {
        window.clearTimeout(frameFallbackRef.current);
        frameFallbackRef.current = 0;
      }
      drawRef.current();
    });
    // rAF is throttled to a halt in hidden/backgrounded windows — fall back
    // to a timer so the chart never stays stale until the next interaction.
    if (!frameFallbackRef.current) {
      frameFallbackRef.current = window.setTimeout(() => {
        frameFallbackRef.current = 0;
        if (frameRef.current) {
          window.cancelAnimationFrame(frameRef.current);
          frameRef.current = 0;
        }
        drawRef.current();
      }, 250);
    }
  };

  // --- drawing -------------------------------------------------------------

  const draw = (): void => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (width <= 0 || height <= 0) return;

    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.round(width * dpr);
    const targetH = Math.round(height * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const bars = barsRef.current;
    const computedList = computedRef.current;
    const overlays = computedList.filter((item) => item.kind === "overlay");
    const subpanes = computedList.filter((item) => item.kind === "pane");
    const plotW = Math.max(width - PRICE_AXIS_W, 40);

    // Layout: price pane on top, oscillator subpanes under it.
    let subH = 0;
    if (subpanes.length > 0) {
      const budget = (height - TIME_AXIS_H) * 0.55;
      subH = clamp(budget / subpanes.length, 76, 150);
    }
    const priceHeight = Math.max(height - TIME_AXIS_H - subH * subpanes.length, 120);
    const panes: PaneBox[] = [{ top: 0, height: priceHeight }];
    for (let i = 0; i < subpanes.length; i++) {
      const computedSub = subpanes[i];
      if (!computedSub) continue;
      panes.push({ top: priceHeight + subH * i, height: subH, computed: computedSub });
    }
    const pricePane = panes[0];
    if (!pricePane) return;

    // Background
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, width, height);

    // View window
    const len = bars.length;
    let view = viewRef.current;
    if (!view) {
      view = { start: Math.max(0, len - DEFAULT_VISIBLE), end: len };
      viewRef.current = view;
    }
    if (len === 0) {
      drawTimeAxisAndFrame(ctx, width, height, plotW, TIME_AXIS_H);
      return;
    }
    const span = Math.max(view.end - view.start, MIN_SPAN);
    const barW = plotW / span;
    const xOf = (i: number): number => (i - view.start + 0.5) * barW;
    const i0 = clamp(Math.floor(view.start), 0, len - 1);
    const i1 = clamp(Math.ceil(view.end), 0, len - 1);

    const hoverIndex = crossRef.current?.index ?? null;
    const legendIndex = hoverIndex ?? i1;

    // Visible price range (bars + overlay lines)
    let min = Infinity;
    let max = -Infinity;
    for (let i = i0; i <= i1; i++) {
      const bar = bars[i];
      if (!bar) continue;
      min = Math.min(min, bar.low);
      max = Math.max(max, bar.high);
    }
    for (const overlay of overlays) {
      for (const lineSpec of overlay.lines) {
        for (let i = i0; i <= i1; i++) {
          const value = lineSpec.values[i];
          if (typeof value === "number" && Number.isFinite(value)) {
            min = Math.min(min, value);
            max = Math.max(max, value);
          }
        }
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
      min = (Number.isFinite(min) ? min : 0) - 1;
      max = (Number.isFinite(max) ? max : 1) + 1;
    }
    const padPrice = (max - min) * 0.08;
    min -= padPrice;
    max += padPrice;
    const priceH = pricePane.height;
    const yOf = (value: number): number =>
      pricePane.top + priceH - ((value - min) / (max - min)) * priceH;

    // Vertical grid + time axis labels
    const barSeconds = estimateBarSeconds(bars, i0, i1);
    const stepBars = niceBarStep(barW);
    const labelIndexes: number[] = [];
    for (let i = Math.ceil(view.start / stepBars) * stepBars; i <= view.end; i += stepBars) {
      if (i >= i0 && i <= i1) labelIndexes.push(i);
    }
    const intraday = barSeconds < 86400;
    ctx.strokeStyle = GRID;
    ctx.lineWidth = 1;
    ctx.font = "11px system-ui, -apple-system, sans-serif";
    ctx.fillStyle = AXIS_TEXT;
    for (const i of labelIndexes) {
      const x = Math.round(xOf(i)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height - TIME_AXIS_H);
      ctx.stroke();
      const bar = bars[i];
      if (!bar) continue;
      const text = intraday ? shortTime(bar.time) : shortDate(bar.time);
      ctx.textAlign = "center";
      ctx.fillText(text, x, height - 7);
    }

    // Price pane: horizontal grid + right-axis labels
    const ticks = priceTicks(min, max, 6);
    ctx.textAlign = "left";
    for (const tick of ticks) {
      const y = Math.round(yOf(tick)) + 0.5;
      if (y < pricePane.top || y > pricePane.top + priceH) continue;
      ctx.strokeStyle = GRID;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(plotW, y);
      ctx.stroke();
      ctx.fillStyle = AXIS_TEXT;
      ctx.fillText(fmtPrice(tick), plotW + 6, y + 4);
    }

    // Volume (bottom slice of the price pane)
    let maxVol = 0;
    for (let i = i0; i <= i1; i++) {
      const v = bars[i]?.volume ?? 0;
      if (Number.isFinite(v)) maxVol = Math.max(maxVol, v);
    }
    if (maxVol > 0) {
      const volH = priceH * 0.22;
      const bodyW = Math.max(1, Math.min(barW * 0.7, 14));
      for (let i = i0; i <= i1; i++) {
        const bar = bars[i];
        if (!bar || !bar.volume) continue;
        const h = (bar.volume / maxVol) * volH;
        ctx.fillStyle = bar.close >= bar.open ? "rgba(63,185,80,0.35)" : "rgba(248,81,73,0.35)";
        ctx.fillRect(xOf(i) - bodyW / 2, pricePane.top + priceH - h, bodyW, h);
      }
    }

    // Candles
    const bodyW = Math.max(1, Math.min(barW * 0.7, 16));
    for (let i = i0; i <= i1; i++) {
      const bar = bars[i];
      if (!bar) continue;
      const x = xOf(i);
      const up = bar.close >= bar.open;
      ctx.strokeStyle = up ? UP_COLOR : DOWN_COLOR;
      ctx.fillStyle = up ? UP_COLOR : DOWN_COLOR;
      const wickX = Math.round(x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(wickX, yOf(bar.high));
      ctx.lineTo(wickX, yOf(bar.low));
      ctx.stroke();
      const openY = yOf(bar.open);
      const closeY = yOf(bar.close);
      const top = Math.min(openY, closeY);
      const bodyH = Math.max(Math.abs(openY - closeY), 1);
      ctx.fillRect(x - bodyW / 2, top, bodyW, bodyH);
    }

    // Indicator overlays on the price pane
    for (const overlay of overlays) {
      for (const lineSpec of overlay.lines) {
        drawLine(ctx, lineSpec, xOf, yOf, i0, i1, barW);
      }
    }

    // Last price line + tag
    const lastBar = bars[i1];
    if (lastBar) {
      const y = Math.round(yOf(lastBar.close)) + 0.5;
      const up = lastBar.close >= (lastBar.open ?? lastBar.close);
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = up ? UP_COLOR : DOWN_COLOR;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(plotW, y);
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = up ? UP_COLOR : DOWN_COLOR;
      const label = fmtPrice(lastBar.close);
      ctx.fillRect(plotW + 1, y - 8, PRICE_AXIS_W - 1, 16);
      ctx.fillStyle = "#04121a";
      ctx.font = "11px system-ui, -apple-system, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(label, plotW + 6, y + 4);
    }

    // Event / pattern markers
    const allMarkers = [...eventMarkers, ...patternMarkersRef.current];
    for (const marker of allMarkers) {
      const index = findBarIndex(bars, marker.time);
      if (index === null || index < i0 || index > i1) continue;
      const bar = bars[index];
      if (!bar) continue;
      const x = xOf(index);
      const above = marker.position !== "belowBar";
      const y = above ? yOf(bar.high) - 10 : yOf(bar.low) + 10;
      ctx.fillStyle = marker.color ?? "#f0883e";
      ctx.beginPath();
      if (above) {
        ctx.moveTo(x, y - 6);
        ctx.lineTo(x - 5, y + 3);
        ctx.lineTo(x + 5, y + 3);
      } else {
        ctx.moveTo(x, y + 6);
        ctx.lineTo(x - 5, y - 3);
        ctx.lineTo(x + 5, y - 3);
      }
      ctx.closePath();
      ctx.fill();
      if (marker.text) {
        ctx.textAlign = "center";
        ctx.font = "10px system-ui, -apple-system, sans-serif";
        ctx.fillText(marker.text, x, above ? y - 10 : y + 16);
      }
    }

    // Price legend (top-left)
    ctx.font = "11px system-ui, -apple-system, sans-serif";
    let legendY = 8;
    const legendX = 8;
    ctx.textAlign = "left";
    ctx.fillStyle = "#c9d1d9";
    ctx.font = "600 12px system-ui, -apple-system, sans-serif";
    ctx.fillText(`${tickerRef.current} · ${barSecondsLabel(barSeconds)}`, legendX, legendY + 4);
    legendY += 16;
    const hoverBar = hoverIndex !== null ? bars[hoverIndex] : lastBar;
    if (hoverBar) {
      ctx.font = "11px system-ui, -apple-system, sans-serif";
      const up = hoverBar.close >= hoverBar.open;
      ctx.fillStyle = up ? UP_COLOR : DOWN_COLOR;
      const parts = [
        `O ${fmtPrice(hoverBar.open)}`,
        `H ${fmtPrice(hoverBar.high)}`,
        `L ${fmtPrice(hoverBar.low)}`,
        `C ${fmtPrice(hoverBar.close)}`,
      ];
      ctx.fillText(parts.join("   "), legendX, legendY + 4);
      legendY += 15;
    }
    ctx.font = "11px system-ui, -apple-system, sans-serif";
    for (const overlay of overlays) {
      for (const lineSpec of overlay.lines) {
        const value = lineSpec.values[legendIndex];
        ctx.fillStyle = lineSpec.color;
        ctx.fillRect(legendX, legendY - 5, 10, 2);
        ctx.fillStyle = "#c9d1d9";
        const suffix = typeof value === "number" && Number.isFinite(value) ? `  ${fmtPrice(value)}` : "";
        ctx.fillText(`${lineSpec.name}${suffix}`, legendX + 15, legendY + 3);
        legendY += 14;
        if (legendY > pricePane.top + priceH - 8) break;
      }
      if (legendY > pricePane.top + priceH - 8) break;
    }

    // Subpanes
    for (let p = 1; p < panes.length; p++) {
      const pane = panes[p];
      if (!pane || !pane.computed) continue;
      drawSubpane(ctx, pane, pane.computed, { i0, i1, xOf, plotW, width, legendIndex, height });
    }

    // Crosshair
    const cross = crossRef.current;
    if (cross && cross.x <= plotW) {
      ctx.save();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = "#8b949e";
      ctx.lineWidth = 1;
      const vx = Math.round(cross.x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(vx, 0);
      ctx.lineTo(vx, height - TIME_AXIS_H);
      ctx.stroke();

      // Horizontal segment + price tag inside the pane under the cursor
      const inPane =
        panes.find((pane) => cross.y >= pane.top && cross.y < pane.top + pane.height) ?? pricePane;
      const hy = Math.round(cross.y) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, hy);
      ctx.lineTo(plotW, hy);
      ctx.stroke();
      ctx.restore();

      const hoverBar = bars[cross.index];
      if (hoverBar) {
        // time tag
        const stamp = fullStamp(hoverBar.time, intraday);
        ctx.font = "11px system-ui, -apple-system, sans-serif";
        const tw = ctx.measureText(stamp).width + 12;
        const tx = clamp(vx - tw / 2, 0, plotW - tw);
        ctx.fillStyle = "#2d333b";
        ctx.fillRect(tx, height - TIME_AXIS_H + 2, tw, TIME_AXIS_H - 4);
        ctx.fillStyle = "#c9d1d9";
        ctx.textAlign = "center";
        ctx.fillText(stamp, tx + tw / 2, height - 8);

        // price tag in the pane under the cursor
        const paneRange = inPane.computed
          ? paneValueRange(inPane.computed, i0, i1)
          : { min, max };
        if (paneRange) {
          const fraction = (inPane.top + inPane.height - hy) / inPane.height;
          const value = paneRange.min + fraction * (paneRange.max - paneRange.min);
          drawTag(ctx, plotW, hy, fmtPrice(value), "#2d333b", "#c9d1d9");
        }
      }
    }

    // Frame: axes borders
    drawTimeAxisAndFrame(ctx, width, height, plotW, TIME_AXIS_H);
  };

  drawRef.current = draw;

  // --- data / prop sync ----------------------------------------------------

  useEffect(() => {
    barsRef.current = [...historyData];
    const view = viewRef.current;
    if (view) {
      const len = barsRef.current.length;
      if (view.end > len || view.start > len - MIN_SPAN) {
        viewRef.current = null; // data shrank (timeframe/symbol change) — recenter
      }
    }
    scheduleDraw();
  }, [historyData]);

  useEffect(() => {
    computedRef.current = computed;
    scheduleDraw();
  }, [computed]);

  // "Now" button: reset the viewport so the latest candle sits at the right edge.
  useEffect(() => {
    if (nowSignal === 0) return;
    viewRef.current = null;
    crossRef.current = null;
    scheduleDraw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nowSignal]);

  useEffect(() => {
    viewRef.current = null;
    crossRef.current = null;
    dragRef.current = null;
    patternMarkersRef.current = [];
    setTooltip(null);
    scheduleDraw();
  }, [ticker]);

  useEffect(() => {
    if (!liveUpdate) return;
    const priceData = liveUpdate.priceData;
    const bars = barsRef.current;
    if (priceData && bars.length > 0) {
      const last = bars[bars.length - 1];
      if (last && priceData.time === last.time) {
        bars[bars.length - 1] = {
          ...last,
          close: priceData.close,
          high: Math.max(last.high, priceData.close),
          low: Math.min(last.low, priceData.close),
        };
      } else if (last && priceData.time > last.time) {
        bars.push({ ...priceData, volume: priceData.volume ?? last.volume });
      }
    }
    if (liveUpdate.pattern_detected) {
      const marker: ChartMarker = {
        time: liveUpdate.time,
        position: "aboveBar",
        color: "#f0883e",
        text: liveUpdate.pattern_label ?? "Pattern",
      };
      const exists = patternMarkersRef.current.some(
        (current) => current.time === marker.time && current.text === marker.text,
      );
      if (!exists) patternMarkersRef.current = [...patternMarkersRef.current, marker];
    }
    scheduleDraw();
  }, [liveUpdate]);

  // --- interactions --------------------------------------------------------

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return undefined;

    const plotWidth = (): number => Math.max(container.clientWidth - PRICE_AXIS_W, 40);

    const ensureView = (): { start: number; end: number } => {
      const view = viewRef.current;
      if (view) return view;
      const len = barsRef.current.length;
      const fresh = { start: Math.max(0, len - DEFAULT_VISIBLE), end: len };
      viewRef.current = fresh;
      return fresh;
    };

    const clampView = (view: { start: number; end: number }): void => {
      const len = barsRef.current.length;
      if (len === 0) return;
      let span = view.end - view.start;
      if (span < MIN_SPAN) span = MIN_SPAN;
      if (span > Math.max(len, MIN_SPAN)) span = Math.max(len, MIN_SPAN);
      let start = view.start;
      let end = start + span;
      if (end > len) {
        end = len;
        start = end - span;
      }
      if (start < 0) {
        start = 0;
        end = span;
      }
      viewRef.current = { start, end: Math.min(end, len) };
    };

    const onWheel = (event: WheelEvent): void => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      if (x > plotWidth()) return;
      const view = ensureView();
      const span = Math.max(view.end - view.start, MIN_SPAN);
      const barW = plotWidth() / span;
      const anchor = view.start + x / barW;
      const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
      const nextSpan = clamp(span * factor, MIN_SPAN, Math.max(barsRef.current.length, MIN_SPAN));
      const frac = x / plotWidth();
      viewRef.current = { start: anchor - frac * nextSpan, end: anchor + (1 - frac) * nextSpan };
      clampView(viewRef.current);
      scheduleDraw();
    };

    const onPointerDown = (event: PointerEvent): void => {
      if (event.button !== 0) return;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      if (x > plotWidth()) return;
      const view = ensureView();
      dragRef.current = { x, start: view.start, end: view.end };
      canvas.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event: PointerEvent): void => {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const bars = barsRef.current;

      const drag = dragRef.current;
      if (drag) {
        const view = { start: drag.start, end: drag.end };
        const span = Math.max(view.end - view.start, MIN_SPAN);
        const barW = plotWidth() / span;
        const deltaBars = (x - drag.x) / barW;
        viewRef.current = { start: view.start - deltaBars, end: view.end - deltaBars };
        clampView(viewRef.current);
      }

      if (x <= plotWidth() && bars.length > 0 && y < container.clientHeight - TIME_AXIS_H) {
        const view = ensureView();
        const span = Math.max(view.end - view.start, MIN_SPAN);
        const barW = plotWidth() / span;
        const index = clamp(Math.round(view.start + x / barW - 0.5), 0, bars.length - 1);
        crossRef.current = { x, y, index };
        if (!drag) setTooltip({ x, y, rows: tooltipRows(bars[index], index) });
      } else {
        crossRef.current = null;
        setTooltip(null);
      }
      scheduleDraw();
    };

    const endDrag = (event: PointerEvent): void => {
      if (dragRef.current) {
        dragRef.current = null;
        try {
          canvas.releasePointerCapture(event.pointerId);
        } catch {
          // pointer already released
        }
      }
    };

    const onPointerLeave = (): void => {
      crossRef.current = null;
      setTooltip(null);
      scheduleDraw();
    };

    const onDoubleClick = (): void => {
      viewRef.current = null;
      scheduleDraw();
    };

    const resizeObserver =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => scheduleDraw()) : null;
    resizeObserver?.observe(container);

    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("dblclick", onDoubleClick);

    scheduleDraw();

    return () => {
      resizeObserver?.disconnect();
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", endDrag);
      canvas.removeEventListener("pointercancel", endDrag);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("dblclick", onDoubleClick);
      if (frameRef.current) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = 0;
      }
      if (frameFallbackRef.current) {
        window.clearTimeout(frameFallbackRef.current);
        frameFallbackRef.current = 0;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tooltipRows = (bar: HistoryCandle | undefined, index: number): TooltipState["rows"] => {
    if (!bar) return [];
    const rows: TooltipState["rows"] = [
      { label: "O", value: fmtPrice(bar.open) },
      { label: "H", value: fmtPrice(bar.high) },
      { label: "L", value: fmtPrice(bar.low) },
      { label: "C", value: fmtPrice(bar.close), color: bar.close >= bar.open ? UP_COLOR : DOWN_COLOR },
    ];
    if (typeof bar.volume === "number" && bar.volume > 0) {
      rows.push({ label: "Vol", value: fmtVolume(bar.volume) });
    }
    for (const item of computedRef.current) {
      for (const lineSpec of item.lines) {
        const value = lineSpec.values[index];
        if (typeof value === "number" && Number.isFinite(value)) {
          rows.push({ label: lineSpec.name, value: fmtPrice(value), color: lineSpec.color });
        }
      }
    }
    return rows;
  };

  const showTooltip = tooltip && tooltip.rows.length > 0 && !loading;
  const tooltipLeft = tooltip
    ? clamp(tooltip.x + 18, 8, Math.max((containerRef.current?.clientWidth ?? 400) - 170, 8))
    : 0;
  const tooltipTop = tooltip ? clamp(tooltip.y + 14, 8, Math.max((containerRef.current?.clientHeight ?? 300) - 120, 8)) : 0;

  return (
    <div
      ref={containerRef}
      className="main-chart"
      style={{
        height: fillContainer ? "100%" : "min(460px, 56vh)",
        width: "100%",
        border: "1px solid var(--border-primary, #30363d)",
        borderRadius: "10px",
        overflow: "hidden",
        position: "relative",
      }}
      aria-busy={loading}
    >
      <canvas
        ref={canvasRef}
        className="chart-canvas"
        style={{ display: "block", width: "100%", height: "100%", touchAction: "none" }}
      />
      {showTooltip && tooltip && (
        <div
          className="chart-tooltip"
          style={{ left: tooltipLeft, top: tooltipTop }}
          role="status"
          aria-hidden="true"
        >
          {tooltip.rows.map((row) => (
            <div key={row.label} className="ct-row">
              <span className="ct-label">{row.label}</span>
              <span className="ct-value" style={row.color ? { color: row.color } : undefined}>
                {row.value}
              </span>
            </div>
          ))}
        </div>
      )}
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
            The market may be closed, the symbol unknown, or the data feed unreachable. Try another provider or timeframe.
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// drawing helpers
// ---------------------------------------------------------------------------

function estimateBarSeconds(bars: HistoryCandle[], i0: number, i1: number): number {
  if (i1 <= i0) return 3600;
  const first = bars[i0];
  const last = bars[i1];
  if (!first || !last) return 3600;
  const count = Math.max(i1 - i0, 1);
  return Math.max((last.time - first.time) / count, 1);
}

function barSecondsLabel(seconds: number): string {
  if (seconds < 90) return "1m";
  if (seconds < 900) return "5m";
  if (seconds < 1800) return "15m";
  if (seconds < 5400) return "30m";
  if (seconds < 86400 * 0.9) return "1h";
  if (seconds < 86400 * 1.5) return "1D";
  if (seconds < 86400 * 7) return "1W";
  return `${Math.round(seconds / 86400)}D`;
}

function niceBarStep(barW: number): number {
  const target = Math.max(90 / Math.max(barW, 0.001), 1);
  const candidates = [1, 2, 3, 5, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000];
  for (const candidate of candidates) {
    if (candidate >= target) return candidate;
  }
  return 1000;
}

function findBarIndex(bars: HistoryCandle[], time: number): number | null {
  if (bars.length === 0) return null;
  const first = bars[0];
  const last = bars[bars.length - 1];
  if (!first || !last) return null;
  if (time <= first.time) return 0;
  if (time >= last.time) return bars.length - 1;
  let lo = 0;
  let hi = bars.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const bar = bars[mid];
    if (!bar) break;
    if (bar.time === time) return mid;
    if (bar.time < time) lo = mid + 1;
    else hi = mid - 1;
  }
  return clamp(lo - 1, 0, bars.length - 1);
}

function drawLine(
  ctx: CanvasRenderingContext2D,
  lineSpec: IndicatorLine,
  xOf: (i: number) => number,
  yOf: (value: number) => number,
  i0: number,
  i1: number,
  barW: number,
): void {
  ctx.fillStyle = lineSpec.color;
  ctx.strokeStyle = lineSpec.color;
  ctx.lineWidth = 1.4;

  if (lineSpec.style === "points") {
    const radius = clamp(barW * 0.25, 1.4, 3);
    for (let i = i0; i <= i1; i++) {
      const value = lineSpec.values[i];
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      const x = xOf(i);
      const y = yOf(value);
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    return;
  }

  ctx.beginPath();
  let pen = false;
  for (let i = i0; i <= i1; i++) {
    const value = lineSpec.values[i];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      pen = false;
      continue;
    }
    const x = xOf(i);
    const y = yOf(value);
    if (!pen) {
      ctx.moveTo(x, y);
      pen = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
}

function paneValueRange(
  computed: ComputedIndicator,
  i0: number,
  i1: number,
): { min: number; max: number } | null {
  let min = computed.min;
  let max = computed.max;
  let seen = false;
  for (const lineSpec of computed.lines) {
    for (let i = i0; i <= i1; i++) {
      const value = lineSpec.values[i];
      if (typeof value === "number" && Number.isFinite(value)) {
        if (min === undefined || value < min) min = value;
        if (max === undefined || value > max) max = value;
        seen = true;
      }
    }
  }
  for (const guide of computed.guides ?? []) {
    if (min === undefined || guide.value < min) min = guide.value;
    if (max === undefined || guide.value > max) max = guide.value;
    seen = true;
  }
  if (!seen || min === undefined || max === undefined) return null;
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.12;
  return { min: min - pad, max: max + pad };
}

interface SubpaneContext {
  i0: number;
  i1: number;
  xOf: (i: number) => number;
  plotW: number;
  width: number;
  legendIndex: number;
  height: number;
}

function drawSubpane(
  ctx: CanvasRenderingContext2D,
  pane: PaneBox,
  computed: ComputedIndicator,
  ctxState: SubpaneContext,
): void {
  const { i0, i1, xOf, plotW, legendIndex } = ctxState;
  const top = pane.top;
  const h = pane.height;

  ctx.fillStyle = "#0b0f14";
  ctx.fillRect(0, top, plotW, h);
  ctx.strokeStyle = BORDER;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, Math.round(top) + 0.5);
  ctx.lineTo(plotW, Math.round(top) + 0.5);
  ctx.stroke();

  const scale = paneValueRange(computed, i0, i1);
  if (!scale) return;
  const yOf = (value: number): number => top + h - ((value - scale.min) / (scale.max - scale.min)) * h;

  // grid + right axis labels
  const ticks = priceTicks(scale.min, scale.max, 3);
  ctx.font = "10px system-ui, -apple-system, sans-serif";
  for (const tick of ticks) {
    const y = Math.round(yOf(tick)) + 0.5;
    if (y < top + 2 || y > top + h - 2) continue;
    ctx.strokeStyle = GRID;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(plotW, y);
    ctx.stroke();
    ctx.fillStyle = AXIS_TEXT;
    ctx.textAlign = "left";
    ctx.fillText(fmtPrice(tick), plotW + 6, y + 3);
  }

  // guides
  for (const guide of computed.guides ?? []) {
    const y = Math.round(yOf(guide.value)) + 0.5;
    if (y < top || y > top + h) continue;
    ctx.save();
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = "#444c56";
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(plotW, y);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = "#6e7681";
    ctx.textAlign = "left";
    ctx.fillText(guide.label, 4, y - 3);
  }

  // lines
  for (const lineSpec of computed.lines) {
    if (lineSpec.style === "histogram") {
      const baseline = lineSpec.baseline ?? 0;
      const baseY = clamp(yOf(baseline), top, top + h);
      const barW = Math.max(1, Math.min((plotW / Math.max(i1 - i0 + 1, 1)) * 0.7, 12));
      for (let i = i0; i <= i1; i++) {
        const value = lineSpec.values[i];
        if (typeof value !== "number" || !Number.isFinite(value)) continue;
        const y = yOf(value);
        ctx.fillStyle = value >= baseline ? UP_COLOR : DOWN_COLOR;
        const rectTop = Math.min(y, baseY);
        const rectH = Math.max(Math.abs(y - baseY), 1);
        ctx.fillRect(xOf(i) - barW / 2, rectTop, barW, rectH);
      }
      continue;
    }
    drawLine(ctx, lineSpec, xOf, yOf, i0, i1, plotW / Math.max(i1 - i0 + 1, 1));
  }

  // legend
  ctx.font = "11px system-ui, -apple-system, sans-serif";
  ctx.textAlign = "left";
  let legendY = top + 12;
  for (const lineSpec of computed.lines) {
    const value = lineSpec.values[legendIndex];
    ctx.fillStyle = lineSpec.color;
    ctx.fillRect(8, legendY - 7, 10, 2);
    ctx.fillStyle = "#c9d1d9";
    const suffix =
      typeof value === "number" && Number.isFinite(value) ? `  ${fmtPrice(value)}` : "";
    ctx.fillText(`${lineSpec.name}${suffix}`, 23, legendY);
    legendY += 13;
    if (legendY > top + h - 4) break;
  }
}

function drawTag(
  ctx: CanvasRenderingContext2D,
  plotW: number,
  y: number,
  text: string,
  background: string,
  color: string,
): void {
  ctx.font = "11px system-ui, -apple-system, sans-serif";
  const width = ctx.measureText(text).width + 12;
  ctx.fillStyle = background;
  ctx.fillRect(plotW + 1, y - 8, Math.max(width, 40), 16);
  ctx.fillStyle = color;
  ctx.textAlign = "left";
  ctx.fillText(text, plotW + 6, y + 4);
}

function drawTimeAxisAndFrame(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  plotW: number,
  timeH: number,
): void {
  ctx.strokeStyle = BORDER;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, height - timeH + 0.5);
  ctx.lineTo(width, height - timeH + 0.5);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(plotW + 0.5, 0);
  ctx.lineTo(plotW + 0.5, height);
  ctx.stroke();
}
