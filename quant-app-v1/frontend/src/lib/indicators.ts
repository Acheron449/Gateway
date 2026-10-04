/**
 * Indicator catalog + computations for the hand-built canvas chart.
 *
 * Everything is computed client-side from the bars the chart already holds.
 * NaN marks "not enough history yet"; the renderer converts it to gaps.
 */
import type { HistoryCandle } from "../types/market";

export type IndicatorKind = "overlay" | "pane";

export type IndicatorCategory =
  | "Averages/Bands"
  | "Momentum/Oscillator"
  | "Money Flow"
  | "Projection"
  | "Statistical"
  | "Support/Resistance"
  | "Trend Analysis";

export const INDICATOR_CATEGORIES: readonly IndicatorCategory[] = [
  "Averages/Bands",
  "Momentum/Oscillator",
  "Money Flow",
  "Projection",
  "Statistical",
  "Support/Resistance",
  "Trend Analysis",
];

export interface IndicatorDef {
  id: string;
  name: string;
  category: IndicatorCategory;
  kind: IndicatorKind;
  /** Part of the "Common Indicators" shortlist. */
  common?: boolean;
  /** One-line description shown on the row's info hover. */
  desc: string;
}

export interface IndicatorLine {
  name: string;
  color: string;
  values: Array<number | null>;
  style?: "line" | "histogram" | "points";
  /** Baseline for histogram lines (default 0). */
  baseline?: number;
}

export interface ComputedIndicator {
  id: string;
  name: string;
  kind: IndicatorKind;
  lines: IndicatorLine[];
  /** Fixed pane scale (e.g. oscillators bound to 0–100). */
  min?: number;
  max?: number;
  guides?: Array<{ value: number; label: string }>;
}

const PALETTE = [
  "#2962ff",
  "#ff6d00",
  "#e040fb",
  "#00bcd4",
  "#00e676",
  "#ffd600",
  "#ff1744",
  "#651fff",
  "#18ffff",
  "#b2ff59",
];

export const INDICATORS: readonly IndicatorDef[] = [
  // --- Averages/Bands -------------------------------------------------
  { id: "sma", name: "Moving Average (SMA)", category: "Averages/Bands", kind: "overlay", common: true, desc: "Simple arithmetic mean of the last 20 closes." },
  { id: "ema", name: "Moving Average Exponential (EMA)", category: "Averages/Bands", kind: "overlay", common: true, desc: "Weighted mean giving exponentially more weight to recent closes." },
  { id: "wma", name: "Moving Average Weighted (WMA)", category: "Averages/Bands", kind: "overlay", desc: "Linear-weighted mean; the newest bar counts most." },
  { id: "vwma", name: "Volume Weighted Moving Average (VWMA)", category: "Averages/Bands", kind: "overlay", desc: "Moving average weighted by per-bar volume." },
  { id: "vwap", name: "VWAP", category: "Averages/Bands", kind: "overlay", common: true, desc: "Volume-weighted average price anchored at the start of the loaded range." },
  { id: "avwap", name: "Anchored VWAP", category: "Averages/Bands", kind: "overlay", desc: "VWAP re-anchored at the lowest low of the loaded range." },
  { id: "bb", name: "Bollinger Bands", category: "Averages/Bands", kind: "overlay", common: true, desc: "SMA 20 with ±2 standard-deviation envelope." },
  { id: "kc", name: "Keltner Channel", category: "Averages/Bands", kind: "overlay", desc: "EMA 20 ± 2 × ATR(14) volatility channel." },
  { id: "env", name: "Envelopes (Moving Avg)", category: "Averages/Bands", kind: "overlay", desc: "SMA 20 shifted ±1% — overbought/oversold bounds." },
  { id: "atrb", name: "ATR Bands", category: "Averages/Bands", kind: "overlay", desc: "SMA 20 ± 2 × Average True Range." },

  // --- Momentum/Oscillator -------------------------------------------
  { id: "rsi", name: "RSI", category: "Momentum/Oscillator", kind: "pane", common: true, desc: "Relative Strength Index (14) — 0–100 momentum oscillator." },
  { id: "macd", name: "MACD", category: "Momentum/Oscillator", kind: "pane", common: true, desc: "12/26 EMA difference with a 9 EMA signal line and histogram." },
  { id: "stoch", name: "Stochastic", category: "Momentum/Oscillator", kind: "pane", common: true, desc: "%K/%D location of close within the 14-bar range." },
  { id: "stochrsi", name: "Stochastic RSI", category: "Momentum/Oscillator", kind: "pane", desc: "Stochastic applied to RSI — a faster, bounded momentum read." },
  { id: "cci", name: "CCI", category: "Momentum/Oscillator", kind: "pane", desc: "Commodity Channel Index (20) around the typical-price mean." },
  { id: "willr", name: "Williams %R", category: "Momentum/Oscillator", kind: "pane", desc: "Closing range momentum (14), scaled −100 to 0." },
  { id: "mom", name: "Momentum", category: "Momentum/Oscillator", kind: "pane", desc: "Close minus the close 10 bars ago." },
  { id: "roc", name: "Rate of Change (ROC)", category: "Momentum/Oscillator", kind: "pane", desc: "Percentage change over the last 10 bars." },
  { id: "trix", name: "TRIX", category: "Momentum/Oscillator", kind: "pane", desc: "Rate of change of a triple-smoothed 15-period EMA." },
  { id: "uo", name: "Ultimate Oscillator", category: "Momentum/Oscillator", kind: "pane", desc: "Weighted 7/14/28-bar buying pressure oscillator." },
  { id: "ao", name: "Awesome Oscillator", category: "Momentum/Oscillator", kind: "pane", desc: "SMA(5) − SMA(34) of median price." },

  // --- Money Flow -----------------------------------------------------
  { id: "ad", name: "Accumulation/Distribution", category: "Money Flow", kind: "pane", desc: "Cumulative volume flow weighted by close location in the bar range." },
  { id: "mfi", name: "Money Flow Index (MFI)", category: "Money Flow", kind: "pane", desc: "Volume-weighted RSI (14)." },
  { id: "obv", name: "On Balance Volume (OBV)", category: "Money Flow", kind: "pane", common: true, desc: "Cumulative volume signed by the direction of each close." },
  { id: "cmf", name: "Chaikin Money Flow", category: "Money Flow", kind: "pane", desc: "20-bar average of A/D money-flow volume." },
  { id: "fi", name: "Force Index", category: "Money Flow", kind: "pane", desc: "EMA(13) of price change × volume." },
  { id: "emv", name: "Ease of Movement", category: "Money Flow", kind: "pane", desc: "Distance travelled per unit of volume — low values mean heavy resistance." },

  // --- Projection -----------------------------------------------------
  { id: "psar", name: "Parabolic SAR", category: "Projection", kind: "overlay", common: true, desc: "Stop-and-reverse dots trailing the trend (0.02/0.02)." },
  { id: "fib", name: "Fibonacci Retracement", category: "Projection", kind: "overlay", desc: "Classic 0–100% retracement levels across the loaded range." },
  { id: "pivots", name: "Pivot Points (Classic)", category: "Projection", kind: "overlay", desc: "Floor-trader P/R1–R3/S1–S3 from the previous session." },
  { id: "zigzag", name: "ZigZag", category: "Projection", kind: "overlay", desc: "Connects swings larger than 5%, filtering noise." },

  // --- Statistical ----------------------------------------------------
  { id: "atr", name: "Average True Range", category: "Statistical", kind: "pane", common: true, desc: "Wilder-smoothed volatility (14) in price units." },
  { id: "stddev", name: "Standard Deviation", category: "Statistical", kind: "pane", desc: "20-bar rolling population standard deviation of close." },
  { id: "hv", name: "Historical Volatility", category: "Statistical", kind: "pane", desc: "Annualised (252d) standard deviation of log returns, in %." },
  { id: "zscore", name: "Z-Score", category: "Statistical", kind: "pane", desc: "How many standard deviations the close sits from its 20-bar mean." },

  // --- Support/Resistance --------------------------------------------
  { id: "donchian", name: "Donchian Channel", category: "Support/Resistance", kind: "overlay", desc: "Highest-high / lowest-low envelope of the last 20 bars." },
  { id: "pchannel", name: "Price Channel", category: "Support/Resistance", kind: "overlay", desc: "20-bar extremes excluding the current bar — breakout levels." },
  { id: "sr", name: "Support & Resistance (Rolling)", category: "Support/Resistance", kind: "overlay", desc: "Pivot-based rolling support, mid and resistance from 20-bar extremes." },
  { id: "linregch", name: "Linear Regression Channel", category: "Support/Resistance", kind: "overlay", desc: "Least-squares trend of the last 100 bars ±2 residual σ." },

  // --- Trend Analysis -------------------------------------------------
  { id: "adx", name: "ADX/DMS", category: "Trend Analysis", kind: "pane", common: true, desc: "Average Directional Index with +DI/−DI (14) — trend strength." },
  { id: "aroon", name: "Aroon", category: "Trend Analysis", kind: "pane", desc: "Time since the 25-bar high/low, as percentages." },
  { id: "aroonosc", name: "Aroon Oscillator", category: "Trend Analysis", kind: "pane", desc: "Aroon Up minus Aroon Down (−100 to 100)." },
  { id: "alligator", name: "Alligator", category: "Trend Analysis", kind: "overlay", desc: "Three smoothed, future-shifted balance lines (jaw/teeth/lips)." },
  { id: "ichimoku", name: "Ichimoku Cloud", category: "Trend Analysis", kind: "overlay", desc: "Tenkan/Kijun lines plus forward-shifted Senkou spans." },
  { id: "supertrend", name: "SuperTrend", category: "Trend Analysis", kind: "overlay", desc: "ATR(10)×3 trailing trend line that flips on breaks." },
  { id: "vortex", name: "Vortex Indicator", category: "Trend Analysis", kind: "pane", desc: "VI+/VI− (16) — directional movement ratio." },
];

