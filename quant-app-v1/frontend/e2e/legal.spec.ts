import { expect, test } from "@playwright/test";

const token = "legal-notice-test-token";
const user = { id: "legal-notice-user", email: "legal@example.test" };

async function mockNoticeApi(page: import("@playwright/test").Page, accepted: { value: boolean }) {
  await page.addInitScript((accessToken) => {
    localStorage.setItem("gateway_auth_token", accessToken);
    localStorage.setItem(
      "gateway_user",
      JSON.stringify({ id: "legal-notice-user", email: "legal@example.test" }),
    );
  }, token);

  let acceptancePosts = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/auth/me") return route.fulfill({ json: user });
    if (pathname === "/notices" && request.method() === "POST") {
      acceptancePosts += 1;
      accepted.value = true;
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/notices") {
      return route.fulfill({
        json: {
          accepted: accepted.value,
          version: "2026-11-07",
          accepted_at: accepted.value ? "2026-11-07T12:00:00Z" : null,
        },
      });
    }
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  return () => acceptancePosts;
}

test("first authenticated use records acceptance and keeps the notice visible", async ({ page }) => {
  const accepted = { value: false };
  const posts = await mockNoticeApi(page, accepted);

  await page.goto("/app/overview");

  await expect(page.getByText(/Results are simulated and historical, not investment advice/i).first()).toBeVisible();
  const dialog = page.getByRole("dialog", { name: "Before you continue" });
  await expect(dialog).toBeVisible();
  await page.getByRole("button", { name: "I understand and accept" }).click();
  await expect(dialog).toBeHidden();
  expect(posts()).toBe(1);
  expect(accepted.value).toBe(true);
  await expect(page.getByLabel("Legal notice")).toContainText("not investment advice");
});

test("an already-accepted user sees the persistent notice without a prompt", async ({ page }) => {
  const accepted = { value: true };
  await mockNoticeApi(page, accepted);

  await page.goto("/app/overview");

  await expect(page.getByLabel("Legal notice")).toContainText("Paper execution only");
  await expect(page.getByRole("dialog", { name: "Before you continue" })).toHaveCount(0);
});
