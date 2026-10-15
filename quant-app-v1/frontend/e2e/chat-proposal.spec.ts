import { expect, test } from "@playwright/test";

const token = "browser-owner-token";
const proposal = {
  provider: "openrouter",
  model: "test-model",
  prompt: "Buy when the 20-day moving average crosses above the 50-day average.",
  symbol: "AAPL",
  tf: "1d",
  bars: 100,
  capital: 1000,
  max_llm_calls: 2,
};

const providerResponse = {
  providers: [{
    id: "openrouter",
    label: "OpenRouter",
    group: "compatible",
    detail: "Browser-test provider",
    base_url: "https://example.test/v1",
    key_required: true,
    docs: "",
    has_key: true,
    has_stored_key: true,
    configured: true,
    models: [proposal.model],
    default_model: proposal.model,
  }],
  default_provider: "openrouter",
};

async function openAuthenticatedChat(page: import("@playwright/test").Page) {
  page.on("pageerror", (error) => console.error("Browser page error:", error));
  page.on("console", (message) => { if (message.type() === "error") console.error("Browser console error:", message.text()); });
  await page.addInitScript((accessToken) => {
    localStorage.setItem("gateway_auth_token", accessToken);
    localStorage.setItem("gateway_user", JSON.stringify({ id: "browser-owner", email: "owner@example.test" }));
    localStorage.setItem("gateway_llm_selection", JSON.stringify({ provider: "openrouter", model: "test-model" }));
  }, token);

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname.replace(/^\/api/, "");

    if (pathname === "/quotes") {
      await route.fulfill({ json: { quotes: [] } });
    } else if (pathname === "/auth/me") {
      await route.fulfill({ json: { id: "browser-owner", email: "owner@example.test" } });
    } else if (pathname === "/llm/providers") {
      await route.fulfill({ json: providerResponse });
    } else if (pathname === "/llm/providers/openrouter/models") {
      await route.fulfill({ json: { provider: "openrouter", models: [{ id: proposal.model, is_free: true }] } });
    } else if (pathname === "/agentic-lab/runs") {
      await route.fulfill({ json: { runs: [], summary: {} } });
    } else if (pathname.startsWith("/history/")) {
      await route.fulfill({ json: [] });
    } else if (pathname === "/llm/chat" && request.method() === "POST") {
      expect(request.headers().authorization).toBe(`Bearer ${token}`);
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: ${JSON.stringify({ type: "backtest_proposal", ...proposal })}\n\n`,
          `data: ${JSON.stringify({ type: "delta", text: "Review this historical backtest before it runs." })}\n\n`,
          `data: ${JSON.stringify({ type: "done", usage: null })}\n\n`,
        ].join(""),
      });
    } else {
      await route.fulfill({ json: {} });
    }
  });

  await page.goto("/app/harness");
  await expect(page.locator(".chat-topbar-title")).toHaveText("AI Chat");
  await expect(page.getByRole("button", { name: /OpenRouter.*test-model/ })).toBeVisible();

  await page.getByRole("checkbox", { name: "Allow public market context and backtest proposal tools" }).check();
  await page.getByPlaceholder("Ask anything — tickers, setups, your portfolio… (@ for context)").fill("Propose a moving average backtest for AAPL");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("region", { name: "Backtest proposal" })).toContainText("awaiting confirmation");
  await expect(page.getByText("Review this historical backtest before it runs.")).toBeVisible();
}

test("cancelling a backtest proposal sends no backtest request", async ({ page }) => {
  const startedJobs: string[] = [];
  await openAuthenticatedChat(page);
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/agentic-lab/backtest")) {
      startedJobs.push(request.url());
    }
  });

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("region", { name: "Backtest proposal" })).toHaveCount(0);
  await expect.poll(() => startedJobs).toEqual([]);
});

test("confirm starts a backtest and polls its job with the authenticated owner token", async ({ page }) => {
  const postHeaders: string[] = [];
  const pollHeaders: string[] = [];
  const submittedBodies: unknown[] = [];
  await openAuthenticatedChat(page);

  await page.route("**/api/agentic-lab/backtest", async (route) => {
    postHeaders.push(route.request().headers().authorization ?? "");
    submittedBodies.push(route.request().postDataJSON());
    await route.fulfill({ json: { job_id: "owner-job-123" } });
  });
  await page.route("**/api/agentic-lab/jobs/owner-job-123", async (route) => {
    pollHeaders.push(route.request().headers().authorization ?? "");
    await route.fulfill({ json: { id: "owner-job-123", status: "succeeded", progress: 1, message: "Run complete", result: { id: "result-1" }, error: null } });
  });

  await page.getByRole("button", { name: "Confirm backtest" }).click();
  await expect(page.getByText("Run complete")).toBeVisible();
  expect(postHeaders).toEqual([`Bearer ${token}`]);
  expect(pollHeaders).toEqual([`Bearer ${token}`]);
  expect(submittedBodies).toEqual([{
    kind: "llm",
    provider: proposal.provider,
    model: proposal.model,
    prompt: proposal.prompt,
    symbol: proposal.symbol,
    tf: proposal.tf,
    bars: proposal.bars,
    capital: proposal.capital,
    max_llm_calls: proposal.max_llm_calls,
    risk: { max_position_pct: 100, max_drawdown_pct: 0, allow_short: true },
  }]);
});

test("signed-out chat prompts for sign-in without sending a model request", async ({ page }) => {
  const chatRequests: string[] = [];
  page.on("pageerror", (error) => console.error("Signed-out chat page error:", error));
  await page.addInitScript(() => {
    localStorage.removeItem("gateway_auth_token");
    localStorage.removeItem("gateway_user");
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/llm/chat" && request.method() === "POST") chatRequests.push(request.url());
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname === "/llm/providers") return route.fulfill({ json: providerResponse });
    if (pathname === "/llm/providers/openrouter/models") return route.fulfill({ json: { provider: "openrouter", models: [{ id: proposal.model, is_free: true }] } });
    if (pathname === "/auth/me") return route.fulfill({ status: 401, json: { detail: "Not signed in" } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/harness");
  await expect(page.locator(".chat-page")).toBeVisible();
  await expect(page.locator(".chat-topbar-title")).toHaveText("AI Chat");
  await page.getByPlaceholder("Ask anything — tickers, setups, your portfolio… (@ for context)").fill("Explain a moving average crossover");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert")).toContainText("Sign in to chat");
  expect(chatRequests).toEqual([]);
});

test("expired authentication when confirming a proposal shows an error and does not poll a job", async ({ page }) => {
  let startRequests = 0;
  let pollRequests = 0;
  await openAuthenticatedChat(page);

  await page.route("**/api/agentic-lab/backtest", async (route) => {
    startRequests += 1;
    expect(route.request().headers().authorization).toBe(`Bearer ${token}`);
    await route.fulfill({ status: 401, json: { detail: "Access token expired" } });
  });
  await page.route("**/api/agentic-lab/jobs/**", async (route) => {
    pollRequests += 1;
    await route.fulfill({ status: 401, json: { detail: "Access token expired" } });
  });

  await page.getByRole("button", { name: "Confirm backtest" }).click();
  await expect(page.getByRole("alert")).toContainText("Access token expired");
  expect(startRequests).toBe(1);
  expect(pollRequests).toBe(0);
  await expect(page.getByRole("region", { name: "Backtest proposal" })).toBeVisible();
});

test("Backtester submits a bounded authenticated run and displays its completed job", async ({ page }) => {
  const postHeaders: string[] = [];
  const pollHeaders: string[] = [];
  const submittedBodies: unknown[] = [];
  const strategyPrompt = "Go long when the 20-day average crosses above the 50-day average.";
  await page.addInitScript((accessToken) => {
    localStorage.setItem("gateway_auth_token", accessToken);
    localStorage.setItem("gateway_user", JSON.stringify({ id: "browser-owner", email: "owner@example.test" }));
  }, token);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (pathname === "/auth/me") return route.fulfill({ json: { id: "browser-owner", email: "owner@example.test" } });
    if (pathname === "/llm/providers") return route.fulfill({ json: providerResponse });
    if (pathname === "/llm/providers/openrouter/models") return route.fulfill({ json: { provider: "openrouter", models: [{ id: proposal.model, is_free: true }] } });
    if (pathname === "/agentic-lab/agents") return route.fulfill({ json: { agents: [] } });
    if (pathname === "/agentic-lab/research") return route.fulfill({ json: { research: [] } });
    if (pathname === "/agentic-lab/runs") return route.fulfill({ json: { runs: [] } });
    if (pathname.startsWith("/history/")) return route.fulfill({ json: [] });
    if (pathname === "/quotes") return route.fulfill({ json: { quotes: [] } });
    if (pathname === "/agentic-lab/backtest" && request.method() === "POST") {
      postHeaders.push(request.headers().authorization ?? "");
      submittedBodies.push(request.postDataJSON());
      return route.fulfill({ json: { job_id: "backtester-job-456" } });
    }
    if (pathname === "/agentic-lab/jobs/backtester-job-456") {
      pollHeaders.push(request.headers().authorization ?? "");
      return route.fulfill({ json: { id: "backtester-job-456", status: "succeeded", progress: 1, message: "Run complete", result: { id: "backtester-result-1" }, error: null } });
    }
    return route.fulfill({ json: {} });
  });

  await page.goto("/app/agentic-lab?tab=backtests");
  await expect(page.getByRole("tab", { name: "Backtests" })).toHaveAttribute("aria-selected", "true");
  await page.locator(".strategy-prompt-field textarea").fill(strategyPrompt);
  await page.locator(".strategy-launcher-grid select").first().selectOption("openrouter");
  await expect(page.locator(".strategy-model-field select")).toBeVisible();
  await page.locator(".strategy-model-field select").selectOption(proposal.model);
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();

  await expect(page.getByRole("status")).toContainText("Backtest complete");
  expect(postHeaders).toEqual([`Bearer ${token}`]);
  expect(pollHeaders).toEqual([`Bearer ${token}`]);
  expect(submittedBodies).toEqual([{
    kind: "llm",
    prompt: strategyPrompt,
    provider: proposal.provider,
    model: proposal.model,
    symbol: "AAPL",
    tf: "1d",
    bars: 260,
    capital: 10000,
    max_llm_calls: 12,
    risk: { max_position_pct: 100, max_drawdown_pct: 0, allow_short: true },
  }]);
});
