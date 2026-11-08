import { expect, test } from "@playwright/test";

const token = "vault-test-token";
const user = { id: "vault-user", email: "vault@example.test" };

interface SecretMeta {
  name: string;
  note: string;
  length: number;
  updated_at?: string;
}

test("the vault is reachable from Providers and stores/reveals/deletes an owner-scoped secret", async ({ page }) => {
  await page.addInitScript(
    ({ accessToken, account }) => {
      localStorage.setItem("gateway_auth_token", accessToken);
      localStorage.setItem("gateway_user", JSON.stringify(account));
    },
    { accessToken: token, account: user },
  );

  let secrets: SecretMeta[] = [];
  const vaultCalls: { method: string; path: string; authorization?: string }[] = [];
  const putBodies: Record<string, unknown>[] = [];

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
    if (pathname === "/settings/providers") return route.fulfill({ json: [] });
    if (pathname === "/llm/providers") return route.fulfill({ json: { providers: [] } });

    if (pathname === "/vault" && request.method() === "GET") {
      vaultCalls.push({ method: request.method(), path: pathname, authorization });
      return route.fulfill({ json: secrets });
    }
    if (pathname.startsWith("/vault/") && request.method() === "PUT") {
      vaultCalls.push({ method: request.method(), path: pathname, authorization });
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      putBodies.push(body);
      const name = decodeURIComponent(pathname.slice("/vault/".length));
      const meta: SecretMeta = {
        name,
        note: String(body.note ?? ""),
        length: String(body.value ?? "").length,
        updated_at: new Date().toISOString(),
      };
      secrets = [meta];
      return route.fulfill({ json: meta });
    }
    if (pathname.endsWith("/reveal") && request.method() === "GET") {
      vaultCalls.push({ method: request.method(), path: pathname, authorization });
      const name = decodeURIComponent(pathname.slice("/vault/".length, -"/reveal".length));
      return route.fulfill({ json: { name, value: "cf-secret-value" } });
    }
    if (pathname.startsWith("/vault/") && request.method() === "DELETE") {
      vaultCalls.push({ method: request.method(), path: pathname, authorization });
      const name = decodeURIComponent(pathname.slice("/vault/".length));
      secrets = secrets.filter((item) => item.name !== name);
      return route.fulfill({ status: 204, body: "" });
    }

    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/news") return route.fulfill({ json: { items: [] } });
    if (pathname === "/filings") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/overview");
  await page.getByRole("button", { name: "User menu" }).click();
  await page.getByRole("menuitem", { name: /Account settings/ }).click();

  await expect(page).toHaveURL(/\/app\/settings$/);
  await expect(page.getByRole("heading", { name: "Secrets vault — encrypted at rest" })).toBeVisible();
  await expect(page.locator("[data-vault-count]")).toHaveAttribute("data-vault-count", "0");

  await page.getByPlaceholder("Name (e.g. cloudflare-api-token)").fill("cloudflare-api-token");
  await page.getByPlaceholder("Secret value").fill("cf-secret-value");
  await page.getByPlaceholder("Note (optional)").fill("E2E secret");
  await page.getByRole("button", { name: /Store secret/ }).click();

  await expect.poll(() => putBodies.length).toBe(1);
  expect(putBodies[0]).toMatchObject({ value: "cf-secret-value", note: "E2E secret" });
  await expect(page.locator("[data-vault-count]")).toHaveAttribute("data-vault-count", "1");
  const row = page.getByRole("row").filter({ hasText: "cloudflare-api-token" });
  await expect(row).toContainText("E2E secret");

  await row.getByRole("button", { name: "Reveal" }).click();
  await expect(page.getByText("cloudflare-api-token: cf-secret-value")).toBeVisible();

  page.on("dialog", (dialog) => void dialog.accept());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.locator("[data-vault-count]")).toHaveAttribute("data-vault-count", "0");

  expect(vaultCalls.length).toBeGreaterThanOrEqual(4);
  expect(vaultCalls.every((call) => call.authorization === `Bearer ${token}`)).toBe(true);
});

test("signed-out visitors get a sign-in prompt instead of vault data", async ({ page }) => {
  let vaultRequests = 0;
  await page.route(/(?:\/api\/|127\.0\.0\.1:8000\/)/, (route) => {
    const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (pathname === "/notices") {
      return route.fulfill({
        json: { accepted: true, version: "2026-11-07", accepted_at: "2026-11-07T12:00:00Z" },
      });
    }
    if (pathname === "/settings/providers") return route.fulfill({ json: [] });
    if (pathname === "/llm/providers") return route.fulfill({ json: { providers: [] } });
    if (pathname.startsWith("/vault")) vaultRequests += 1;
    return route.fulfill({ status: 401, json: { detail: "Not authenticated" } });
  });

  await page.goto("/app/settings");

  await expect(page.getByRole("heading", { name: "Sign in to use the vault" })).toBeVisible();
  await expect(page.locator(".vault-table")).toHaveCount(0);
  expect(vaultRequests).toBe(0);
});
