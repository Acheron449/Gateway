import { useQuery } from "@tanstack/react-query";

import { API_BASE } from "../../lib/constants";
import { LastUpdated } from "../../lib/LastUpdated";

interface AccountSummary {
  portfolio_id?: string;
  equity?: number;
  cash?: number;
  buying_power?: number;
  positions?: unknown[];
  account_number?: string;
}

function money(value: number | undefined): string {
  return value === undefined
    ? "—"
    : value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function fetchAccountSummary(mode: "paper" | "live"): Promise<AccountSummary> {
  if (mode === "live") throw new Error("Live execution unavailable");
  if (mode === "paper") {
    const token = localStorage.getItem("gateway_auth_token");
    const response = await fetch(`${API_BASE}/portfolio`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error((await response.text()) || "Failed to fetch portfolio");
    return response.json();
  }

  const response = await fetch(`${API_BASE}/live/account`);
  if (!response.ok) {
    let message = `Live account unavailable (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") message = payload.detail;
    } catch {
      // Retain the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

export function TradingAccountStatus({ mode }: { mode: "paper" | "live" }) {
  const { data, dataUpdatedAt } = useQuery({
    queryKey: ["trading-account-summary", mode],
    queryFn: () => fetchAccountSummary(mode),
    refetchInterval: 5000,
    staleTime: 2500,
    retry: 1,
  });

  const positions = Array.isArray(data?.positions) ? data.positions.length : 0;
  const accountNumber = data?.account_number ?? data?.portfolio_id?.replace("live:", "");

  return (
    <section className={`desk-status ${mode === "live" ? "live" : ""}`} aria-label={`${mode} account summary`}>
      {mode === "live" ? <strong>Live execution unavailable</strong> : <LastUpdated at={dataUpdatedAt || undefined} />}
      <div className="desk-status-metrics" aria-live="polite">
        <span><b>Equity</b> ${money(data?.equity)}</span>
        <span><b>Cash</b> ${money(data?.cash)}</span>
        <span><b>Buying power</b> ${money(data?.buying_power)}</span>
        <span><b>Positions</b> {positions}</span>
        {mode === "live" && accountNumber ? (
          <span className="desk-account-id"><b>Account</b> {accountNumber}</span>
        ) : null}
      </div>
    </section>
  );
}
