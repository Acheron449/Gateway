import { expect, test } from "@playwright/test";

const bars = Array.from({ length: 300 }, (_, index) => {
  const open = 100 + index * 0.1;
  return {
    time: 1_786_000_000 + index * 3_600,
    open,
    high: open + 1,
    low: open - 1,
    close: open + (index % 2 === 0 ? 0.5 : -0.5),
    volume: 1_000 + index,
  };
});

const providers = {
  providers: [
    {
      id: "yahoo",
      name: "Yahoo Finance",
      detail: "Test feed",
      available: true,
      is_default: true,
    },
  ],
  default: "yahoo",
};

test("markets chart frames the recent window after the empty first draw", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("gateway_ui_chart_provider", "yahoo");
  });

  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/history/providers") return route.fulfill({ json: providers });
    if (path === "/history/AAPL") return route.fulfill({ json: bars });
    return route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "offline in chart test" }),
    });
  });

  await page.goto("/app/markets");

  const chart = page.locator(".main-chart");
  await expect(chart).toHaveAttribute("data-chart-bars", "300");
  await expect(chart).toHaveAttribute("data-visible-end", "300");
  await expect(chart).toHaveAttribute("data-visible-bars", "120");
});
