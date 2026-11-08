# Model, Chat, Backtester, and Calendar Improvements — Design

**Date:** 2026-10-12  
**Status:** Approved; implementation-plan review pending.  
**Scope:** Extend the existing Gateway web app without changing its paper-only/historical-only boundary.

## Intent and acceptance criteria

The user wants to finish the existing free-model picker work and then improve model choice consistency, chat reliability and feature access, direct strategy entry in Backtester, the calendar source list, and the overall feel of those touched screens. The proposed architecture was approved. The chat backtest authorization was separately decided as **ask before each run**.

Acceptance criteria:

1. Every existing selectable LLM model in AI Chat, Agentic Lab (agent creation, research generation, iterative research), and Provider Settings uses a model dropdown backed by the provider catalogue and a **Free models only** toggle.
2. Unknown free status fails closed while the filter is on; changing provider/filter preserves the selection only if it remains eligible. Manual model entry remains available only when model discovery fails or returns no models with the filter off.
3. OpenAI-compatible streaming renders incremental text exactly once. Usage/final metadata and tool-call frames never become answer text. Cumulative message snapshots are not appended to already streamed deltas. Do not text-deduplicate legitimate repeated words.
4. AI Chat can invoke only a documented, bounded allowlist of app features. A model-generated backtest proposal is displayed for review and requires a user confirmation click before a model-backed run starts or spends backtest-call credits. The proposal cannot create or place orders, access broker actions, or bypass authentication, risk limits, or existing call caps.
5. Backtester includes a natural-language strategy field and model/provider selectors. Its explicit **Run backtest** button starts the existing historical LLM strategy backtest with bounded inputs and call cap. It does not generate or execute Python/JavaScript, place orders, or start live/paper trades.
6. Yahoo Finance economic events appear as an explicit calendar source and participate in the `auto` merged source chain. Map returned fields to the canonical EconomicEvent contract; clearly surface unavailability and do not misrepresent an empty/unavailable feed as complete data.
7. Affected model, chat, calendar, and backtest controls are visually consistent with existing Gateway dark-terminal styles, accessible labels, and responsive layout. Avoid broad unrelated redesign.
8. Backend tests, frontend production build/typecheck, and a browser pass cover the changed interaction paths. External Yahoo/OpenRouter availability is not a prerequisite for deterministic tests.
9. Protect `POST /llm/chat` with the existing `CurrentUser` dependency, since the current route accepts requests without verifying the frontend's auth header. Associate each `/agentic-lab/backtest` job with its creator and require authenticated, owner-scoped access when polling its job/result; retain visibility of existing shared runs through the established runs API.

## Existing implementation evidence

- `GET /llm/providers/{provider_id}/models` returns `{id, is_free}` catalogue entries, and `normalize_model_catalogue` intentionally fails closed except for explicitly tagged models and verified OpenRouter `:free` entries with zero text-generation prices.
- AI Chat (`AiHarness.tsx`) already contains the first free-only picker. `AgenticLab.tsx` still selects models in agent creation/research-generation/iterative-research controls; `LlmProviderSettings.tsx` still edits the default model as text and shows model chips.
- Chat stream service currently emits `delta` text and `done` usage, but falls back from `delta.content` to `choice.message.content` on each SSE frame. That fallback can treat a complete/snapshot message as another appended delta. Upstream stream frames must remain incremental; do not deduplicate legitimate same-valued token strings.
- Chat request schema currently accepts only system/user/assistant messages and has no tool schema. AI chat system policy describes deep links, not app tool invocations. Unlike the model-catalogue route, `POST /llm/chat` currently has no `CurrentUser` dependency despite the frontend sending an Authorization header; this plan must close that gap. The lab backtest start route requires `CurrentUser`, but job metadata and its poll route do not enforce job ownership; result polling must be scoped to the initiating user.
- `/agentic-lab/backtest` already starts an async historical job with an LLM-call cap and risk rules; `Backtester.tsx` renders the saved run list and comparisons. This is the permitted execution path.
- Calendar sources currently merge via `_CALENDAR_CHAIN`; Yahoo Finance is already a registered, keyless market-data provider for news/quotes/history but has no economic-calendar method. Repo root pins `yfinance==0.2.65`, which does not export the `Calendars` API. yfinance 1.0 introduced `Calendars.get_economic_events_calendar`; updating the root pin must be included and compatibility with existing Yahoo market-data code checked.

## Architecture and data flow

### Shared catalogue-driven model selector

Add a focused reusable frontend picker that receives provider ID, model value/change handler, catalogue state, and free-filter state. It loads the existing authenticated catalogue route for configured providers, caches per provider for the component lifetime, and treats missing/non-boolean `is_free` as false. The component must expose loading/error/empty states, preserve valid model choices, and allow text entry only as an explicit fallback when catalogue fetch cannot provide choices and filtering is disabled. Integrate it in the AI Chat popup, all Agentic Lab model-entry surfaces, and Provider Settings' default selection. Provider changes and filter transitions must not submit a stale/ineligible model.

### Chat streaming and allowlisted tools

Maintain the existing SSE event contract for text, while representing tool calls as their own typed structured event. The backend stream adapter will accept only incremental string `delta.content`; ignore content-free usage frames and never reinterpret a `message.content` snapshot as incremental text. Parse streamed tool-call fragments by index and emit a complete validated function call only after stream completion; malformed/incomplete calls are reported, not executed. The chat endpoint will accept a fixed server-owned tool schema, not caller-supplied executable definitions.

