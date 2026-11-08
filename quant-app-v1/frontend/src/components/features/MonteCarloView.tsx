import { useMemo } from "react";

import { useAuth } from "../../context/AuthContext";
import { useHistory } from "../../hooks/useHistory";
import { MonteCarloPanel } from "./MonteCarloPanel";

/* §5.1 Monte Carlo as a navigation-level surface.

   The series is the selected symbol's own daily closes, fetched from the chart's
   provider, and the simulated paths start from its last close. Nothing here is
   hand-entered: the panel posts those returns to POST /quant/monte-carlo, which
   hashes them into the response. The report screen keeps its own tab for
   resampling a stored run's equity curve. */

const LOOKBACK_BARS = 250;
const MIN_CLOSES = 21;

const day = (epochSeconds: number | null | undefined) =>
  epochSeconds === null || epochSeconds === undefined
    ? "—"
    : new Date(epochSeconds * 1000).toISOString().slice(0, 10);

const money = (value: number) =>
  value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function MonteCarloView({ symbol }: { symbol: string }) {
  const { token } = useAuth();
  const { data, loading, error, retry } = useHistory(symbol, "1d", LOOKBACK_BARS);

  const { series, lastClose, asOf, bars } = useMemo(() => {
    const usable = data.filter((candle) => Number.isFinite(candle.close) && candle.close > 0);
    const closes = usable.map((candle) => candle.close);
    if (closes.length < MIN_CLOSES) {
      return { series: null, lastClose: null, asOf: null, bars: closes.length };
    }
    const returns = closes.slice(1).map((close, index) => close / closes[index]! - 1);
    const startEquity = closes[closes.length - 1]!;
    return {
      series: {
        returns,
        startEquity,
        label: `daily returns of ${symbol.toUpperCase()}`,
      },
      lastClose: startEquity,
      asOf: usable[usable.length - 1]?.time ?? null,
      bars: closes.length,
    };
  }, [data, symbol]);

  if (loading) {
    return (
      <p className="report-note" role="status">
        Loading {symbol.toUpperCase()} daily bars…
      </p>
    );
  }

  if (error || !series) {
    return (
      <div className="report-section">
        <p className="report-empty">
          {error
            ? `${symbol.toUpperCase()} daily bars are unavailable (${error}). The simulation needs at least ${MIN_CLOSES} closes.`
            : `No usable daily bars for ${symbol.toUpperCase()}; the simulation needs at least ${MIN_CLOSES} closes.`}
        </p>
        <button type="button" className="btn-secondary" onClick={retry}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <>
      <p
        className="report-note mc-source"
        data-bars={bars}
        data-last-close={lastClose}
        data-as-of={asOf ?? ""}
      >
        Resampling {series.returns.length} daily returns of {symbol.toUpperCase()} · last close{" "}
        {money(lastClose!)} on {day(asOf)}
      </p>
      <MonteCarloPanel
        token={token}
        series={series}
        bars={bars}
        initialCapital={lastClose ?? undefined}
      />
    </>
  );
}
