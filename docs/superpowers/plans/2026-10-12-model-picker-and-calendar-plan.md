# Shared Model Picker and Yahoo Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every current LLM model selection use catalogue metadata and add best-effort Yahoo Finance economic events to Calendar.

**Architecture:** Extract an accessible reusable picker backed by the existing authenticated `/llm/providers/{provider}/models` API and integrate it in AI Chat, Agentic Lab and Provider Settings. Implement Yahoo event normalization in the existing Yahoo provider and include it in the existing explicit/automatic calendar source flow.

**Tech Stack:** React 18, TypeScript, Vite, FastAPI, Pydantic, yfinance, pandas, pytest.

**Spec:** [../specs/2026-10-12-model-chat-backtest-calendar-design.md](../specs/2026-10-12-model-chat-backtest-calendar-design.md)

## Global Constraints

- Free-only filtering excludes models unless the catalogue explicitly sets `is_free: true`.
- Existing model catalogue route and response shape remain unchanged.
- Yahoo source is best-effort and provenance-labelled; skip rows without a parseable timestamp.
- Keep historical/paper-only execution boundaries unchanged.
- Add no new UI or Python dependencies; update root `yfinance` constraint to `>=1.0,<2.0`.

## Review Focus

- Catalogue request fails/empty: retry/error and manual-entry behavior is safe; free-only never admits unknown models.
- Provider changes while free-only is active: selection is eligible for the new provider or cleared.
- Yahoo returns NaN, missing values, unknown countries, or date-only times: malformed values are not converted into invented data.
- Yahoo calendar raises due to missing `Calendars`, network, or API response: source status is unavailable and automatic merge continues.
- Provider Settings default-model dropdown preserves IDs and only filters explicitly-free IDs.

---

### Task 1: Shared model picker

**Files:**
- Create: `quant-app-v1/frontend/src/components/layout/ModelPicker.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/AiHarness.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/LlmProviderSettings.tsx`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`
- Test: `quant-app-v1/frontend/src/components/layout/ModelPicker.test.tsx` only if a frontend test runner is already installed; otherwise browser-verify.

**Interfaces:**
- `ModelPicker({providerId, configured, value, onChange, className?})`; owns catalogue fetch/retry and free-only toggle, renders status/empty states, and permits manual model entry only if filtering is disabled and no catalogue choices are available.
- Uses the existing authenticated catalogue route, existing `gateway_auth_token`, and explicit `is_free === true` only.

- [ ] Step 1: Inspect frontend test dependencies/config. If a runner exists, add a failing test that excludes `is_free:false` and unknown entries, retains explicit free, and clears an invalid selection.
- [ ] Step 2: Run the focused test and observe failure because `ModelPicker` is not yet exported. If no test runner is configured, record that and do not add one solely for this feature.
- [ ] Step 3: Implement `ModelPicker`; replace AI Chat's inline catalogue picker; use it for Agentic Lab create-agent, research generation, iterative research; use it for Provider Settings default model and preserve provider fetch/status feedback.
- [ ] Step 4: Add compact responsive styles; run `cd quant-app-v1/frontend && npm run build`; expected `tsc` and Vite build succeed.
- [ ] Step 5: Browser verify AI Chat, Agentic Lab and Provider Settings with free/paid/unknown catalogue fixtures; failure fallback remains unfiltered only.

### Task 2: Yahoo Finance calendar source

**Files:**
- Modify: `requirements.txt`
- Modify: `quant-app-v1/backend/app/providers/yahoo_provider.py`
- Modify: `quant-app-v1/backend/app/api/v1/news.py`
- Modify: `quant-app-v1/frontend/src/components/layout/CalendarView.tsx` only if needed for source labeling/status.
- Modify: `quant-app-v1/backend/tests/test_calendar_api_providers.py`
- Modify: `quant-app-v1/backend/tests/test_calendar_sources.py`
- Test: existing Yahoo provider tests under `quant-app-v1/backend/tests/`.

**Interfaces:**
- `YahooFinanceProvider.calendar(limit: int = 5) -> list[EconomicEvent]` calls synchronous `yf.Calendars().get_economic_events_calendar(limit=min(limit,100))` via `asyncio.to_thread`.
- A pure row normalizer maps the current yfinance labels `Event` (index), `Event Time`, `Region`, `Actual`, `Expected`, `Last`, `Revised` into canonical records with stable IDs and provider version. Country names/codes are normalized through an explicit mapping, with currency inferred only from a known country mapping; otherwise use the empty currency and country string rather than guess.

- [ ] Step 1: Add failing tests for valid UTC rows, NaN numeric fields, stable IDs, missing/date-only timestamps, empty frames, missing Calendars API, and upstream exception; add source list + merge + fallback tests.
- [ ] Step 2: Run the focused tests; expected failures because Yahoo has no calendar method and is absent from `_CALENDAR_CHAIN`.
- [ ] Step 3: Implement row normalization against the verified yfinance column labels `Event`, `Event Time`, `Region`, `Actual`, `Expected`, `Last`, `Revised`; use finite numbers only, do not invent schedule times, skip malformed rows, use deterministic IDs from event/time/country, and raise `ProviderUnavailableError` for missing API/network/data errors.
- [ ] Step 4: Add Yahoo to `_CALENDAR_CHAIN` and `_CALENDAR_SOURCE_DETAILS` in `news.py`; strict named-source behavior and `auto` merge/fallback remain unchanged. Update root `requirements.txt` to `yfinance>=1.0,<2.0` and any Calendar source helper text to identify Yahoo as best effort.
- [ ] Step 5: Run `./.venv/bin/python -m pytest -q quant-app-v1/backend/tests/test_calendar_api_providers.py quant-app-v1/backend/tests/test_calendar_sources.py` plus existing Yahoo tests; expected all pass. Run `git diff --check`; inspect the changed hunks.

### Task 3: Integrated verification

- [ ] Step 1: Run frontend production build and relevant backend provider/calendar tests; expected both pass.
- [ ] Step 2: Browser verify each model-choice control, failure/free-only states, and Calendar's explicit Yahoo option/status; expected provider choices are consistent and unknown metadata remains excluded.
- [ ] Step 3: Review diffs and run `git diff --check`; expected no whitespace errors, and any defect fix has a regression test.

---

This plan shares the exported ModelPicker component with [the Chat and Backtester plan](2026-10-12-chat-tools-backtester-plan.md); the second plan must consume the same component rather than implement a second picker.