export const INDICATOR_MAP: ReadonlyMap<string, IndicatorDef> = new Map(
  INDICATORS.map((def) => [def.id, def]),
);

// ---------------------------------------------------------------------------
// Numeric helpers — NaN means "no value yet"
// ---------------------------------------------------------------------------

function filled(len: number): number[] {
  return new Array<number>(len).fill(NaN);
}

function sma(src: number[], period: number): number[] {
  const n = src.length;
  const out = filled(n);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += src[i] ?? NaN;
    if (i >= period) sum -= src[i - period] ?? NaN;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function ema(src: number[], period: number): number[] {
  const n = src.length;
  const out = filled(n);
  if (period <= 0) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  let seeded = 0;
  let prev = NaN;
  for (let i = 0; i < n; i++) {
    const v = src[i] ?? NaN;
    if (!Number.isFinite(v)) continue;
    if (!Number.isFinite(prev)) {
      seed += v;
      seeded += 1;
      if (seeded >= period) {
        prev = seed / period;
        out[i] = prev;
      }
      continue;
    }
    prev = v * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function rma(src: number[], period: number): number[] {
  const n = src.length;
  const out = filled(n);
  if (period <= 0) return out;
  let seed = 0;
  let seeded = 0;
  let prev = NaN;
  for (let i = 0; i < n; i++) {
    const v = src[i] ?? NaN;
    if (!Number.isFinite(v)) continue;
    if (!Number.isFinite(prev)) {
      seed += v;
      seeded += 1;
      if (seeded >= period) {
        prev = seed / period;
        out[i] = prev;
      }
      continue;
    }
    prev = (prev * (period - 1) + v) / period;
    out[i] = prev;
  }
  return out;
}

function wma(src: number[], period: number): number[] {
  const n = src.length;
  const out = filled(n);
  if (period <= 0) return out;
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    let ok = true;
    for (let j = 0; j < period; j++) {
      const v = src[i - j] ?? NaN;
      if (!Number.isFinite(v)) {
        ok = false;
        break;
      }
      acc += v * (period - j);
    }
    if (ok) out[i] = acc / denom;
  }
  return out;
}

function stdev(src: number[], period: number): number[] {
  const n = src.length;
  const out = filled(n);
  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    let sumSq = 0;
    let ok = true;
    for (let j = 0; j < period; j++) {
      const v = src[i - j] ?? NaN;
      if (!Number.isFinite(v)) {
        ok = false;
        break;
      }
      sum += v;
      sumSq += v * v;
    }
    if (!ok) continue;
    const mean = sum / period;
    const variance = sumSq / period - mean * mean;
    out[i] = Math.sqrt(Math.max(variance, 0));
  }
  return out;
}

function rollingExtreme(src: number[], period: number, mode: "max" | "min"): number[] {
  const n = src.length;
  const out = filled(n);
  for (let i = period - 1; i < n; i++) {
    let best = mode === "max" ? -Infinity : Infinity;
    let ok = true;
    for (let j = 0; j < period; j++) {
      const v = src[i - j] ?? NaN;
      if (!Number.isFinite(v)) {
        ok = false;
        break;
      }
      best = mode === "max" ? Math.max(best, v) : Math.min(best, v);
    }
    if (ok) out[i] = best;
  }
  return out;
}

function shiftsForward(values: number[], bars: number): number[] {
  const out = filled(values.length);
  for (let i = 0; i < values.length; i++) {
    const v = values[i] ?? NaN;
    const target = i + bars;
    if (Number.isFinite(v) && target < out.length) out[target] = v;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Bar series
// ---------------------------------------------------------------------------

function closesOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => b.close);
}

function highsOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => b.high);
}

function lowsOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => b.low);
}

function volumesOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => (typeof b.volume === "number" && Number.isFinite(b.volume) ? b.volume : 0));
}

function trueRangeOf(bars: HistoryCandle[]): number[] {
  const out = filled(bars.length);
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    const prev = i > 0 ? bars[i - 1] : undefined;
    if (!bar) continue;
    if (!prev) {
      out[i] = bar.high - bar.low;
      continue;
    }
    out[i] = Math.max(
      bar.high - bar.low,
      Math.abs(bar.high - prev.close),
      Math.abs(bar.low - prev.close),
    );
  }
  return out;
}

function typicalOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => (b.high + b.low + b.close) / 3);
}

function medianOf(bars: HistoryCandle[]): number[] {
  return bars.map((b) => (b.high + b.low) / 2);
}

function rsiOf(closes: number[], period = 14): number[] {
  const n = closes.length;
  const gains = filled(n);
  const losses = filled(n);
  for (let i = 1; i < n; i++) {
    const cur = closes[i] ?? NaN;
    const prev = closes[i - 1] ?? NaN;
    const diff = cur - prev;
    gains[i] = Math.max(diff, 0);
    losses[i] = Math.max(-diff, 0);
  }
  const avgGain = rma(gains, period);
  const avgLoss = rma(losses, period);
  const out = filled(n);
  for (let i = 0; i < n; i++) {
    const g = avgGain[i] ?? NaN;
    const l = avgLoss[i] ?? NaN;
    if (!Number.isFinite(g) || !Number.isFinite(l)) continue;
    if (l === 0) {
      out[i] = 100;
      continue;
    }
    const rs = g / l;
    out[i] = 100 - 100 / (1 + rs);
  }
  return out;
}

function toValues(values: number[]): Array<number | null> {
  return values.map((v) => (Number.isFinite(v) ? v : null));
}

function line(
  name: string,
  color: string,
  values: number[],
  style?: IndicatorLine["style"],
  baseline?: number,
): IndicatorLine {
  const result: IndicatorLine = { name, color, values: toValues(values) };
  if (style) result.style = style;
  if (baseline !== undefined) result.baseline = baseline;
  return result;
}

// ---------------------------------------------------------------------------
// Indicator computations
// ---------------------------------------------------------------------------

function computeBands(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const closes = closesOf(bars);
  const typical = typicalOf(bars);
  const volumes = volumesOf(bars);
  const atrArr = rma(trueRangeOf(bars), 14);

  const mid = sma(closes, 20);
  const sd = stdev(closes, 20);

  switch (id) {
    case "sma":
      return { id, name: "SMA 20", kind: "overlay", lines: [line("SMA 20", PALETTE[0] ?? "#2962ff", mid)] };
    case "ema":
      return { id, name: "EMA 20", kind: "overlay", lines: [line("EMA 20", PALETTE[0] ?? "#2962ff", ema(closes, 20))] };
    case "wma":
      return { id, name: "WMA 20", kind: "overlay", lines: [line("WMA 20", PALETTE[0] ?? "#2962ff", wma(closes, 20))] };
    case "vwma": {
      const num = filled(bars.length);
      const den = filled(bars.length);
      for (let i = 19; i < bars.length; i++) {
        let s = 0;
        let v = 0;
        for (let j = 0; j < 20; j++) {
          const bar = bars[i - j];
          if (!bar) continue;
          s += ((bar.high + bar.low + bar.close) / 3) * (volumes[i - j] ?? 0);
          v += volumes[i - j] ?? 0;
        }
        num[i] = s;
        den[i] = v;
      }
      const vwmaArr = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const d = den[i] ?? NaN;
        if (Number.isFinite(d) && d !== 0) vwmaArr[i] = (num[i] ?? NaN) / d;
      }
      return { id, name: "VWMA 20", kind: "overlay", lines: [line("VWMA 20", PALETTE[0] ?? "#2962ff", vwmaArr)] };
    }
    case "vwap": {
      const vwapArr = filled(bars.length);
      let pv = 0;
      let vv = 0;
      for (let i = 0; i < bars.length; i++) {
        pv += (typical[i] ?? 0) * (volumes[i] ?? 0);
        vv += volumes[i] ?? 0;
        vwapArr[i] = vv > 0 ? pv / vv : NaN;
      }
      return { id, name: "VWAP", kind: "overlay", lines: [line("VWAP", PALETTE[1] ?? "#ff6d00", vwapArr)] };
    }
    case "avwap": {
      let anchor = 0;
      for (let i = 1; i < bars.length; i++) {
        if ((bars[i]?.low ?? Infinity) < (bars[anchor]?.low ?? Infinity)) anchor = i;
      }
      const vwapArr = filled(bars.length);
      let pv = 0;
      let vv = 0;
      for (let i = anchor; i < bars.length; i++) {
        pv += (typical[i] ?? 0) * (volumes[i] ?? 0);
        vv += volumes[i] ?? 0;
        vwapArr[i] = vv > 0 ? pv / vv : NaN;
      }
      return { id, name: "Anchored VWAP", kind: "overlay", lines: [line("AVWAP", PALETTE[1] ?? "#ff6d00", vwapArr)] };
    }
    case "bb": {
      const upper = filled(bars.length);
      const lower = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const m = mid[i] ?? NaN;
        const s = sd[i] ?? NaN;
        if (Number.isFinite(m) && Number.isFinite(s)) {
          upper[i] = m + 2 * s;
          lower[i] = m - 2 * s;
        }
      }
      return {
        id,
        name: "Bollinger Bands",
        kind: "overlay",
        lines: [
          line("BB Upper", PALETTE[2] ?? "#e040fb", upper),
          line("BB Basis", PALETTE[0] ?? "#2962ff", mid),
          line("BB Lower", PALETTE[2] ?? "#e040fb", lower),
        ],
      };
    }
    case "kc": {
      const upper = filled(bars.length);
      const lower = filled(bars.length);
      const basis = ema(closes, 20);
      for (let i = 0; i < bars.length; i++) {
        const b = basis[i] ?? NaN;
        const a = atrArr[i] ?? NaN;
        if (Number.isFinite(b) && Number.isFinite(a)) {
          upper[i] = b + 2 * a;
          lower[i] = b - 2 * a;
        }
      }
      return {
        id,
        name: "Keltner Channel",
        kind: "overlay",
        lines: [
          line("KC Upper", PALETTE[3] ?? "#00bcd4", upper),
          line("KC Basis", PALETTE[0] ?? "#2962ff", basis),
          line("KC Lower", PALETTE[3] ?? "#00bcd4", lower),
        ],
      };
    }
    case "env": {
      const upper = mid.map((v) => (Number.isFinite(v) ? v * 1.01 : NaN));
      const lower = mid.map((v) => (Number.isFinite(v) ? v * 0.99 : NaN));
      return {
        id,
        name: "Envelopes",
        kind: "overlay",
        lines: [
          line("ENV Upper", PALETTE[4] ?? "#00e676", upper),
          line("ENV Basis", PALETTE[0] ?? "#2962ff", mid),
          line("ENV Lower", PALETTE[4] ?? "#00e676", lower),
        ],
      };
    }
    case "atrb": {
      const upper = filled(bars.length);
      const lower = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const m = mid[i] ?? NaN;
        const a = atrArr[i] ?? NaN;
        if (Number.isFinite(m) && Number.isFinite(a)) {
          upper[i] = m + 2 * a;
          lower[i] = m - 2 * a;
        }
      }
      return {
        id,
        name: "ATR Bands",
        kind: "overlay",
        lines: [
          line("ATR Upper", PALETTE[5] ?? "#ffd600", upper),
          line("ATR Basis", PALETTE[0] ?? "#2962ff", mid),
          line("ATR Lower", PALETTE[5] ?? "#ffd600", lower),
        ],
      };
    }
    default:
      return null;
  }
}

