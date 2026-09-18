import { useEffect, useState } from "react";

import { API_BASE } from "../../lib/constants";
import type { HistoryCandle } from "../../types/market";

type ForecastRow = Record<string, string | number>;

export function KronosForecast({ bars }: { bars: HistoryCandle[] }) {
  const [rows, setRows] = useState<ForecastRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setRows([]);
    setMessage(null);
  }, [bars]);

  async function requestForecast() {
    setLoading(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/forecast/kronos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bars, horizon: 20, frequency: "D" }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Forecast request failed");
      setRows(body.forecast ?? []);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Forecast request failed");
    } finally {
      setLoading(false);
    }
  }

  const last = rows.at(-1);
  const close = last?.close ?? last?.Close;
  return (
    <section style={{ border: "1px solid #30363d", borderRadius: "6px", padding: "0.65rem" }}>
      <strong>Kronos forecast</strong>
      <button disabled={loading || bars.length < 20} onClick={requestForecast} style={{ marginLeft: "0.65rem" }}>
        {loading ? "Forecasting…" : "Forecast next 20 bars"}
      </button>
      {close !== undefined ? <span style={{ marginLeft: "0.65rem" }}>Final projected close: {Number(close).toFixed(2)}</span> : null}
      {message ? <p role="alert" style={{ color: "#f0883e", marginBottom: 0 }}>{message}</p> : null}
    </section>
  );
}
