import { expect, test } from "@playwright/test";

const token = "journal-test-token";
const user = { id: "journal-user", email: "journal@example.test" };

const now = new Date().toISOString();

const seededEntry = {
  id: "journal-seed",
  symbol: "AAPL",
  side: "buy",
  quantity: 10,
  entry_price: 100,
  entry_time: now,
  hypothesis: "Breakout above the range high",
  entry_context: "Volume expansion",
  tags: ["swing"],
  status: "open",
  source: "manual",
  created_at: now,
  updated_at: now,
};

const statsPayload = {
  total_trades: 2,
  winning_trades: 1,
  losing_trades: 1,
  win_rate: 50,
  total_pnl: 120.5,
  avg_win: 200,
  avg_loss: -79.5,
  profit_factor: 2.52,
  avg_hold_time: "3h 10m",
};

test("journal is reachable from navigation and creates an account-scoped entry", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const entries = [{ ...seededEntry }];
  const listCalls: (string | undefined)[] = [];
  const createBodies: Record<string, unknown>[] = [];
  let divergenceRequests = 0;

  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");

    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/journal" && request.method() === "GET") {
      listCalls.push(request.headers()["authorization"]);
      return route.fulfill({ json: { entries } });
    }
    if (pathname === "/journal/stats") {
      return route.fulfill({ json: statsPayload });
    }
    if (pathname === "/journal" && request.method() === "POST") {
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      createBodies.push(body);
      const created = {
        id: "journal-created",
        symbol: String(body.symbol ?? ""),
        side: String(body.side ?? "buy"),
        quantity: Number(body.quantity ?? 0),
        entry_price: Number(body.entry_price ?? 0),
        entry_time: new Date().toISOString(),
        hypothesis: String(body.hypothesis ?? ""),
        entry_context: String(body.entry_context ?? ""),
        tags: (body.tags as string[]) ?? [],
        status: "open",
        source: "manual",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      entries.unshift(created);
      return route.fulfill({ status: 201, json: created });
    }
    if (pathname.startsWith("/divergence")) divergenceRequests += 1;
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/filings") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");
  await page.getByRole("link", { name: "Journal", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/journal$/);
  await expect(page.getByRole("heading", { name: "Trade Journal", level: 1 })).toBeVisible();
  await expect(page.locator(".trade-journal")).toHaveAttribute("data-entry-count", "1");
  await expect(page.getByText("50.0%")).toBeVisible();
  await expect(page.getByText("+120.50")).toBeVisible();
  await expect(page.getByText("2.52")).toBeVisible();

  await page.getByRole("button", { name: "Table" }).click();
  const seededRow = page.locator('[data-entry-id="journal-seed"]');
  await expect(seededRow).toBeVisible();
  await expect(seededRow).toContainText("AAPL");
  await expect(seededRow).toContainText("Manual");

  expect(listCalls.length).toBeGreaterThan(0);
  expect(listCalls.every((authorization) => authorization === `Bearer ${token}`)).toBe(true);

  await page.getByRole("button", { name: "+ New trade" }).click();
  const dialog = page.getByRole("dialog", { name: "New trade entry" });
  await dialog.getByLabel("Symbol").fill("nvda");
  await dialog.getByLabel("Side").selectOption("sell");
  await dialog.getByLabel("Quantity").fill("5");
  await dialog.getByLabel("Entry price").fill("200");
  await dialog.getByLabel("Hypothesis / thesis").fill("Fade the failed breakout");
  await dialog.getByLabel("Tags (comma-separated)").fill("mean-reversion");
  await dialog.getByRole("button", { name: "Create entry" }).click();

  const createdRow = page.locator('[data-entry-id="journal-created"]');
  await expect(createdRow).toBeVisible();
  await expect(createdRow).toContainText("NVDA");
  await expect(createdRow).toContainText("Sell");
  expect(createBodies).toHaveLength(1);
  expect(createBodies[0]).toMatchObject({
    symbol: "NVDA",
    side: "sell",
    quantity: 5,
    entry_price: 200,
    hypothesis: "Fade the failed breakout",
    tags: ["mean-reversion"],
  });

  // The broker sync control, the impossible "actual" comparison and the mock
  // divergence panel are gone rather than left claiming data.
  await expect(page.getByRole("button", { name: /Sync actual trades/ })).toHaveCount(0);
  await expect(page.getByText(/Actual PnL/)).toHaveCount(0);
  expect(divergenceRequests).toBe(0);
});

test("signed-out visitors get a sign-in prompt instead of journal entries", async ({ page }) => {
  let journalRequests = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname.startsWith("/journal")) journalRequests += 1;
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/journal");

  await expect(page.getByRole("heading", { name: "Sign in to see your journal" })).toBeVisible();
  await expect(page.locator(".entries-table")).toHaveCount(0);
  expect(journalRequests).toBe(0);
});
