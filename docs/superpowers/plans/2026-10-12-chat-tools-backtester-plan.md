# AI Chat Tools and Natural-Language Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat streaming robust, allow a model to prepare safe feature actions for user confirmation, and let users backtest typed strategy intent from Backtester.

**Architecture:** Keep the existing OpenAI-compatible SSE stream but distinguish incremental text and tool-call events. The model may only call server-defined `get_market_context` or `propose_backtest`; backtests are proposals until explicitly approved in UI. Both Chat confirmation and Backtester launch reuse authenticated, owner-scoped Agentic Lab backtest jobs and the existing call/risk limits.

**Tech Stack:** FastAPI, Pydantic, httpx, Python async iterators, React 18, TypeScript, Vite, existing job store and lab backtester.

**Spec:** [../specs/2026-10-12-model-chat-backtest-calendar-design.md](../specs/2026-10-12-model-chat-backtest-calendar-design.md)

## Global Constraints

- Tool definitions remain server-owned, fixed, and allowlisted; never accept executable tool schemas from the client.
- Model-generated backtest requests never start without a user click; no tool starts a job directly.
- Require `CurrentUser` for `/llm/chat`; authenticate/owner-scope all created backtest job polls.
- Never enable live/paper orders or give model tools account/broker/secrets access.
- Use existing model-call cap, `BacktestRequest` bounds, risk rules, and job store; add no new dependency.
- Never remove duplicate text by comparing token strings; repeated natural text is valid.

## Review Focus

- Upstream emits content-free final usage choice: usage is retained but not rendered.
- Upstream puts cumulative `message.content` in a stream frame: ignore rather than append as a delta.
- OpenRouter/provider emits tool-call name/arguments in multiple deltas, out of order or incomplete: only validated complete calls become proposals.
- User cancels, is signed out, switches provider/model, or tries a stale proposal: no run is started; no cross-user job/result can be read.
- Provider rejects tools: display a clear error and preserve plain chat behavior; no silent paid fallback/retry.

---

### Task 1: Correct stream parsing and regression tests

**Files:**
- Modify: `quant-app-v1/backend/app/services/llm_providers.py`
- Modify: `quant-app-v1/backend/app/api/v1/llm.py`
- Modify: `quant-app-v1/frontend/src/components/layout/AiHarness.tsx`
- Test: `quant-app-v1/backend/tests/test_phase2_provider_safety.py`

**Interfaces:**
- `stream_chat(...)` yields `{type:"delta", text:str}`, `{type:"tool_call", id:str, name:str, arguments:dict}`, one `{type:"done", usage:dict|None}`, or `{type:"error", message:str}`. Backend providers must receive OpenAI-compatible `tool_calls` in assistant messages, and any tool result must be returned with `role:"tool"`, matching `tool_call_id`, before a follow-up completion request; client-supplied tool-call history remains rejected.
- Text is read exclusively from string `choices[0].delta.content`; do not use `choice.message.content` as an incremental delta.
- Tool deltas are accumulated by provider tool-call index and emitted only after a complete response.

- [ ] Step 1: Add failing mocked SSE tests with regular incremental strings, repeated legitimate fragments, content-free usage frame, cumulative `message.content` snapshot, malformed JSON, indexed fragmented tool arguments, missing finish/tool frames, and upstream error.
- [ ] Step 2: Run `./.venv/bin/python -m pytest -q quant-app-v1/backend/tests/test_phase2_provider_safety.py -k stream`; expected failure on current snapshot fallback/tool event behavior.
- [ ] Step 3: Implement event normalization and finish/tool-call handling; only emit complete valid JSON tool arguments, error on malformed/incomplete calls, preserve usage; update API docs/forwarding.
- [ ] Step 4: Update AI Chat SSE consumer to append only delta text and hold tool proposals separately; usage or tool fragments are never rendered in answer Markdown. Preserve text-fragment order and parse CRLF/SSE data robustly.
- [ ] Step 5: Run focused backend tests and `cd quant-app-v1/frontend && npm run build`; expected pass.

### Task 2: Authenticated allowlisted feature proposal protocol

**Files:**
- Modify: `quant-app-v1/backend/app/api/v1/llm.py`
- Modify: `quant-app-v1/backend/app/api/v1/agentic_lab.py`
- Modify: `quant-app-v1/backend/app/services/job_store.py` only if a minimal owner accessor is needed
- Test: `quant-app-v1/backend/tests/test_agentic_lab.py`
- Modify: `quant-app-v1/backend/tests/test_phase2_provider_safety.py`
- Modify: `quant-app-v1/backend/tests/test_agentic_lab.py`

**Interfaces:**
- `POST /llm/chat` requires `user: CurrentUser`; server attaches only fixed tool definitions on requests that request tool use.
- Tool proposal payloads are validated by strict Pydantic models. `propose_backtest` produces a structured proposal only; no background run/job is created.
- `POST /agentic-lab/backtest` stores `owner_user_id=user.id` in job metadata; `GET /agentic-lab/jobs/{job_id}` requires `CurrentUser` and returns 404 for missing/wrong-owner jobs.

