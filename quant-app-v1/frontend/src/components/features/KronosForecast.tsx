import { useEffect, useRef, useState } from "react";

import { API_BASE } from "../../lib/constants";
import type { HistoryCandle } from "../../types/market";

interface ForecastRow {
  index: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

const HORIZONS = [5, 10, 20] as const;

const FREQ_LABEL: Record<string, string> = {
  D: "days",
  h: "hours",
  W: "weeks",
  "5min": "5-minute bars",
  min: "minutes",
};

function fmt(value: number | undefined, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function pct(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function dayLabel(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso.slice(0, 10);
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Kronos predictions panel (Markets tab).
 *
 * POSTs the visible candles to /forecast/kronos and renders the projected
 * path: summary stats, a sparkline of history + forecast, and a per-day table.
 * Auto-runs once per symbol/timeframe; the horizon chips re-run on demand.
 */
export function KronosForecast({
  bars,
  ticker,
  frequency,
}: {
  bars: HistoryCandle[];
  ticker: string;
  frequency: string;
}) {
  const [horizon, setHorizon] = useState(10);
  const [rows, setRows] = useState<ForecastRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);
  const autoStartedFor = useRef<string | null>(null);
  const sparkRef = useRef<HTMLCanvasElement | null>(null);

  const runKey = `${ticker}|${frequency}`;
  const unit = FREQ_LABEL[frequency] ?? "bars";

  async function runForecast(nextHorizon: number) {
    const seq = ++requestSeq.current;
    setLoading(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/forecast/kronos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bars, horizon: nextHorizon, frequency }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string;
        forecast?: ForecastRow[];
      };
      if (!response.ok) throw new Error(body.detail ?? "Forecast request failed");
      if (seq !== requestSeq.current) return;
      setRows(body.forecast ?? []);
    } catch (error) {
      if (seq !== requestSeq.current) return;
      setRows([]);
      setMessage(error instanceof Error ? error.message : "Forecast request failed");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }

  // Clear stale predictions when the symbol or timeframe changes.
  useEffect(() => {
    setRows([]);
    setMessage(null);
  }, [runKey]);

  // Auto-run once per symbol/timeframe once enough candles have loaded.
  useEffect(() => {
    if (bars.length >= 20 && autoStartedFor.current !== runKey) {
      autoStartedFor.current = runKey;
      void runForecast(horizon);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars.length, runKey]);

  const lastClose = bars.at(-1)?.close;
  const finalClose = rows.at(-1)?.close;
  const movePct =
    lastClose && finalClose ? ((finalClose - lastClose) / lastClose) * 100 : undefined;
  const minLow = rows.length ? Math.min(...rows.map((r) => r.low)) : undefined;
  const maxHigh = rows.length ? Math.max(...rows.map((r) => r.high)) : undefined;
  const upDays = rows.reduce((count, row, i) => {
    const prevRow = i > 0 ? rows[i - 1] : undefined;
    return prevRow && row.close > prevRow.close ? count + 1 : count;
  }, 0);
  const direction =
    movePct === undefined ? "" : movePct >= 0 ? "k-up" : "k-down";

  // Sparkline: recent history closes followed by the projected path.
  useEffect(() => {
    const canvas = sparkRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth || canvas.parentElement?.clientWidth || 600;
    const cssHeight = 96;
    canvas.width = Math.max(1, Math.floor(cssWidth * dpr));
    canvas.height = Math.max(1, Math.floor(cssHeight * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);
    if (bars.length < 2) return;

    const history = bars.slice(-60).map((b) => b.close);
    const future = rows.map((r) => r.close);
    const all = [...history, ...future];
    const min = Math.min(...all);
    const max = Math.max(...all);
    const span = max - min || 1;
    const pad = 8;
    const xOf = (i: number, total: number) =>
      pad + ((cssWidth - pad * 2) * i) / Math.max(1, total - 1);
    const yOf = (v: number) => cssHeight - pad - ((cssHeight - pad * 2) * (v - min)) / span;

    // history line
    ctx.beginPath();
    history.forEach((v, i) => {
      const x = xOf(i, all.length);
      const y = yOf(v);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#58a6ff";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    if (future.length) {
      // divider between history and forecast
      const divX = xOf(history.length - 1, all.length);
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = "#484f58";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(divX, 4);
      ctx.lineTo(divX, cssHeight - 4);
      ctx.stroke();
      ctx.restore();

      // forecast line continues from the last actual close
      ctx.beginPath();
      history.slice(-1).forEach((v, i) => {
        ctx.moveTo(xOf(history.length - 1 + i, all.length), yOf(v));
      });
      future.forEach((v, i) => {
        ctx.lineTo(xOf(history.length + i, all.length), yOf(v));
      });
      ctx.strokeStyle = "#f0883e";
      ctx.lineWidth = 1.75;
      ctx.stroke();

      // end marker
      const endX = xOf(all.length - 1, all.length);
      const lastFuture = future[future.length - 1];
      if (lastFuture !== undefined) {
        const endY = yOf(lastFuture);
        ctx.beginPath();
        ctx.arc(endX, endY, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#f0883e";
        ctx.fill();
      }
    }

    // start marker
    const firstClose = history[0];
    if (firstClose !== undefined) {
      const startX = xOf(0, all.length);
      const startY = yOf(firstClose);
      ctx.beginPath();
      ctx.arc(startX, startY, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = "#58a6ff";
      ctx.fill();
    }
  }, [bars, rows, ticker, frequency]);

  return (
    <section className="kronos-panel" aria-label="Kronos predictions">
      <div className="kronos-head">
        <div className="kronos-title">
          <strong>Kronos predictions</strong>
          <span className="kronos-sub">
            {ticker} · next {horizon} {unit}
          </span>
        </div>
        <div className="kronos-controls">
          <div className="kronos-horizon" role="group" aria-label="Forecast horizon">
            {HORIZONS.map((h) => (
              <button
                key={h}
                type="button"
                className={`kronos-chip ${horizon === h ? "active" : ""}`}
                aria-pressed={horizon === h}
                onClick={() => {
                  setHorizon(h);
                  if (rows.length || autoStartedFor.current === runKey) void runForecast(h);
                }}
              >
                {h}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="kronos-run"
            disabled={loading || bars.length < 20}
            onClick={() => void runForecast(horizon)}
          >
            {loading ? "Forecasting…" : rows.length ? "Re-run" : "Run forecast"}
          </button>
        </div>
      </div>

      {message ? (
        <p className="kronos-error" role="alert">
          {message}
        </p>
      ) : null}

      {!message && rows.length === 0 && !loading ? (
        <p className="kronos-hint">
          {bars.length < 20
            ? "Waiting for at least 20 candles to build a forecast…"
            : `Project the next ${horizon} ${unit} from the last ${bars.length} candles — zero-shot, no training data leaves this machine.`}
        </p>
      ) : null}

      {rows.length > 0 ? (
        <>
          <div className="kronos-summary">
            <div className="kronos-stat">
              <div className="k-label">Projected move</div>
              <div className={`k-value ${direction}`}>
                {fmt(finalClose)} <span className="k-delta">{pct(movePct)}</span>
              </div>
            </div>
            <div className="kronos-stat">
              <div className="k-label">Forecast range</div>
              <div className="k-value">
                {fmt(minLow)} – {fmt(maxHigh)}
              </div>
            </div>
            <div className="kronos-stat">
              <div className="k-label">Up days</div>
              <div className="k-value">
                {upDays}/{rows.length}
              </div>
            </div>
          </div>
          <canvas ref={sparkRef} className="kronos-spark" aria-hidden="true" />
          <div className="kronos-table-wrap">
            <table className="kronos-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Predicted close</th>
                  <th>Δ day</th>
                  <th>Low – high</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => {
                  const prevRow = i === 0 ? undefined : rows[i - 1];
                  const prev = i === 0 ? lastClose : prevRow?.close;
                  const delta = prev ? ((row.close - prev) / prev) * 100 : undefined;
                  const cls =
                    delta === undefined ? "" : delta >= 0 ? "k-up" : "k-down";
                  return (
                    <tr key={row.index}>
                      <td>{dayLabel(row.index)}</td>
                      <td>{fmt(row.close)}</td>
                      <td className={cls}>{pct(delta)}</td>
                      <td>
                        {fmt(row.low)} – {fmt(row.high)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