function computeMomentum(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const closes = closesOf(bars);

  switch (id) {
    case "rsi": {
      const rsi = rsiOf(closes, 14);
      return {
        id,
        name: "RSI 14",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [
          { value: 70, label: "70" },
          { value: 30, label: "30" },
        ],
        lines: [line("RSI 14", PALETTE[6] ?? "#ff1744", rsi)],
      };
    }
    case "macd": {
      const fast = ema(closes, 12);
      const slow = ema(closes, 26);
      const macdArr = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const f = fast[i] ?? NaN;
        const s = slow[i] ?? NaN;
        if (Number.isFinite(f) && Number.isFinite(s)) macdArr[i] = f - s;
      }
      const signal = ema(macdArr, 9);
      const hist = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const m = macdArr[i] ?? NaN;
        const sg = signal[i] ?? NaN;
        if (Number.isFinite(m) && Number.isFinite(sg)) hist[i] = m - sg;
      }
      return {
        id,
        name: "MACD",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [
          line("MACD Histogram", "#8b949e", hist, "histogram", 0),
          line("MACD 12/26", PALETTE[0] ?? "#2962ff", macdArr),
          line("Signal 9", PALETTE[1] ?? "#ff6d00", signal),
        ],
      };
    }
    case "stoch": {
      const highs = highsOf(bars);
      const lows = lowsOf(bars);
      const hh = rollingExtreme(highs, 14, "max");
      const ll = rollingExtreme(lows, 14, "min");
      const k = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const h = hh[i] ?? NaN;
        const l = ll[i] ?? NaN;
        if (!Number.isFinite(h) || !Number.isFinite(l) || h === l) continue;
        k[i] = ((closes[i] ?? NaN) - l) / (h - l) * 100;
      }
      const d = sma(k, 3);
      return {
        id,
        name: "Stochastic",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [
          { value: 80, label: "80" },
          { value: 20, label: "20" },
        ],
        lines: [
          line("%K", PALETTE[0] ?? "#2962ff", k),
          line("%D", PALETTE[1] ?? "#ff6d00", d),
        ],
      };
    }
    case "stochrsi": {
      const rsi = rsiOf(closes, 14);
      const hh = rollingExtreme(rsi, 14, "max");
      const ll = rollingExtreme(rsi, 14, "min");
      const k = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const h = hh[i] ?? NaN;
        const l = ll[i] ?? NaN;
        if (!Number.isFinite(h) || !Number.isFinite(l) || h === l) continue;
        k[i] = ((rsi[i] ?? NaN) - l) / (h - l) * 100;
      }
      return {
        id,
        name: "Stochastic RSI",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [
          { value: 80, label: "80" },
          { value: 20, label: "20" },
        ],
        lines: [
          line("StochRSI K", PALETTE[3] ?? "#00bcd4", k),
          line("StochRSI D", PALETTE[7] ?? "#651fff", sma(k, 3)),
        ],
      };
    }
    case "cci": {
      const typical = typicalOf(bars);
      const basis = sma(typical, 20);
      const cciArr = filled(bars.length);
      for (let i = 19; i < bars.length; i++) {
        const b = basis[i] ?? NaN;
        if (!Number.isFinite(b)) continue;
        let dev = 0;
        for (let j = 0; j < 20; j++) dev += Math.abs((typical[i - j] ?? NaN) - b);
        const meanDev = dev / 20;
        if (meanDev !== 0) cciArr[i] = ((typical[i] ?? NaN) - b) / (0.015 * meanDev);
      }
      return {
        id,
        name: "CCI 20",
        kind: "pane",
        guides: [
          { value: 100, label: "100" },
          { value: -100, label: "-100" },
          { value: 0, label: "0" },
        ],
        lines: [line("CCI 20", PALETTE[1] ?? "#ff6d00", cciArr)],
      };
    }
    case "willr": {
      const highs = highsOf(bars);
      const lows = lowsOf(bars);
      const hh = rollingExtreme(highs, 14, "max");
      const ll = rollingExtreme(lows, 14, "min");
      const wr = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const h = hh[i] ?? NaN;
        const l = ll[i] ?? NaN;
        if (!Number.isFinite(h) || !Number.isFinite(l) || h === l) continue;
        wr[i] = (-100 * (h - (closes[i] ?? NaN))) / (h - l);
      }
      return {
        id,
        name: "Williams %R",
        kind: "pane",
        min: -100,
        max: 0,
        guides: [
          { value: -20, label: "-20" },
          { value: -80, label: "-80" },
        ],
        lines: [line("%R", PALETTE[7] ?? "#651fff", wr)],
      };
    }
    case "mom": {
      const mom = filled(bars.length);
      for (let i = 10; i < bars.length; i++) mom[i] = (closes[i] ?? NaN) - (closes[i - 10] ?? NaN);
      return {
        id,
        name: "Momentum 10",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("Momentum 10", PALETTE[4] ?? "#00e676", mom)],
      };
    }
    case "roc": {
      const roc = filled(bars.length);
      for (let i = 10; i < bars.length; i++) {
        const prev = closes[i - 10] ?? NaN;
        if (prev !== 0) roc[i] = (((closes[i] ?? NaN) / prev) - 1) * 100;
      }
      return {
        id,
        name: "ROC 10",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("ROC 10", PALETTE[3] ?? "#00bcd4", roc)],
      };
    }
    case "trix": {
      const e1 = ema(closes, 15);
      const e2 = ema(e1, 15);
      const e3 = ema(e2, 15);
      const trix = filled(bars.length);
      for (let i = 1; i < bars.length; i++) {
        const prev = e3[i - 1] ?? NaN;
        const cur = e3[i] ?? NaN;
        if (Number.isFinite(prev) && Number.isFinite(cur) && prev !== 0) {
          trix[i] = (cur / prev - 1) * 100;
        }
      }
      return {
        id,
        name: "TRIX 15",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("TRIX 15", PALETTE[5] ?? "#ffd600", trix)],
      };
    }
    case "uo": {
      const n = bars.length;
      const bp = filled(n);
      const trr = filled(n);
      for (let i = 0; i < n; i++) {
        const bar = bars[i];
        const prev = i > 0 ? bars[i - 1] : undefined;
        if (!bar) continue;
        const prevClose = prev ? prev.close : bar.close;
        bp[i] = bar.close - Math.min(bar.low, prevClose);
        trr[i] = Math.max(
          bar.high - bar.low,
          prev ? Math.abs(bar.high - prevClose) : 0,
          prev ? Math.abs(bar.low - prevClose) : 0,
        );
      }
      const sumOver = (arr: number[], from: number, to: number): number => {
        let s = 0;
        for (let i = from; i <= to; i++) s += arr[i] ?? 0;
        return s;
      };
      const uo = filled(n);
      for (let i = 27; i < n; i++) {
        const s7 = sumOver(bp, i - 6, i);
        const t7 = sumOver(trr, i - 6, i);
        const s14 = sumOver(bp, i - 13, i);
        const t14 = sumOver(trr, i - 13, i);
        const s28 = sumOver(bp, i - 27, i);
        const t28 = sumOver(trr, i - 27, i);
        const avg = t7 > 0 && t14 > 0 && t28 > 0 ? 4 * (s7 / t7 + s14 / t14 + s28 / t28) : NaN;
        if (Number.isFinite(avg)) uo[i] = avg * 100 / 7;
      }
      return {
        id,
        name: "Ultimate Oscillator",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [
          { value: 70, label: "70" },
          { value: 30, label: "30" },
        ],
        lines: [line("UO 7/14/28", PALETTE[1] ?? "#ff6d00", uo)],
      };
    }
    case "ao": {
      const median = medianOf(bars);
      const fast = sma(median, 5);
      const slow = sma(median, 34);
      const ao = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const f = fast[i] ?? NaN;
        const s = slow[i] ?? NaN;
        if (Number.isFinite(f) && Number.isFinite(s)) ao[i] = f - s;
      }
      return {
        id,
        name: "Awesome Oscillator",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("AO 5/34", PALETTE[4] ?? "#00e676", ao, "histogram", 0)],
      };
    }
    default:
      return null;
  }
}