- [ ] Step 1: Add failing tests for anonymous chat 401, fixed tool definitions, unknown tool denied, malformed/oversized args rejected, proposal event without created job, backtest owner polling success/foreign owner 404, and new owner-scoped job metadata.
- [ ] Step 2: Run focused tests; expected failures because chat has no auth/tools and job polling is unscoped.
- [ ] Step 3: Implement authenticated `/llm/chat` and bounded server-owned tool definitions. Limit tools to read-only public context and backtest proposal creation; do not expose portfolio, order, key or broker data.
- [ ] Step 4: Harden backtest job create/poll ownership without breaking public/shared runs via `/agentic-lab/runs`; ensure user is injected server-side and not accepted from request JSON. Audit `/agentic-lab/backtest` authorization; require `CurrentUser` for LLM-backed runs if anonymous invocation is possible, while preserving any established read-only baseline access behavior.
- [ ] Step 5: Run tests for chat auth/proposals and Agentic Lab ownership; expected all pass.

### Task 3: Confirmation UI and chat capability handoff

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/AiHarness.tsx`
- Modify: `quant-app-v1/frontend/src/lib/markdown.tsx` only if internal `/app/...` links need in-app navigation support
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`
- Reuse: `quant-app-v1/frontend/src/components/layout/ModelPicker.tsx` from the Shared Model Picker plan

**Interfaces:**
- Displays a validated `BacktestProposal` card with strategy, symbol, timeframe, provider/model, bars, capital, and max LLM calls.
- Confirm handler posts the proposal as an LLM `BacktestRequest` to `/agentic-lab/backtest`; Cancel clears it without a request.
- Chat response distinguishes an internal feature-link handoff from normal external Markdown URLs.

- [ ] Step 1: If frontend tests are configured, add a failing test proving proposal renders Confirm/Cancel and Cancel causes no request. Otherwise use browser route/mocked fetch verification.
- [ ] Step 2: Implement proposal parsing/validation at the client boundary, explicit confirm/cancel buttons, progress polling (owner-scoped), and a link to Backtests. On auth expiry show sign-in and do not post.
- [ ] Step 3: Add a `get_market_context` result panel or preserve existing attached-context flow; avoid redundant feed requests if a selected context payload already exists. Context tool uses validated request-owned symbol/timeframe and excludes the existing context feeder's `portfolio` section.
- [ ] Step 4: Improve the system policy with exact tools and explain that backtest proposals require confirmation. Add consistent panel layout styles.
- [ ] Step 5: Run frontend build and browser-test confirmed/cancelled/auth-missing flows. Expected Cancel/unauthenticated paths create zero jobs; confirmation starts one job only.

### Task 4: Backtester natural-language strategy launcher

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/Backtester.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx` (pass selected symbol, providers, callbacks if Backtester does not already own this context)
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`
- Reuse: `ModelPicker` from Shared Model Picker plan; `/agentic-lab/backtest` and owner-scoped `/agentic-lab/jobs/{job_id}`.

**Interfaces:**
- New launcher accepts `initialSymbol`, configured providers, and refresh callback; fields are strategy prompt (1–2000 chars), symbol, provider, model, timeframe, bars (40–1000), capital (100–10,000,000), call cap (1–40), and risk defaults.
- Run handler posts `{kind:"llm",prompt,provider,model,symbol,tf,bars,capital,max_llm_calls,risk}` then polls job until terminal; no source-code field or execution.

- [ ] Step 1: Add UI test if runner exists; otherwise capture current browser route and verify default controls in the live app.
- [ ] Step 2: Implement a clear review summary and explicit **Run backtest** action. Disable when required data/auth is missing or request busy; surface job message, progress, error and completion.
- [ ] Step 3: Verify API request clamps match existing `BacktestRequest` and risk normalization; user cannot exceed backend bounds. Add responsive styles and historical-only disclaimer.
- [ ] Step 4: Run `cd quant-app-v1/frontend && npm run build`; use mocked API/browser flow to verify request payload, progress, completion, and unauthenticated behavior.

### Task 5: Integrated verification and security review

**Files:** all Task 1–4 changes.

- [ ] Step 1: Run focused backend tests for stream/tool/auth/ownership, plus `test_agentic_lab.py` and provider safety suite; expected pass.
- [ ] Step 2: Run full relevant backend tests; expected suite green.
- [ ] Step 3: Run frontend production build, `git diff --check`, and inspect every changed hunk; expected build succeeds and no whitespace errors remain.
- [ ] Step 4: Browser verify Chat receives a single streamed answer; tools result only in a proposal; Cancel/confirm behavior; free-only selection; Backtester strategy run/poll flow.
- [ ] Step 5: Review security boundaries for public context only, owner-scoped job polling, and auth; fix any finding with a regression test. Record remaining external provider verification limits; expected no unmitigated high-severity finding.

---

This plan depends on the Shared Model Picker plan's exported `ModelPicker` component. Implement and approve that plan first; preserve its contract as `ModelPicker({providerId, configured, value, onChange, className?})` and extend only through backward-compatible optional props if necessary.
