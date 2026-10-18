import { expect, test } from "@playwright/test";

test("paper desk discloses simulator mode and routes orders only to the simulator", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("gateway_auth_token", "paper-safety-test-token");
    localStorage.setItem("gateway_user", JSON.stringify({ id: "paper-safety-user", email: "paper@example.test" }));
  });

  const brokerRequests: string[] = [];
  const simulatedOrderRequests: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname.replace(/^\/api/, "");
    if (pathname.startsWith("/live/")) brokerRequests.push(`${request.method()} ${pathname}`);
    if (pathname === "/portfolio/orders" && request.method() === "POST") {
      simulatedOrderRequests.push(`${request.method()} ${pathname}`);
      await route.fulfill({ json: { order_id: "simulated-order-1", status: "accepted", message: "Simulated paper order accepted" } });
    } else if (pathname.endsWith("/simulate-fill") && request.method() === "POST") {
      await route.fulfill({ json: { filled: false } });
    } else if (pathname.endsWith("/auth/me")) {
      await route.fulfill({ json: { id: "paper-safety-user", email: "paper@example.test" } });
    } else if (pathname.endsWith("/portfolio")) {
      await route.fulfill({ json: { id: "sim-portfolio", equity: 100000, cash: 100000, buying_power: 100000, positions: [], open_orders: [], recent_fills: [] } });
    } else if (pathname.endsWith("/quotes")) {
      await route.fulfill({ json: { quotes: [{ symbol: "AAPL", price: 190, change: 0, change_pct: 0 }] } });
    } else if (pathname.endsWith("/history/AAPL")) {
      await route.fulfill({ json: [] });
    } else if (pathname.endsWith("/market-status")) {
      await route.fulfill({ json: { is_open: false, market_open: false } });
    } else {
      await route.fulfill({ json: {} });
    }
  });

  await page.goto("/app/paper-trading");
  await expect(page.getByText("Simulated paper", { exact: true })).toBeVisible();
  await expect(page.getByText(/Market (state|status): Closed/i)).toBeVisible();
  await expect(page.getByText(/Live execution unavailable/i)).toBeVisible();
  await page.getByRole("tab", { name: "Trade" }).click();
  const submit = page.locator("button.paper-submit");
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect.poll(() => simulatedOrderRequests).toEqual(["POST /portfolio/orders"]);
  expect(brokerRequests).toEqual([]);
});

test("live execution view is an explicit unavailable state", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("gateway_auth_token", "paper-safety-test-token");
    localStorage.setItem("gateway_user", JSON.stringify({ id: "paper-safety-user", email: "paper@example.test" }));
  });
  const brokerRequests: string[] = [];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/api/, "");
    if (pathname.startsWith("/live/")) brokerRequests.push(`${route.request().method()} ${pathname}`);
    if (pathname.endsWith("/auth/me")) {
      await route.fulfill({ json: { id: "paper-safety-user", email: "paper@example.test" } });
    } else {
      await route.fulfill({ json: {} });
    }
  });

  await page.goto("/app/live-trading");
  await expect(page).toHaveURL(/\/app\/live-trading$/);
  expect(brokerRequests).toEqual([]);
});