The initial allowlist is deliberately narrow:

- `get_market_context`: read-only public market data for an explicitly supplied symbol/timeframe and allowlisted context sections; no portfolio/broker/account data.
- `propose_backtest`: create a validated proposal (symbol, timeframe, strategy instruction, bar count, capital, provider/model, bounded call cap). It does not start a job. The frontend shows an approval panel, including model and max-call cap. On user confirmation, the existing authenticated `/agentic-lab/backtest` route starts the job; progress/result are shown and linked to the Backtests view.

The frontend validates tool arguments again, binds provider/model to the current chosen configuration (not model-supplied credentials), and requires authenticated user confirmation. Do not trigger silent tool round-trips or background model calls. Existing context feeding remains available and need not be executed as an LLM tool if that creates duplicate data requests.

### Natural-language Backtester strategy launcher

Place a strategy-launch panel above the run comparison inside Backtester. Reuse the app's selected symbol (editable within the panel), provider/model selector, timeframe/bars/capital/call-cap controls, and authenticated start/poll APIs. Label it as historical simulation, show a review summary before start, and present job progress/errors/result. Strategy text is a prompt passed to the existing model-driven backtester and never code interpreted by the app. Default max LLM calls remain bounded by existing API schema; user cannot exceed its range.

### Yahoo Finance economic calendar

Implement `calendar(limit)` on `YahooFinanceProvider` using `yf.Calendars().get_economic_events_calendar` in a worker thread because yfinance is synchronous. Request at most 100 events and map DataFrame rows to normalized `EconomicEvent`s (stable deterministic Yahoo IDs, UTC timestamps, country/currency, importance, actual/consensus/prior values, source/version/provenance). Handle pandas NaN, missing event times, unrecognized countries, malformed rows, missing `Calendars`, endpoint exceptions, and empty frames without raising raw exceptions; raise `ProviderUnavailableError` when the source itself is unavailable so `auto` can continue to other feeds. The explicit Yahoo source is strict like other named sources. Since the `Calendars` API begins at yfinance 1.0, raise the root requirement to `yfinance>=1.0,<2.0` (or a tested exact 1.x version) and run existing Yahoo provider tests. Do not infer event times from date-only rows; skip rows whose schedule cannot be normalized.

### Visual finish

Keep current compact, high-contrast Gateway theme. Consolidate repeated model-picking UI into the shared selector, use consistent field spacing, concise helper/status text, and responsive stacking for the new strategy launch and calendar source controls. Preserve semantic labels, keyboard access, and current navigation.

## Security, spend, and safety boundaries

- All provider/model requests require authentication. Add `CurrentUser` to `/llm/chat`; do not rely on frontend-only auth checks.
- Store the creator ID in new backtest job metadata and require that same authenticated owner on `/agentic-lab/jobs/{job_id}`; never reveal another user's in-progress or completed private backtest result.
- AI tool definitions are server-owned and allowlisted; model text/arguments are untrusted data.
- A model backtest proposal never starts without the user approving it in the UI. Backtest endpoint validation, risk normalization, and `max_llm_calls` limits remain authoritative.
- No live/paper execution APIs, order placement, secret material, account balances, or client-supplied API keys are tools.
- Keep requests bounded: tool call count and backtest call cap are limited; context symbols/sections/timeframes are validated with established API limits.
- External Yahoo data is best-effort, non-authoritative, and provenance-labelled.

## Error handling and compatibility

- Catalogue fetch failure: show a retryable message; only show manual entry if filtering is off. A free-only filter with unknown metadata offers no selectable model.
- Stream upstream errors remain visible as chat errors. Invalid SSE JSON may be ignored as today; a malformed tool call must fail closed. Abort/stop must not persist an incomplete tool proposal as an executed action.
- OpenRouter remains OpenAI-compatible, but no provider is assumed to support tools; if tool parameters are rejected, return a clear unsupported-tools error and retain plain-text chat usability rather than retrying invisibly.
- yfinance import/version/data/network failures produce source-unavailable status and allow the calendar merge chain to continue.
- Existing saved chat messages, saved provider settings, legacy model ID responses, existing backtest payloads, and calendar API response shape remain compatible.

## Verification

- Backend unit/API tests: model catalogue free metadata; stream delta versus snapshot/usage fixtures; tool-call fragment assembly, allowlist, malformed/unsupported provider handling, and proposal-not-execute behavior; anonymous `/llm/chat` rejection; backtest job owner polling and foreign-owner 404; yfinance DataFrame normalization/missing dependency/error cases; calendar source listing and merge fallback; existing Agentic Lab and Yahoo provider regressions.
- Frontend build/typecheck plus focused tests if an established framework is available; otherwise exercise rendered controls and state transitions in the app browser.
- Browser check: change providers/filter in AI Chat and Agentic Lab; select Provider Settings default from catalogue; verify free-only hides unknown entries; submit a Backtester strategy with a configured model and inspect progress/results; verify Chat's proposal requires confirmation and cancellation does not create a job; inspect calendar source selector and errors.
- Run `git diff --check` and review final changed hunks. Do not make a live provider call or deploy as part of deterministic verification.

## Deferred / not in scope

- General-purpose autonomous agent or arbitrary plugin/MCP access from chat.
- Strategy code generation/execution, live trading, paper trading, or automatic user-account actions.
- Treating Yahoo Finance as authoritative or guaranteed complete for macro events.
- Broad application redesign, authentication redesign, or adding new third-party services.