function computeMoneyFlow(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const volumes = volumesOf(bars);
  const n = bars.length;

  switch (id) {
    case "ad": {
      const ad = filled(n);
      let acc = 0;
      for (let i = 0; i < n; i++) {
        const bar = bars[i];
        if (!bar) continue;
        const range = bar.high - bar.low;
        const mult = range !== 0 ? ((bar.close - bar.low) - (bar.high - bar.close)) / range : 0;
        acc += mult * (volumes[i] ?? 0);
        ad[i] = acc;
      }
      return { id, name: "A/D Line", kind: "pane", lines: [line("A/D", PALETTE[3] ?? "#00bcd4", ad)] };
    }
    case "mfi": {
      const typical = typicalOf(bars);
      const pos = filled(n);
      const neg = filled(n);
      for (let i = 1; i < n; i++) {
        const cur = typical[i] ?? NaN;
        const prev = typical[i - 1] ?? NaN;
        const flow = cur * (volumes[i] ?? 0);
        pos[i] = cur > prev ? flow : 0;
        neg[i] = cur < prev ? flow : 0;
      }
      const sumPos = sma(pos, 14);
      const sumNeg = sma(neg, 14);
      const mfi = filled(n);
      for (let i = 0; i < n; i++) {
        const p = sumPos[i] ?? NaN;
        const ng = sumNeg[i] ?? NaN;
        if (!Number.isFinite(p) || !Number.isFinite(ng)) continue;
        mfi[i] = ng === 0 ? 100 : 100 - 100 / (1 + p / ng);
      }
      return {
        id,
        name: "MFI 14",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [
          { value: 80, label: "80" },
          { value: 20, label: "20" },
        ],
        lines: [line("MFI 14", PALETTE[5] ?? "#ffd600", mfi)],
      };
    }
    case "obv": {
      const obv = filled(n);
      let acc = 0;
      for (let i = 0; i < n; i++) {
        if (i > 0) {
          const cur = bars[i]?.close ?? NaN;
          const prev = bars[i - 1]?.close ?? NaN;
          if (Number.isFinite(cur) && Number.isFinite(prev)) {
            acc += cur > prev ? volumes[i] ?? 0 : cur < prev ? -(volumes[i] ?? 0) : 0;
          }
        }
        obv[i] = acc;
      }
      return { id, name: "OBV", kind: "pane", lines: [line("OBV", PALETTE[0] ?? "#2962ff", obv)] };
    }
    case "cmf": {
      const flow = filled(n);
      const vol = filled(n);
      for (let i = 0; i < n; i++) {
        const bar = bars[i];
        if (!bar) continue;
        const range = bar.high - bar.low;
        const mult = range !== 0 ? ((bar.close - bar.low) - (bar.high - bar.close)) / range : 0;
        flow[i] = mult * (volumes[i] ?? 0);
        vol[i] = volumes[i] ?? 0;
      }
      const f = sma(flow, 20);
      const v = sma(vol, 20);
      const cmf = filled(n);
      for (let i = 0; i < n; i++) {
        const fv = f[i] ?? NaN;
        const vv = v[i] ?? NaN;
        if (Number.isFinite(fv) && Number.isFinite(vv) && vv !== 0) cmf[i] = fv / vv;
      }
      return {
        id,
        name: "Chaikin Money Flow",
        kind: "pane",
        min: -1,
        max: 1,
        guides: [{ value: 0, label: "0" }],
        lines: [line("CMF 20", PALETTE[4] ?? "#00e676", cmf)],
      };
    }
    case "fi": {
      const raw = filled(n);
      for (let i = 1; i < n; i++) {
        const cur = bars[i]?.close ?? NaN;
        const prev = bars[i - 1]?.close ?? NaN;
        raw[i] = (cur - prev) * (volumes[i] ?? 0);
      }
      return {
        id,
        name: "Force Index",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("FI 13", PALETTE[6] ?? "#ff1744", ema(raw, 13))],
      };
    }
    case "emv": {
      const median = medianOf(bars);
      const raw = filled(n);
      for (let i = 1; i < n; i++) {
        const bar = bars[i];
        if (!bar) continue;
        const height = bar.high - bar.low;
        const box = height > 0 ? (volumes[i] ?? 0) / height : NaN;
        if (Number.isFinite(box) && box !== 0) {
          raw[i] = ((median[i] ?? NaN) - (median[i - 1] ?? NaN)) / box;
        }
      }
      return {
        id,
        name: "Ease of Movement",
        kind: "pane",
        guides: [{ value: 0, label: "0" }],
        lines: [line("EMV 14", PALETTE[7] ?? "#651fff", sma(raw, 14))],
      };
    }
    default:
      return null;
  }
}

