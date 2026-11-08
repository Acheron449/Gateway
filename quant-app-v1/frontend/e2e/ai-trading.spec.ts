import { expect, test } from "@playwright/test";

const token = "ai-trading-test-token";
const user = { id: "ai-user", email: "ai@example.test" };

const config = {
  enabled: false,
  route: "paper",
  symbols: ["SPY", "QQQ"],
  strategy: "momentum",
  max_position_notional: 1000,
  confidence_threshold: 0.65,
  use_journal_memory: true,
  use_backtest_memory: true,
  cycle_seconds: 60,
};

const seededLog = [
  {
    id: "ai-log-1",
    ts: new Date().toISOString(),
    symbol: "SPY",
    action: "buy",
    confidence: 0.8,
    reason: "momentum spread +1.20% vs 20-bar mean",
    price: 500,
    qty: null,
    route: "paper",
    ok: 1,
    detail: "opened 1 @ ~500.00",
  },
  {
    id: "ai-log-2",
    ts: new Date().toISOString(),
    symbol: "QQQ",
    action: "hold",
    confidence: 0.3,
    reason: "confidence 30% below 65% threshold",
    price: 420,
    qty: null,
    route: "paper",
    ok: 1,
    detail: "confidence 30% below 65% threshold",
  },
];

test("AI Trading is reachable from navigation and saves an authenticated owner-scoped config", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const calls: { path: string; method: string; authorization?: string }[] = [];
  const saveBodies: Record<string, unknown>[] = [];
  let cycleRuns = 0;

  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    const authorization = request.headers()["authorization"];

    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/ai-trading" && request.method() === "GET") {
      calls.push({ path: pathname, method: request.method(), authorization });
      return route.fulfill({
        json: {
          running: false,
          config,
          last_log: seededLog,
          journal_memory: {
            SPY: { closed: 3, wins: 2, win_rate: 0.667, pnl: 120 },
          },
          backtest_edge: 0.05,
        },
      });
    }
    if (pathname === "/ai-trading" && request.method() === "PUT") {
      calls.push({ path: pathname, method: request.method(), authorization });
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      saveBodies.push(body);
      return route.fulfill({ json: { config: { ...config, ...body }, running: false } });
    }
    if (pathname === "/ai-trading/log") {
      calls.push({ path: pathname, method: request.method(), authorization });
      const rows = cycleRuns
        ? [
            {
              ...seededLog[0],
              id: "ai-log-3",
              action: "buy",
              detail: "opened 2 @ ~500.00",
            },
            ...seededLog,
          ]
        : seededLog;
      return route.fulfill({ json: rows });
    }
    if (pathname === "/ai-trading/cycle" && request.method() === "POST") {
      calls.push({ path: pathname, method: request.method(), authorization });
      cycleRuns += 1;
      return route.fulfill({
        json: {
          route: "paper",
          decisions: [{ symbol: "SPY", action: "buy", confidence: 0.8, price: 500 }],
          ts: new Date().toISOString(),
        },
      });
    }
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/filings") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");
  await page.getByRole("link", { name: "AI Trading", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/ai-trading$/);
  await expect(page.locator(".ai-trading")).toHaveAttribute("data-log-count", "2");
  await expect(page.getByText("○ Stopped")).toBeVisible();
  await expect(page.getByText("+5.0%")).toBeVisible();
  await expect(page.getByText("67%", { exact: true })).toBeVisible();

  expect(calls.length).toBeGreaterThan(0);
  expect(calls.every((call) => call.authorization === `Bearer ${token}`)).toBe(true);

  await page.getByLabel("Symbols (comma separated)").fill("AAPL, MSFT");
  await page.getByRole("button", { name: "Save config" }).click();

  await expect.poll(() => saveBodies.length).toBe(1);
  expect(saveBodies[0]).toMatchObject({ symbols: ["AAPL", "MSFT"], route: "paper" });
  await expect(page.getByText("Configuration saved.")).toBeVisible();

  await page.getByRole("button", { name: "Run one cycle now" }).click();
  await expect.poll(() => cycleRuns).toBe(1);
  await expect(page.locator(".ai-trading")).toHaveAttribute("data-log-count", "3");
  await expect(page.locator('[data-log-id="ai-log-3"]')).toBeVisible();

  // Live broker routing was removed rather than left as a disabled dead control.
  await expect(page.getByText("Live broker (unavailable)")).toHaveCount(0);
  await expect(page.getByLabel("Trade route")).toHaveCount(0);
  expect(calls.filter((call) => call.path.startsWith("/live/"))).toHaveLength(0);
});

test("signed-out visitors get a sign-in prompt instead of the AI trader", async ({ page }) => {
  let aiRequests = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname.startsWith("/ai-trading")) aiRequests += 1;
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/ai-trading");

  await expect(page.getByRole("heading", { name: "Sign in to use AI Trading" })).toBeVisible();
  await expect(page.locator(".ai-trading")).toHaveCount(0);
  expect(aiRequests).toBe(0);
});
