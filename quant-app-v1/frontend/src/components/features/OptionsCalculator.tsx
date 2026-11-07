import { useCallback, useEffect, useState } from "react";

import { useAuth } from "../../context/AuthContext";
import { API_BASE } from "../../lib/constants";

/* §5.2 Black-Scholes calculator (FR-O1..O6): value, greeks and implied
   volatility for user-supplied inputs. No chain, no feed — a calculator. */

interface PriceResponse {
  engine_version: string;
  type: "call" | "put";
  price: number;
  intrinsic: number;
  time_value: number;
  greeks: { delta: number; gamma: number; vega: number; theta: number; rho: number };
  greek_units: Record<string, string>;
  bounds: { lower: number; upper: number };
  near_expiry_unstable: boolean;
  warnings: string[];
  model_boundaries: string[];
}

interface IvResponse {
  implied_volatility: number;
  converged: boolean;
  iterations: number;
  solver: string;
  market_price: number;
  model_price: number;
  price_error: number;
  bounds: { lower: number; upper: number };
  warnings: string[];
}

interface ApiErrorDetail {
  code?: string;
  field?: string;
  bound?: number;
  message?: string;
}

const num = (value: number | null | undefined, digits = 4) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

const vol = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(2)}%`;

const asNumber = (raw: string, label: string): number => {
  const parsed = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(parsed)) throw new Error(`${label} must be a number.`);
  return parsed;
};

export function OptionsCalculator() {
  const { token } = useAuth();
  const [form, setForm] = useState({
    S: "100",
    K: "100",
    T: "0.25",
    r: "0.05",
    q: "0",
    sigma: "0.2",
    type: "call" as "call" | "put",
    market: "5.20",
  });
  const [priced, setPriced] = useState<PriceResponse | null>(null);
  const [implied, setImplied] = useState<IvResponse | null>(null);
  const [ivError, setIvError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setIvError(null);
    try {
      const S = asNumber(form.S, "Spot");
      const K = asNumber(form.K, "Strike");
      const T = asNumber(form.T, "Time to expiry");
      const r = asNumber(form.r, "Rate");
      const q = asNumber(form.q, "Dividend yield");
      const sigma = asNumber(form.sigma, "Volatility");
      const market = asNumber(form.market, "Market price");

      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;

      const priceResponse = await fetch(`${API_BASE}/quant/options/price`, {
        method: "POST",
        headers,
        body: JSON.stringify({ S, K, T, r, q, sigma, type: form.type }),
      });
      const priceBody = (await priceResponse.json()) as PriceResponse & { detail?: ApiErrorDetail };
      if (!priceResponse.ok) {
        const detail = priceBody.detail;
        throw new Error(detail?.message ?? `Pricing failed (${priceResponse.status})`);
      }
      setPriced(priceBody);
      setImplied(null);

      const ivResponse = await fetch(`${API_BASE}/quant/options/implied-vol`, {
        method: "POST",
        headers,
        body: JSON.stringify({ market_price: market, S, K, T, r, q, type: form.type }),
      });
      const ivBody = (await ivResponse.json()) as IvResponse & { detail?: ApiErrorDetail };
      if (!ivResponse.ok) {
        const detail = ivBody.detail;
        // §5.2: a price outside the band names the violated bound.
        setIvError(
          detail?.bound !== undefined
            ? `${detail.message ?? "Price is outside the no-arbitrage band"} (bound ${num(detail.bound, 4)})`
            : (detail?.message ?? `Implied volatility failed (${ivResponse.status})`),
        );
        return;
      }
      setImplied(ivBody);
    } catch (err) {
      setPriced(null);
      setImplied(null);
      setError(err instanceof Error ? err.message : "Pricing failed");
    } finally {
      setLoading(false);
    }
  }, [form, token]);

  useEffect(() => {
    void run();
    // Price once on mount; afterwards the button (or Enter) re-runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (key: keyof typeof form, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const marketValue = Number(form.market);
  const currencyDiff =
    priced && Number.isFinite(marketValue) ? priced.price - marketValue : null;
  const ivDiff = implied && priced ? implied.implied_volatility - Number(form.sigma) : null;

  return (
    <div className="report-section mc-panel">
      <p className="mc-disclaimer">
        <strong>European Black-Scholes-Merton.</strong> Fair value, greeks and implied volatility
        from inputs you supply — there is no options chain or market-options feed behind this
        calculator, and no American early-exercise premium is modelled.
      </p>

      <div className="mc-controls">
        <label>
          Spot S
          <input value={form.S} onChange={(event) => update("S", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Strike K
          <input value={form.K} onChange={(event) => update("K", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Expiry T (years)
          <input value={form.T} onChange={(event) => update("T", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Rate r
          <input value={form.r} onChange={(event) => update("r", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Dividend yield q
          <input value={form.q} onChange={(event) => update("q", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Volatility σ
          <input value={form.sigma} onChange={(event) => update("sigma", event.target.value)} inputMode="decimal" />
        </label>
        <label>
          Type
          <select value={form.type} onChange={(event) => update("type", event.target.value)}>
            <option value="call">Call</option>
            <option value="put">Put</option>
          </select>
        </label>
        <label>
          Market price
          <input value={form.market} onChange={(event) => update("market", event.target.value)} inputMode="decimal" />
        </label>
        <button type="button" className="btn-secondary" onClick={() => void run()} disabled={loading}>
          {loading ? "Pricing…" : "Price"}
        </button>
      </div>

      {error && <p className="report-error-text">{error}</p>}

      {priced && (
        <>
          <div className="opt-summary">
            <div>
              <span className="opt-label">Fair value</span>
              <strong>{num(priced.price, 4)}</strong>
              <small>
                intrinsic {num(priced.intrinsic, 4)} · time value {num(priced.time_value, 4)}
              </small>
            </div>
            <div>
              <span className="opt-label">Market price</span>
              <strong>{num(marketValue, 4)}</strong>
              <small>{priced.type === "call" ? "call" : "put"} · model {priced.engine_version}</small>
            </div>
            <div>
              <span className="opt-label">Difference (fair − market)</span>
              <strong className={currencyDiff === null ? undefined : currencyDiff >= 0 ? "up" : "down"}>
                {currencyDiff === null ? "—" : `${currencyDiff >= 0 ? "+" : ""}${num(currencyDiff, 4)}`}
              </strong>
              <small>currency units per contract</small>
            </div>
            <div>
              <span className="opt-label">Implied volatility of market price</span>
              <strong>{vol(implied?.implied_volatility)}</strong>
              <small>
                {ivError
                  ? ivError
                  : implied
                    ? `${implied.converged ? "converged" : "did not converge"} · ${implied.solver} · ${implied.iterations} iterations`
                    : "—"}
              </small>
            </div>
            <div>
              <span className="opt-label">IV difference (implied − σ)</span>
              <strong className={ivDiff === null ? undefined : ivDiff >= 0 ? "up" : "down"}>
                {ivDiff === null ? "—" : `${ivDiff >= 0 ? "+" : ""}${(ivDiff * 100).toFixed(2)} vol pts`}
              </strong>
              <small>positive means the market price implies more volatility than entered</small>
            </div>
          </div>

          <table className="report-table">
            <caption>
              Greeks · theta per calendar day, vega and rho per 1% ({priced.type})
            </caption>
            <thead>
              <tr>
                <th scope="col">Greek</th>
                <th scope="col">Value</th>
                <th scope="col">Unit</th>
              </tr>
            </thead>
            <tbody>
              {(["delta", "gamma", "vega", "theta", "rho"] as const).map((greek) => (
                <tr key={greek}>
                  <th scope="row">{greek.charAt(0).toUpperCase() + greek.slice(1)}</th>
                  <td>{num(priced.greeks[greek], 6)}</td>
                  <td>{priced.greek_units[greek]}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {priced.near_expiry_unstable && (
            <p className="mc-disclaimer">
              <strong>Less than one day to expiry.</strong> Greeks are numerically unstable here;
              treat them as indicative only.
            </p>
          )}

          <details className="report-spec">
            <summary>Model boundaries</summary>
            <ul>
              {priced.model_boundaries.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="report-note">
              No-arbitrage band for this contract: {num(priced.bounds.lower, 4)} to{" "}
              {num(priced.bounds.upper, 4)}. Prices outside it have no implied volatility.
            </p>
          </details>
        </>
      )}
    </div>
  );
}