function computeProjection(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const n = bars.length;

  switch (id) {
    case "psar": {
      const out = filled(n);
      if (n < 3) return { id, name: "Parabolic SAR", kind: "overlay", lines: [line("PSAR", PALETTE[1] ?? "#ff6d00", out, "points")] };
      let up = true;
      let sar = bars[0]?.low ?? 0;
      let ep = bars[0]?.high ?? 0;
      let af = 0.02;
      for (let i = 1; i < n; i++) {
        const bar = bars[i];
        const prevBar = bars[i - 1];
        if (!bar) continue;
        sar = sar + af * (ep - sar);
        if (up) {
          const floor = Math.min(prevBar?.low ?? bar.low, i > 1 ? bars[i - 2]?.low ?? bar.low : bar.low);
          if (sar > floor) sar = floor;
          if (bar.low < sar) {
            up = false;
            sar = ep;
            ep = bar.low;
            af = 0.02;
          } else if (bar.high > ep) {
            ep = bar.high;
            af = Math.min(af + 0.02, 0.2);
          }
        } else {
          const ceiling = Math.max(prevBar?.high ?? bar.high, i > 1 ? bars[i - 2]?.high ?? bar.high : bar.high);
          if (sar < ceiling) sar = ceiling;
          if (bar.high > sar) {
            up = true;
            sar = ep;
            ep = bar.high;
            af = 0.02;
          } else if (bar.low < ep) {
            ep = bar.low;
            af = Math.min(af + 0.02, 0.2);
          }
        }
        out[i] = sar;
      }
      return { id, name: "Parabolic SAR", kind: "overlay", lines: [line("PSAR", PALETTE[1] ?? "#ff6d00", out, "points")] };
    }
    case "fib": {
      let low = Infinity;
      let high = -Infinity;
      for (const bar of bars) {
        low = Math.min(low, bar.low);
        high = Math.max(high, bar.high);
      }
      const span = high - low;
      const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
      const names = ["0.0%", "23.6%", "38.2%", "50.0%", "61.8%", "78.6%", "100%"];
      return {
        id,
        name: "Fibonacci Retracement",
        kind: "overlay",
        lines: levels.map((level, index) =>
          line(
            `Fib ${names[index] ?? ""}`,
            index === 0 || index === levels.length - 1 ? "#8b949e" : PALETTE[0] ?? "#2962ff",
            new Array<number>(n).fill(high - span * level),
          ),
        ),
      };
    }
    case "pivots": {
      const defs = ["P", "R1", "R2", "R3", "S1", "S2", "S3"];
      const lines = defs.map((name, index) =>
        line(name, index < 4 ? PALETTE[0] ?? "#2962ff" : PALETTE[6] ?? "#ff1744", filled(n)),
      );
      let day = "";
      let sessionHigh = -Infinity;
      let sessionLow = Infinity;
      let sessionClose = NaN;
      let prev: { high: number; low: number; close: number } | null = null;

      const applyPivots = (start: number, end: number, source: { high: number; low: number; close: number }): void => {
        const p = (source.high + source.low + source.close) / 3;
        const values = [
          p,
          2 * p - source.low,
          p + (source.high - source.low),
          source.high + 2 * (p - source.low),
          2 * p - source.high,
          p - (source.high - source.low),
          source.low - 2 * (source.high - p),
        ];
        for (let i = start; i < end; i++) {
          values.forEach((value, index) => {
            const target = lines[index]?.values;
            if (target) target[i] = value;
          });
        }
      };

      for (let i = 0; i < n; i++) {
        const bar = bars[i];
        if (!bar) continue;
        const stamp = new Date(bar.time * 1000).toISOString().slice(0, 10);
        if (stamp !== day) {
          if (prev) applyPivots(Math.max(i - 1, 0), i, prev);
          day = stamp;
          sessionHigh = bar.high;
          sessionLow = bar.low;
          sessionClose = bar.close;
        } else {
          sessionHigh = Math.max(sessionHigh, bar.high);
          sessionLow = Math.min(sessionLow, bar.low);
          sessionClose = bar.close;
        }
        prev = { high: sessionHigh, low: sessionLow, close: sessionClose };
      }
      if (prev) applyPivots(Math.max(n - 1, 0), n, prev);
      return { id, name: "Pivot Points (Classic)", kind: "overlay", lines };
    }
    case "zigzag": {
      const out = filled(n);
      if (n === 0) return { id, name: "ZigZag", kind: "overlay", lines: [line("ZigZag", PALETTE[1] ?? "#ff6d00", out)] };
      const threshold = 0.05;
      let dir = 1;
      let extIdx = 0;
      let ext = bars[0]?.low ?? 0;
      out[0] = bars[0]?.low ?? NaN;
      for (let i = 1; i < n; i++) {
        const bar = bars[i];
        if (!bar) continue;
        if (dir > 0) {
          if (bar.high > ext) {
            ext = bar.high;
            extIdx = i;
          } else if (ext > 0 && (ext - bar.low) / ext >= threshold) {
            out[extIdx] = ext;
            dir = -1;
            ext = bar.low;
            extIdx = i;
          }
        } else {
          if (bar.low < ext) {
            ext = bar.low;
            extIdx = i;
          } else if (ext > 0 && (bar.high - ext) / ext >= threshold) {
            out[extIdx] = ext;
            dir = 1;
            ext = bar.high;
            extIdx = i;
          }
        }
      }
      out[extIdx] = ext;
      return { id, name: "ZigZag", kind: "overlay", lines: [line("ZigZag 5%", PALETTE[1] ?? "#ff6d00", out)] };
    }
    default:
      return null;
  }
}

function computeStatistical(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const closes = closesOf(bars);

  switch (id) {
    case "atr":
      return {
        id,
        name: "ATR 14",
        kind: "pane",
        lines: [line("ATR 14", PALETTE[1] ?? "#ff6d00", rma(trueRangeOf(bars), 14))],
      };
    case "stddev":
      return {
        id,
        name: "Std Dev 20",
        kind: "pane",
        lines: [line("StdDev 20", PALETTE[3] ?? "#00bcd4", stdev(closes, 20))],
      };
    case "hv": {
      const rets = filled(bars.length);
      for (let i = 1; i < bars.length; i++) {
        const cur = closes[i] ?? NaN;
        const prev = closes[i - 1] ?? NaN;
        if (cur > 0 && prev > 0) rets[i] = Math.log(cur / prev);
      }
      const hv = stdev(rets, 20).map((v) => (Number.isFinite(v) ? v * Math.sqrt(252) * 100 : NaN));
      return { id, name: "Historical Volatility", kind: "pane", lines: [line("HV 20 %", PALETTE[5] ?? "#ffd600", hv)] };
    }
    case "zscore": {
      const basis = sma(closes, 20);
      const sd = stdev(closes, 20);
      const z = filled(bars.length);
      for (let i = 0; i < bars.length; i++) {
        const b = basis[i] ?? NaN;
        const s = sd[i] ?? NaN;
        if (Number.isFinite(b) && Number.isFinite(s) && s !== 0) z[i] = ((closes[i] ?? NaN) - b) / s;
      }
      return {
        id,
        name: "Z-Score",
        kind: "pane",
        guides: [
          { value: 2, label: "+2σ" },
          { value: 0, label: "0" },
          { value: -2, label: "−2σ" },
        ],
        lines: [line("Z-Score 20", PALETTE[7] ?? "#651fff", z)],
      };
    }
    default:
      return null;
  }
}

