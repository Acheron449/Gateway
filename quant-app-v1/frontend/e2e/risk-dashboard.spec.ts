import { expect, test } from "@playwright/test";

const token = "risk-dashboard-test-token";
const user = { id: "risk-dashboard-user", email: "risk@example.test" };

const times = [
  "2026-11-01T14:00:00+00:00",
  "2026-11-02T14:00:00+00:00",
  "2026-11-03T14:00:00+00:00",
  "2026-11-04T14:00:00+00:00",
  "2026-11-05T14:00:00+00:00",
];

const riskPayload = {
  portfolio_id: "paper_risk-dashboard-user",
  generated_at: "2026-11-05T20:00:00+00:00",
  equity: 99_900,
  cash: 98_100,
  buying_power: 98_100,
  daily_pnl: -100,
  daily_pnl_pct: -0.1,
  total_return_pct: -0.1,
  max_drawdown: 0.1,
  current_drawdown: 0.1,
  open_positions: 1,
  gross_exposure: 0.018,
  net_exposure: 0.018,
  var_95: 0.42,
  var_99: 0.67,
  var_95_amount: 419.58,
  var_99_amount: 669.33,
  concentration_risk: [{ symbol: "AAPL", pct: 1.8 }],
  equity_curve: [
    { time: times[0]!, equity: 100_000, cash: 100_000 },
    { time: times[1]!, equity: 100_000, cash: 99_000 },
    { time: times[2]!, equity: 100_000, cash: 99_000 },
    { time: times[3]!, equity: 100_000, cash: 98_100 },
    { time: times[4]!, equity: 99_900, cash: 98_100 },
  ],
  drawdown_curve: [
    { time: times[0]!, drawdown: 0 },
    { time: times[1]!, drawdown: 0 },
    { time: times[2]!, drawdown: 0 },
    { time: times[3]!, drawdown: 0 },
    { time: times[4]!, drawdown: -0.1 },
  ],
  positions: [
    {
      instrument_id: "AAPL",
      quantity: 20,
      avg_cost: 95,
      market_value: 1_800,
      unrealized_pnl: 0,
      realized_pnl: 0,
      pct_of_equity: 1.8,
    },
  ],
  series_note: "Replayed from this paper portfolio's recorded cash flows and fills.",
};

test("risk view is reachable from navigation and draws the backend series", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const riskRequests: { path: string; authorization: string | undefined }[] = [];
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/portfolio/risk") {
      riskRequests.push({ path: pathname, authorization: request.headers()["authorization"] });
      return route.fulfill({ json: riskPayload });
    }
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/filings") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");

  await page.getByRole("link", { name: "Risk", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/risk$/);
  await expect(page.getByRole("heading", { name: "Risk", level: 1 })).toBeVisible();

  const equity = page.locator(".risk-equity-chart");
  const drawdown = page.locator(".risk-drawdown-chart");
  await expect(equity).toBeVisible();
  await expect(drawdown).toBeVisible();
  await expect(equity).toHaveAttribute("data-equity-points", "5");
  await expect(drawdown).toHaveAttribute("data-drawdown-points", "5");

  // The placeholder panels are gone; the charts carry real series.
  await expect(page.getByText(/would go here/i)).toHaveCount(0);
  await expect(page.getByText("Replayed from this paper portfolio's recorded cash flows and fills.")).toBeVisible();

  expect(riskRequests.length).toBeGreaterThan(0);
  expect(riskRequests.every((entry) => entry.authorization === `Bearer ${token}`)).toBe(true);
  expect(riskRequests.every((entry) => entry.path === "/portfolio/risk")).toBe(true);
});

test("signed-out visitors get a sign-in prompt instead of fabricated risk", async ({ page }) => {
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/risk");

  await expect(page.getByRole("heading", { name: "Sign in to see your risk" })).toBeVisible();
  await expect(page.locator(".risk-equity-chart")).toHaveCount(0);
});
