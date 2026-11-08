import { expect, test } from "@playwright/test";

const token = "strategy-studio-test-token";
const user = { id: "studio-user", email: "studio@example.test" };

const seededStrategy = {
  id: "strategy-rsi",
  name: "RSI Reversion",
  description: "Buy oversold RSI on liquid US equities",
  status: "draft",
  version: 2,
  universe: ["AAPL", "MSFT"],
  timeframe: "1d",
  tags: ["swing"],
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-05T00:00:00Z",
};

const seededSpec = {
  strategy_id: seededStrategy.id,
  version: 2,
  name: seededStrategy.name,
  description: seededStrategy.description,
  universe: seededStrategy.universe,
  timeframe: seededStrategy.timeframe,
  entry_rules: [],
  exit_rules: [],
  sizing_rules: [],
  invalidation_rules: [],
  session_rules: [],
  event_rules: [],
  assumptions: {},
  tags: seededStrategy.tags,
};

test("strategy studio is reachable from navigation and creates an account-scoped strategy", async ({
  page,
}) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const strategies = [{ ...seededStrategy }];
  const listCalls: (string | undefined)[] = [];
  const createBodies: Record<string, unknown>[] = [];
  const versionPosts: (string | undefined)[] = [];

  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");

    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/strategies" && request.method() === "GET") {
      listCalls.push(request.headers()["authorization"]);
      return route.fulfill({ json: strategies });
    }
    if (pathname === "/strategies" && request.method() === "POST") {
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      createBodies.push(body);
      const created = {
        id: "strategy-breakout",
        name: String(body.name ?? ""),
        description: String(body.description ?? ""),
        status: "draft",
        version: 1,
        universe: (body.universe as string[]) ?? [],
        timeframe: String(body.timeframe ?? "1h"),
        tags: (body.tags as string[]) ?? [],
        created_at: "2026-11-08T00:00:00Z",
        updated_at: "2026-11-08T00:00:00Z",
      };
      strategies.unshift(created);
      return route.fulfill({ status: 201, json: created });
    }
    if (/^\/strategies\/[^/]+\/versions$/.test(pathname) && request.method() === "POST") {
      const strategyId = pathname.split("/")[2];
      versionPosts.push(request.headers()["authorization"]);
      return route.fulfill({
        status: 201,
        json: { strategy_id: strategyId, version: 2, spec: seededSpec, created_at: "2026-11-08T01:00:00Z" },
      });
    }
    if (/^\/strategies\/[^/]+\/versions$/.test(pathname)) {
      const strategyId = pathname.split("/")[2];
      return route.fulfill({
        json: [
          { strategy_id: strategyId, version: 1, spec: { ...seededSpec, strategy_id: strategyId }, created_at: "2026-11-08T00:00:00Z" },
        ],
      });
    }
    if (/^\/strategies\/[^/]+\/versions\/\d+$/.test(pathname)) {
      return route.fulfill({ json: { strategy_id: "strategy-rsi", version: 1, spec: seededSpec, created_at: "2026-11-08T00:00:00Z" } });
    }
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/filings") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");
  await page.getByRole("link", { name: "Strategies", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/strategies$/);
  await expect(page.getByRole("heading", { name: "Strategy Studio", level: 1 })).toBeVisible();

  const card = page.locator('[data-strategy-id="strategy-rsi"]');
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading", { name: "RSI Reversion" })).toBeVisible();
  await expect(card).toContainText("2 symbols");
  await expect(card).toContainText("1d");
  await expect(card).toContainText("v2");

  expect(listCalls.length).toBeGreaterThan(0);
  expect(listCalls.every((authorization) => authorization === `Bearer ${token}`)).toBe(true);

  await page.getByRole("button", { name: "+ New Strategy" }).click();
  await page.getByLabel("Name").fill("Breakout Confirmation");
  await page.getByLabel("Description").fill("Enter on a confirmed range break");
  await page.getByLabel("Universe (comma-separated symbols)").fill("AAPL, nvda");
  await page.getByLabel("Timeframe").selectOption("4h");
  await page.getByLabel("Tags (comma-separated)").fill("breakout");
  await page.getByRole("button", { name: "Create Strategy" }).click();

  await expect(page.getByRole("heading", { name: /Breakout Confirmation/ })).toBeVisible();
  expect(createBodies).toHaveLength(1);
  expect(createBodies[0]).toMatchObject({
    name: "Breakout Confirmation",
    universe: ["AAPL", "NVDA"],
    timeframe: "4h",
    tags: ["breakout"],
  });

  await page.getByRole("button", { name: "Save Version" }).click();
  await expect(page.locator(".editor-header h2")).toContainText("v2");
  expect(versionPosts).toHaveLength(1);
  expect(versionPosts[0]).toBe(`Bearer ${token}`);

  // The fabricated backtest tab and the no-op promote control are gone.
  await expect(page.getByRole("button", { name: "Backtest" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Promote Selected/ })).toHaveCount(0);
});

test("signed-out visitors get a sign-in prompt instead of a strategy list", async ({ page }) => {
  let strategyRequests = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname.startsWith("/strategies")) strategyRequests += 1;
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/strategies");

  await expect(page.getByRole("heading", { name: "Sign in to see your strategies" })).toBeVisible();
  await expect(page.locator(".strategy-card")).toHaveCount(0);
  expect(strategyRequests).toBe(0);
});
