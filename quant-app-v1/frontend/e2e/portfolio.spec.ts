import { expect, test } from "@playwright/test";

const token = "portfolio-test-token";
const user = { id: "portfolio-user", email: "portfolio@example.test" };

const portfolioPayload = {
  portfolio_id: "paper_portfolio-user",
  cash: 100000,
  equity: 100000,
  buying_power: 100000,
  positions: [],
  open_orders: [],
  recent_fills: [],
};

test("paper trading is reachable from navigation and submits an authenticated owner-scoped order", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const portfolioCalls: (string | undefined)[] = [];
  const orderBodies: Record<string, unknown>[] = [];
  let brokerRequests = 0;

  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");

    if (pathname.startsWith("/live/")) brokerRequests += 1;
    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/portfolio" && request.method() === "GET") {
      portfolioCalls.push(request.headers()["authorization"]);
      return route.fulfill({ json: portfolioPayload });
    }
    if (pathname === "/portfolio/orders" && request.method() === "POST") {
      orderBodies.push((request.postDataJSON() ?? {}) as Record<string, unknown>);
      portfolioCalls.push(request.headers()["authorization"]);
      return route.fulfill({
        json: {
          order_id: "simulated-order-1",
          status: "accepted",
          message: "Simulated order accepted and acknowledged",
        },
      });
    }
    if (pathname.endsWith("/simulate-fill")) {
      return route.fulfill({ json: { filled: false } });
    }
    if (pathname === "/portfolio/market-status") {
      return route.fulfill({ json: { session: "regular", is_open: false } });
    }
    if (pathname === "/quotes") {
      return route.fulfill({
        json: { quotes: [{ symbol: "AAPL", price: 190, change: 1, change_pct: 0.53 }] },
      });
    }
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/calendar") return route.fulfill({ json: { events: [] } });
    if (pathname.startsWith("/analysis/")) {
      return route.fulfill({
        json: { ticker: "AAPL", direction: "bullish", overall_confidence: 0.6, rsi: 55, price: 190 },
      });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");
  await page.getByRole("link", { name: "Paper Trading", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/paper-trading$/);
  await expect(page.getByText("Simulated paper", { exact: true })).toBeVisible();
  await expect(page.locator(".paper-trading")).toHaveAttribute(
    "data-portfolio-id",
    "paper_portfolio-user",
  );

  expect(portfolioCalls.length).toBeGreaterThan(0);
  expect(portfolioCalls.every((authorization) => authorization === `Bearer ${token}`)).toBe(true);

  await page.getByRole("tab", { name: "Trade" }).click();
  await page.locator("button.paper-submit").click();

  await expect.poll(() => orderBodies.length).toBe(1);
  expect(orderBodies[0]).toMatchObject({
    instrument: "AAPL",
    side: "buy",
    order_type: "market",
    quantity: 10,
  });
  await expect(page.getByText(/Simulated order accepted/)).toBeVisible();

  // The dead broker path and the fabricated live stream are gone.
  expect(brokerRequests).toBe(0);
  await expect(page.getByText(/Stream connected/)).toHaveCount(0);
  await expect(page.getByText("Polling every 5s")).toBeVisible();
});

test("signed-out visitors get a sign-in prompt instead of a portfolio", async ({ page }) => {
  let portfolioRequests = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname.startsWith("/portfolio")) portfolioRequests += 1;
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/paper-trading");

  await expect(page.getByRole("heading", { name: "Sign in to paper trade" })).toBeVisible();
  await expect(page.locator(".paper-trading")).toHaveCount(0);
  expect(portfolioRequests).toBe(0);
});