function computeSupportResistance(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const closes = closesOf(bars);
  const highs = highsOf(bars);
  const lows = lowsOf(bars);
  const n = bars.length;

  switch (id) {
    case "donchian":
      return {
        id,
        name: "Donchian Channel",
        kind: "overlay",
        lines: [
          line("Upper 20", PALETTE[3] ?? "#00bcd4", rollingExtreme(highs, 20, "max")),
          line("Lower 20", PALETTE[3] ?? "#00bcd4", rollingExtreme(lows, 20, "min")),
        ],
      };
    case "pchannel": {
      const upper = filled(n);
      const lower = filled(n);
      for (let i = 20; i < n; i++) {
        let h = -Infinity;
        let l = Infinity;
        for (let j = 1; j <= 20; j++) {
          h = Math.max(h, highs[i - j] ?? -Infinity);
          l = Math.min(l, lows[i - j] ?? Infinity);
        }
        upper[i] = h;
        lower[i] = l;
      }
      return {
        id,
        name: "Price Channel",
        kind: "overlay",
        lines: [
          line("Resistance", PALETTE[6] ?? "#ff1744", upper),
          line("Support", PALETTE[4] ?? "#00e676", lower),
        ],
      };
    }
    case "sr": {
      const hh = rollingExtreme(highs, 20, "max");
      const ll = rollingExtreme(lows, 20, "min");
      const mid = filled(n);
      const upper = filled(n);
      const lower = filled(n);
      for (let i = 0; i < n; i++) {
        const h = hh[i] ?? NaN;
        const l = ll[i] ?? NaN;
        if (!Number.isFinite(h) || !Number.isFinite(l)) continue;
        const m = (h + l) / 2;
        mid[i] = m;
        upper[i] = 2 * m - l;
        lower[i] = 2 * m - h;
      }
      return {
        id,
        name: "Support & Resistance",
        kind: "overlay",
        lines: [
          line("Resistance", PALETTE[6] ?? "#ff1744", upper),
          line("Pivot", PALETTE[5] ?? "#ffd600", mid),
          line("Support", PALETTE[4] ?? "#00e676", lower),
        ],
      };
    }
    case "linregch": {
      const period = Math.min(100, n);
      const mid = filled(n);
      const upper = filled(n);
      const lower = filled(n);
      for (let i = period - 1; i < n; i++) {
        let sumX = 0;
        let sumY = 0;
        let sumXY = 0;
        let sumX2 = 0;
        let ok = true;
        for (let j = 0; j < period; j++) {
          const y = closes[i - j] ?? NaN;
          if (!Number.isFinite(y)) {
            ok = false;
            break;
          }
          const x = j;
          sumX += x;
          sumY += y;
          sumXY += x * y;
          sumX2 += x * x;
        }
        if (!ok || period === 0) continue;
        const denom = period * sumX2 - sumX * sumX;
        if (denom === 0) continue;
        const slope = (period * sumXY - sumX * sumY) / denom;
        const intercept = (sumY - slope * sumX) / period;
        let residSq = 0;
        for (let j = 0; j < period; j++) {
          const y = closes[i - j] ?? NaN;
          const fit = intercept + slope * j;
          residSq += (y - fit) * (y - fit);
        }
        const sigma = Math.sqrt(residSq / period);
        const atZero = intercept; // value at the current bar (x = 0)
        mid[i] = atZero;
        upper[i] = atZero + 2 * sigma;
        lower[i] = atZero - 2 * sigma;
      }
      return {
        id,
        name: "Linear Regression Channel",
        kind: "overlay",
        lines: [
          line("LinReg Upper", PALETTE[3] ?? "#00bcd4", upper),
          line("LinReg Basis", PALETTE[0] ?? "#2962ff", mid),
          line("LinReg Lower", PALETTE[3] ?? "#00bcd4", lower),
        ],
      };
    }
    default:
      return null;
  }
}

