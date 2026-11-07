import { expect, test } from "@playwright/test";

const token = "monte-carlo-test-token";
const user = { id: "monte-carlo-user", email: "fan@example.test" };

// 40 daily bars closing 100.00 → 139.00, so the surface must derive 39 simple
// returns from these closes and start the paths at 139.
const bars = Array.from({ length: 40 }, (_, index) => {
  const close = 100 + index;
  return {
    time: 1_786_000_000 + index * 86_400,
    open: close - 1,
    high: close + 1,
    low: close - 1,
    close,
    volume: 1_000_000 + index,
  };
});

const lastBar = bars[bars.length - 1]!;

const simulation = {
  source: "returns",
  seed: 42,
  paths: 2_000,
  horizon: 39,
  method: "bootstrap",
  block_length: 20,
  start_equity: 139,
  data_hash: "mc-data-hash",
  output_hash: "mc-output-hash",
  engine_version: "mc-1.0.0",
  observations: 39,
  fan: [
    { step: 0, p5: 139, p25: 139, p50: 139, p75: 139, p95: 139 },
    { step: 19, p5: 132.4, p25: 136.1, p50: 141.2, p75: 146.3, p95: 150.8 },
    { step: 39, p5: 126.2, p25: 134.4, p50: 142.1, p75: 151.6, p95: 158.3 },
  ],
  terminal_distribution: { bins: [126.2, 142.1, 158.3], counts: [120, 1600, 280] },
  terminal_summary: { mean: 142.6, sd: 9.2 },
  var_cvar: { var_95: 12.4, cvar_95: 15.1, var_99: 18.2, cvar_99: 21.3 },
  drawdown_distribution: {
    p50_pct: 4.1,
    p95_pct: 11.2,
    p99_pct: 15.9,
    worst_pct: 22.4,
    histogram: { bins: [0, 5, 10, 15, 22.4], counts: [900, 700, 260, 100, 40] },
  },
  ruin: {
    threshold: 69.5,
    fraction_of_start: 0.5,
    probability: 0.012,
    ruined_paths: 24,
    median_time_to_ruin: 31,
  },
  sizing: {
    risk_budget: 500,
    position_multiplier: 1.25,
    cvar_99: 21.3,
    expected_tail_loss_at_multiplier: 26.6,
    note: "Sized so the 99% tail stays inside the budget.",
  },
  disclaimer: "A simulation of historical returns.",
};

test("monte carlo is reachable from navigation and simulates the symbol's own daily returns", async ({
  page,
}) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const calls: { authorization: string | undefined; body: Record<string, unknown> }[] = [];
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname.startsWith("/history/")) return route.fulfill({ json: bars });
    if (pathname === "/quant/monte-carlo" && request.method() === "POST") {
      calls.push({
        authorization: request.headers()["authorization"],
        body: (request.postDataJSON() ?? {}) as Record<string, unknown>,
      });
      return route.fulfill({ json: simulation });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");

  await page.getByRole("link", { name: "Monte Carlo", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/monte-carlo$/);
  await expect(page.getByRole("heading", { name: "Monte Carlo", level: 1 })).toBeVisible();

  const panel = page.locator(".mc-panel");
  await expect(panel).toBeVisible();
  await expect(page.locator(".mc-source")).toContainText("Resampling 39 daily returns of AAPL");
  await expect(page.locator(".mc-source")).toContainText("last close 139.00");

  await expect(panel).toHaveAttribute("data-source", "returns");
  await expect(panel).toHaveAttribute("data-engine", "mc-1.0.0");
  await expect(panel).toHaveAttribute("data-paths", "2000");
  await expect(panel).toHaveAttribute("data-horizon", "39");
  await expect(panel).toHaveAttribute("data-seed", "42");
  await expect(panel).toHaveAttribute("data-observations", "39");
  await expect(panel).toHaveAttribute("data-start-equity", "139");

  // Both charts and the tail-risk table come from the simulated payload.
  await expect(page.getByRole("img", { name: "Percentile fan of simulated equity" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Histogram of simulated maximum drawdowns" })).toBeVisible();
  const tail = page.locator(".mc-panel table.report-table");
  await expect(tail).toContainText("CVaR (mean loss beyond VaR)");
  await expect(tail).toContainText("18.20");
  await expect(tail).toContainText("21.30");
  await expect(tail).toContainText("24 of 2,000 paths");
  await expect(page.locator(".mc-panel")).toContainText("Simulation, not a forecast");
  await expect(page.locator(".mc-panel")).toContainText("daily returns of AAPL");

  // The request was authenticated and carried the bar-derived series and last
  // close, never a stored run id or a hand-entered price.
  expect(calls.length).toBeGreaterThan(0);
  const body = calls[0]!.body;
  expect(calls[0]!.authorization).toBe(`Bearer ${token}`);
  expect(body["run_id"]).toBeUndefined();
  expect(body["start_equity"]).toBe(139);
  expect(body["horizon"]).toBe(39);
  expect(body["paths"]).toBe(10_000);
  expect(body["seed"]).toBe(42);
  expect(body["method"]).toBe("bootstrap");
  const returns = body["returns"] as number[];
  expect(returns).toHaveLength(39);
  expect(returns[0]).toBeCloseTo(101 / 100 - 1, 10);
  expect(returns[returns.length - 1]).toBeCloseTo(139 / 138 - 1, 10);
  expect(lastBar.close).toBe(139);

  await expect(page.getByText(/would go here|placeholder fan|lorem ipsum/i)).toHaveCount(0);
});
