import { expect, test } from "@playwright/test";

const token = "options-test-token";
const user = { id: "options-user", email: "bs@example.test" };

const priced = {
  engine_version: "bs-1.0.0",
  type: "call",
  price: 4.6146,
  intrinsic: 0,
  time_value: 4.6146,
  greeks: { delta: 0.5309, gamma: 0.0394, vega: 19.71, theta: -0.0241, rho: 11.31 },
  greek_units: {
    delta: "per 1.00 spot",
    gamma: "per 1.00 spot",
    vega: "per 1% vol",
    theta: "per calendar day",
    rho: "per 1% rate",
  },
  bounds: { lower: 0, upper: 100 },
  near_expiry_unstable: false,
  warnings: [],
  model_boundaries: ["European exercise only; no early-exercise or American premium."],
};

const implied = {
  implied_volatility: 0.2,
  converged: true,
  iterations: 6,
  solver: "brent",
  market_price: 5.2,
  model_price: 4.6146,
  price_error: 0.5854,
  bounds: { lower: 0, upper: 100 },
  warnings: [],
};

test("options is reachable from navigation and prices a contract on the live backend path", async ({
  page,
}) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  const priceCalls: { authorization: string | undefined; body: Record<string, unknown> }[] = [];
  const ivCalls: { authorization: string | undefined; body: Record<string, unknown> }[] = [];
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/quant/options/price" && request.method() === "POST") {
      priceCalls.push({
        authorization: request.headers()["authorization"],
        body: (request.postDataJSON() ?? {}) as Record<string, unknown>,
      });
      return route.fulfill({ json: priced });
    }
    if (pathname === "/quant/options/implied-vol" && request.method() === "POST") {
      ivCalls.push({
        authorization: request.headers()["authorization"],
        body: (request.postDataJSON() ?? {}) as Record<string, unknown>,
      });
      return route.fulfill({ json: implied });
    }
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");

  await page.getByRole("link", { name: "Options", exact: true }).click();

  await expect(page).toHaveURL(/\/app\/options$/);
  await expect(page.getByRole("heading", { name: "Options pricing", level: 1 })).toBeVisible();
  await expect(page.getByText(/European Black-Scholes-Merton/i)).toBeVisible();

  // The calculator prices the default contract on mount, through the real route.
  const summary = page.locator(".opt-summary");
  await expect(summary).toContainText("4.6146");
  await expect(summary).toContainText("call · model bs-1.0.0");
  await expect(summary).toContainText("-0.5854");
  await expect(summary).toContainText("20.00%");
  await expect(summary).toContainText("converged · brent · 6 iterations");
  await expect(summary).toContainText("0.00 vol pts");

  const greeks = page.locator("table.report-table");
  await expect(greeks).toContainText("Delta");
  await expect(greeks).toContainText("0.530900");
  await expect(greeks).toContainText("Gamma");
  await expect(greeks).toContainText("per calendar day");

  // React StrictMode re-runs the mount effect once in development, so the
  // same request may be issued twice; every call must be authenticated and identical.
  expect(priceCalls.length).toBeGreaterThan(0);
  expect(ivCalls.length).toBeGreaterThan(0);
  for (const call of priceCalls) expect(call.authorization).toBe(`Bearer ${token}`);
  for (const call of ivCalls) expect(call.authorization).toBe(`Bearer ${token}`);
  expect(priceCalls[0]!.body).toEqual({
    S: 100,
    K: 100,
    T: 0.25,
    r: 0.05,
    q: 0,
    sigma: 0.2,
    type: "call",
  });

  expect(ivCalls[0]!.body).toEqual({
    market_price: 5.2,
    S: 100,
    K: 100,
    T: 0.25,
    r: 0.05,
    q: 0,
    type: "call",
  });

  await expect(page.getByText(/would go here|placeholder quote|lorem ipsum/i)).toHaveCount(0);
});