function computeTrend(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const highs = highsOf(bars);
  const lows = lowsOf(bars);
  const n = bars.length;

  switch (id) {
    case "adx": {
      const plusDM = filled(n);
      const minusDM = filled(n);
      for (let i = 1; i < n; i++) {
        const bar = bars[i];
        const prev = bars[i - 1];
        if (!bar || !prev) continue;
        const upMove = bar.high - prev.high;
        const downMove = prev.low - bar.low;
        plusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0;
        minusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0;
      }
      const trr = rma(trueRangeOf(bars), 14);
      const pdm = rma(plusDM, 14);
      const mdm = rma(minusDM, 14);
      const plusDI = filled(n);
      const minusDI = filled(n);
      const dx = filled(n);
      for (let i = 0; i < n; i++) {
        const t = trr[i] ?? NaN;
        const p = pdm[i] ?? NaN;
        const m = mdm[i] ?? NaN;
        if (!Number.isFinite(t) || t === 0 || !Number.isFinite(p) || !Number.isFinite(m)) continue;
        plusDI[i] = (100 * p) / t;
        minusDI[i] = (100 * m) / t;
        const sum = (plusDI[i] ?? 0) + (minusDI[i] ?? 0);
        dx[i] = sum !== 0 ? (100 * Math.abs((plusDI[i] ?? 0) - (minusDI[i] ?? 0))) / sum : NaN;
      }
      return {
        id,
        name: "ADX/DMS",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [{ value: 20, label: "20" }],
        lines: [
          line("ADX 14", PALETTE[0] ?? "#2962ff", rma(dx, 14)),
          line("+DI", PALETTE[4] ?? "#00e676", plusDI),
          line("−DI", PALETTE[6] ?? "#ff1744", minusDI),
        ],
      };
    }
    case "aroon": {
      const period = 25;
      const up = filled(n);
      const down = filled(n);
      for (let i = period; i < n; i++) {
        let hiIdx = i;
        let loIdx = i;
        let hi = -Infinity;
        let lo = Infinity;
        for (let j = 0; j <= period; j++) {
          const h = highs[i - j] ?? -Infinity;
          const l = lows[i - j] ?? Infinity;
          if (h >= hi) {
            hi = h;
            hiIdx = i - j;
          }
          if (l <= lo) {
            lo = l;
            loIdx = i - j;
          }
        }
        up[i] = (100 * (period - (i - hiIdx))) / period;
        down[i] = (100 * (period - (i - loIdx))) / period;
      }
      return {
        id,
        name: "Aroon",
        kind: "pane",
        min: 0,
        max: 100,
        guides: [{ value: 50, label: "50" }],
        lines: [
          line("Aroon Up", PALETTE[4] ?? "#00e676", up),
          line("Aroon Down", PALETTE[6] ?? "#ff1744", down),
        ],
      };
    }
    case "aroonosc": {
      const period = 25;
      const up = filled(n);
      const down = filled(n);
      for (let i = period; i < n; i++) {
        let hiIdx = i;
        let loIdx = i;
        let hi = -Infinity;
        let lo = Infinity;
        for (let j = 0; j <= period; j++) {
          const h = highs[i - j] ?? -Infinity;
          const l = lows[i - j] ?? Infinity;
          if (h >= hi) {
            hi = h;
            hiIdx = i - j;
          }
          if (l <= lo) {
            lo = l;
            loIdx = i - j;
          }
        }
        up[i] = (100 * (period - (i - hiIdx))) / period;
        down[i] = (100 * (period - (i - loIdx))) / period;
      }
      const osc = filled(n);
      for (let i = 0; i < n; i++) {
        const u = up[i] ?? NaN;
        const d = down[i] ?? NaN;
        if (Number.isFinite(u) && Number.isFinite(d)) osc[i] = u - d;
      }
      return {
        id,
        name: "Aroon Oscillator",
        kind: "pane",
        min: -100,
        max: 100,
        guides: [{ value: 0, label: "0" }],
        lines: [line("Aroon Osc", PALETTE[0] ?? "#2962ff", osc, "histogram", 0)],
      };
    }
    case "alligator": {
      const median = medianOf(bars);
      const jaw = shiftsForward(rma(median, 34), 13);
      const teeth = shiftsForward(rma(median, 13), 8);
      const lips = shiftsForward(rma(median, 8), 5);
      return {
        id,
        name: "Alligator",
        kind: "overlay",
        lines: [
          line("Jaw (13)", PALETTE[0] ?? "#2962ff", jaw),
          line("Teeth (8)", PALETTE[6] ?? "#ff1744", teeth),
          line("Lips (5)", PALETTE[4] ?? "#00e676", lips),
        ],
      };
    }
    case "ichimoku": {
      const tenkan = filled(n);
      const kijun = filled(n);
      const spanB = filled(n);
      const tenkanHigh = rollingExtreme(highs, 9, "max");
      const tenkanLow = rollingExtreme(lows, 9, "min");
      const kijunHigh = rollingExtreme(highs, 26, "max");
      const kijunLow = rollingExtreme(lows, 26, "min");
      const spanBHigh = rollingExtreme(highs, 52, "max");
      const spanBLow = rollingExtreme(lows, 52, "min");
      for (let i = 0; i < n; i++) {
        const th = tenkanHigh[i] ?? NaN;
        const tl = tenkanLow[i] ?? NaN;
        if (Number.isFinite(th) && Number.isFinite(tl)) tenkan[i] = (th + tl) / 2;
        const kh = kijunHigh[i] ?? NaN;
        const kl = kijunLow[i] ?? NaN;
        if (Number.isFinite(kh) && Number.isFinite(kl)) kijun[i] = (kh + kl) / 2;
        const bh = spanBHigh[i] ?? NaN;
        const bl = spanBLow[i] ?? NaN;
        if (Number.isFinite(bh) && Number.isFinite(bl)) spanB[i] = (bh + bl) / 2;
      }
      const spanA = filled(n);
      for (let i = 0; i < n; i++) {
        const t = tenkan[i] ?? NaN;
        const k = kijun[i] ?? NaN;
        if (Number.isFinite(t) && Number.isFinite(k)) spanA[i] = (t + k) / 2;
      }
      return {
        id,
        name: "Ichimoku Cloud",
        kind: "overlay",
        lines: [
          line("Senkou A", PALETTE[4] ?? "#00e676", shiftsForward(spanA, 26)),
          line("Senkou B", PALETTE[6] ?? "#ff1744", shiftsForward(spanB, 26)),
          line("Tenkan 9", PALETTE[0] ?? "#2962ff", tenkan),
          line("Kijun 26", PALETTE[1] ?? "#ff6d00", kijun),
        ],
      };
    }
    case "supertrend": {
      const period = 10;
      const mult = 3;
      const atrArr = rma(trueRangeOf(bars), period);
      const out = filled(n);
      let finalUpper = NaN;
      let finalLower = NaN;
      let trend = 1;
      for (let i = 0; i < n; i++) {
        const bar = bars[i];
        const prev = i > 0 ? bars[i - 1] : undefined;
        const a = atrArr[i] ?? NaN;
        if (!bar || !Number.isFinite(a)) continue;
        const midPrice = (bar.high + bar.low) / 2;
        const basicUpper = midPrice + mult * a;
        const basicLower = midPrice - mult * a;
        if (!Number.isFinite(finalUpper) || !Number.isFinite(finalLower) || !prev) {
          finalUpper = basicUpper;
          finalLower = basicLower;
        } else {
          finalUpper =
            basicUpper < finalUpper || prev.close > finalUpper ? basicUpper : finalUpper;
          finalLower =
            basicLower > finalLower || prev.close < finalLower ? basicLower : finalLower;
        }
        if (trend === 1) {
          if (bar.close < finalLower) {
            trend = -1;
            out[i] = finalUpper;
          } else {
            out[i] = finalLower;
          }
        } else {
          if (bar.close > finalUpper) {
            trend = 1;
            out[i] = finalLower;
          } else {
            out[i] = finalUpper;
          }
        }
      }
      return { id, name: "SuperTrend", kind: "overlay", lines: [line("SuperTrend 10×3", PALETTE[1] ?? "#ff6d00", out)] };
    }
    case "vortex": {
      const vmPlus = filled(n);
      const vmMinus = filled(n);
      for (let i = 1; i < n; i++) {
        const bar = bars[i];
        const prev = bars[i - 1];
        if (!bar || !prev) continue;
        vmPlus[i] = Math.abs(bar.high - prev.low);
        vmMinus[i] = Math.abs(bar.low - prev.high);
      }
      const trr = trueRangeOf(bars);
      trr[0] = NaN;
      const sumPlus = sma(vmPlus, 16);
      const sumMinus = sma(vmMinus, 16);
      const sumTr = sma(trr, 16);
      const viPlus = filled(n);
      const viMinus = filled(n);
      for (let i = 0; i < n; i++) {
        const t = sumTr[i] ?? NaN;
        const p = sumPlus[i] ?? NaN;
        const m = sumMinus[i] ?? NaN;
        if (!Number.isFinite(t) || t === 0 || !Number.isFinite(p) || !Number.isFinite(m)) continue;
        viPlus[i] = p / t;
        viMinus[i] = m / t;
      }
      return {
        id,
        name: "Vortex Indicator",
        kind: "pane",
        guides: [{ value: 1, label: "1" }],
        lines: [
          line("VI+", PALETTE[4] ?? "#00e676", viPlus),
          line("VI−", PALETTE[6] ?? "#ff1744", viMinus),
        ],
      };
    }
    default:
      return null;
  }
}

const COMPUTE_BY_CATEGORY: Record<IndicatorCategory, (id: string, bars: HistoryCandle[]) => ComputedIndicator | null> = {
  "Averages/Bands": computeBands,
  "Momentum/Oscillator": computeMomentum,
  "Money Flow": computeMoneyFlow,
  Projection: computeProjection,
  Statistical: computeStatistical,
  "Support/Resistance": computeSupportResistance,
  "Trend Analysis": computeTrend,
};

/** Compute one indicator for the given bars; null when unknown. */
export function computeIndicator(id: string, bars: HistoryCandle[]): ComputedIndicator | null {
  const def = INDICATOR_MAP.get(id);
  if (!def || bars.length === 0) return null;
  return COMPUTE_BY_CATEGORY[def.category](id, bars);
}

/** Compute every requested indicator (unknown ids are skipped). */
export function computeIndicators(
  ids: readonly string[],
  bars: HistoryCandle[],
): ComputedIndicator[] {
  const out: ComputedIndicator[] = [];
  for (const id of ids) {
    const computed = computeIndicator(id, bars);
    if (computed) out.push(computed);
  }
  return out;
}
