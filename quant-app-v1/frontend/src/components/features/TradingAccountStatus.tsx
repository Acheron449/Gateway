import { useQuery } from "@tanstack/react-query";

import { API_BASE } from "../../lib/constants";
import { LastUpdated } from "../../lib/LastUpdated";
import { useAuth } from "../../context/AuthContext";

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

async function fetchAccountSummary(mode: "paper" | "live", token: string | null): Promise<AccountSummary> {
  if (mode === "live") throw new Error("Live execution unavailable");
  const response = await fetch(`${API_BASE}/portfolio`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error((await response.text()) || "Failed to fetch portfolio");
  return response.json();
}

export function TradingAccountStatus({ mode }: { mode: "paper" | "live" }) {
  const { token, isAuthenticated } = useAuth();
  const { data, dataUpdatedAt } = useQuery({
    queryKey: ["trading-account-summary", mode, token],
    queryFn: () => fetchAccountSummary(mode, token),
    refetchInterval: 5000,
    staleTime: 2500,
    retry: 1,
    enabled: mode === "live" || isAuthenticated,
  });

  const positions = Array.isArray(data?.positions) ? data.positions.length : 0;
  const accountNumber = data?.account_number ?? data?.portfolio_id?.replace("live:", "");

  if (mode === "paper" && !isAuthenticated) {
    return (
      <section className="desk-status" aria-label="paper account summary">
        <span>Sign in to see your paper account</span>
      </section>
    );
  }

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
