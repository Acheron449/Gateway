import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "offline in accessibility test" }),
    }),
  );
});

function luminance(hex: string): number {
  const channels = hex
    .replace("#", "")
    .match(/../g)!
    .map((value) => parseInt(value, 16) / 255)
    .map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string, background: string): number {
  const [a, b] = [luminance(foreground), luminance(background)];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

test("command palette and brand are keyboard reachable", async ({ page }) => {
  await page.goto("/app/overview");

  const brand = page.getByRole("button", { name: /Gateway/ });
  await expect(brand).toBeVisible();

  await page.keyboard.press("Control+K");
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await expect(dialog).toBeVisible();

  const input = page.getByRole("combobox", { name: "Command" });
  await expect(input).toBeFocused();
  await expect(input).toHaveAttribute("aria-activedescendant", "command-option-0");

  await page.keyboard.press("ArrowDown");
  await expect(input).toHaveAttribute("aria-activedescendant", "command-option-1");

  // Tab stays inside the modal instead of reaching the page behind it.
  await page.keyboard.press("Tab");
  await expect(input).toBeFocused();

  // The highlighted command is activatable from the keyboard alone.
  await input.fill("scanner");
  await expect(input).toHaveAttribute("aria-activedescendant", "command-option-0");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/app\/scanner/);
});

test("muted body text meets 4.5:1 and focus rings are visible", async ({ page }) => {
  await page.goto("/app/overview");

  const tokens = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return {
      muted: style.getPropertyValue("--text-muted").trim(),
      background: style.getPropertyValue("--bg-primary").trim(),
    };
  });
  expect(tokens.muted).toMatch(/^#[0-9a-f]{6}$/i);
  expect(contrast(tokens.muted, tokens.background)).toBeGreaterThanOrEqual(4.5);

  const search = page.getByRole("button", { name: "Search symbols and commands" });
  await page.keyboard.press("Tab");
  await search.focus();
  const outlineWidth = await search.evaluate((element) => getComputedStyle(element).outlineWidth);
  expect(parseFloat(outlineWidth)).toBeGreaterThanOrEqual(2);
});

test("layout collapses to one usable column at 1024 px", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto("/app/overview");

  const leftPanel = page.locator(".left-panel-shell").first();
  const rightPanel = page.locator(".right-panel-shell").first();
  await expect(leftPanel).toHaveCount(1);

  expect((await leftPanel.boundingBox())!.width).toBeLessThanOrEqual(60);
  expect((await rightPanel.boundingBox())!.width).toBeLessThanOrEqual(60);

  const center = await page.locator(".center-canvas-inner").boundingBox();
  expect(center).not.toBeNull();
  expect(center!.width).toBeGreaterThanOrEqual(900);
});
