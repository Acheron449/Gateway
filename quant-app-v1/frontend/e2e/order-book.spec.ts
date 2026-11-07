import { expect, test } from "@playwright/test";

const token = "order-book-test-token";
const user = { id: "order-book-user", email: "book@example.test" };

// 31 daily bars whose last close is 190.00 (previous 188.00), so the panel's
// derived mid is deterministic.
const bars = Array.from({ length: 31 }, (_, index) => {
  const close = 170 + index * 2;
  return {
    time: 1_786_000_000 + index * 86_400,
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close: index === 30 ? 190 : close,
    volume: 1_000_000 + index,
  };
});

const level = (
  side: "bid" | "ask",
  price: number,
  size: number,
  contributions: { archetype: string; size: number; share: number; agents: number }[],
) => ({
  price,
  side,
  size,
  share_of_side: side === "bid" ? 0.6 : 0.625,
  contributions,
});

const book = {
  simulated: true,
  label: "Simulated liquidity — not exchange data",
  engine_version: "ob-1.0.0",
  mid: 190,
  seed: 7,
  agents: 500,
  levels: [
    level("bid", 189.99, 120, [
      { archetype: "market_maker", size: 70, share: 0.583333, agents: 40 },
      { archetype: "noise", size: 50, share: 0.416667, agents: 22 },
    ]),
    level("bid", 189.98, 80, [
      { archetype: "large_passive", size: 80, share: 1, agents: 3 },
    ]),
    level("ask", 190.02, 100, [
      { archetype: "momentum", size: 60, share: 0.6, agents: 18 },
      { archetype: "market_maker", size: 40, share: 0.4, agents: 30 },
    ]),
    level("ask", 190.03, 60, [
      { archetype: "noise", size: 60, share: 1, agents: 25 },
    ]),
  ],
  best_bid: 189.99,
  best_ask: 190.02,
  crossed: false,
  spread: 0.03,
  spread_ticks: 3,
  levels_per_side: { bid: 2, ask: 2 },
  levels_truncated: { bid: 0, ask: 0 },
  total_size: 360,
  visible_size: 360,
  dropped_size: 0,
  conservation_delta: 0,
  size_by_archetype: { market_maker: 110, momentum: 60, noise: 110, large_passive: 80 },
  weights: { market_maker: 0.4, momentum: 0.2, noise: 0.3, large_passive: 0.1 },
  parameters: { tick: 0.01, band: 0.005, inventory: 0 },
  output_hash: "test-book-hash",
};

test("order book is reachable from navigation and renders the live simulated ladder", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const simulateRequests: { authorization: string | undefined; body: Record<string, unknown> }[] = [];
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
    if (pathname === "/quant/orderbook/simulate" && request.method() === "POST") {
      simulateRequests.push({
        authorization: request.headers()["authorization"],
        body: (request.postDataJSON() ?? {}) as Record<string, unknown>,
      });
      return route.fulfill({ json: book });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");

  await page.getByRole("link", { name: "Order book", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/orderbook$/);
  await expect(page.getByRole("heading", { name: "Order book", level: 1 })).toBeVisible();
  await expect(page.getByText(/Simulated liquidity — not exchange data/i).first()).toBeVisible();

  const ladder = page.locator(".ob-ladder");
  await expect(ladder).toBeVisible();
  await expect(ladder).toHaveAttribute("data-simulated", "true");
  await expect(ladder).toHaveAttribute("data-engine", "ob-1.0.0");
  await expect(ladder).toHaveAttribute("data-levels", "4");
  await expect(ladder).toHaveAttribute("data-best-bid", "189.99");
  await expect(ladder).toHaveAttribute("data-best-ask", "190.02");
  await expect(ladder).toHaveAttribute("data-spread-ticks", "3");

  // Both sides are drawn, stacked, from the backend's levels.
  await expect(page.locator(".ob-row")).toHaveCount(4);
  await expect(page.locator(".ob-side.bid .ob-bar")).toHaveCount(2);
  await expect(page.locator(".ob-side.ask .ob-bar")).toHaveCount(2);

  // Spread and depth come from the response, not from client-side invention.
  const summary = page.locator(".ob-summary");
  await expect(summary).toContainText("189.99");
  await expect(summary).toContainText("190.02");
  await expect(summary).toContainText("0.03 · 3 ticks");
  const summaryText = (await summary.innerText()).replace(/\s+/g, " ");
  expect(summaryText).toMatch(/bid depth 200/i);
  expect(summaryText).toMatch(/ask depth 160/i);

  // A level expands to the archetype attribution the engine returned.
  await page.locator(".ob-row.bid").first().click();
  await expect(page.getByRole("heading", { name: "Bid 189.99" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Who is behind this level" })).toContainText("Market maker");

  // The request was authenticated and its mid came from the last daily close,
  // never from a hand-entered or client-fabricated price.
  expect(simulateRequests.length).toBeGreaterThan(0);
  for (const call of simulateRequests) {
    expect(call.authorization).toBe(`Bearer ${token}`);
    expect(call.body["mid"]).toBe(190);
    expect(call.body["agents"]).toBe(500);
    expect(call.body["seed"]).toBe(7);
  }

  await expect(page.getByText(/would go here|placeholder ladder/i)).toHaveCount(0);
});
