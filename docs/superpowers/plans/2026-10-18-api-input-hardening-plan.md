# API and Hostile-Input Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Execute task-by-task only after the user approves this plan. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close authentication, credential-destination, exception-disclosure, installer, and unbounded-input risks without weakening paper-only execution or introducing a new dependency/service.

**Architecture:** First ship the unauthenticated private-route stopgap, Auth0 audience enforcement, AllTick redaction, current-store provider destination/operator/redirect restrictions, and default-disabled installer; these are independent of the large identity and BYOK migrations. Then build shared foundations/ownership, with BYOK-only service integration gated on a separately approved Supabase migration. Bound candles and harden Markdown/chat after their explicitly listed dependencies, with fixed failure contracts and deterministic limits.

**Tech Stack:** Python 3.11+, FastAPI, python-jose, httpx/aiohttp, pandas, pytest/httpx; React 18, TypeScript, Vite, Playwright. Existing libraries only.

**Spec:** [API and Hostile-Input Hardening](../specs/2026-10-18-api-input-hardening-design.md)

## Global Constraints

- Auth0 requires nonempty `AUTH0_AUDIENCE` whenever enabled; verification always checks audience, issuer, RS256 signature, expiry and not-before. Local HS256 behavior stays unchanged.
- Provider settings and keys use the owner-scoped BYOK interfaces from the ownership plan; no other-owner key or environment/shared key fallback in BYOK mode. User BYOK does not require operator status.
- For immutable catalogue URLs, differing `base_url` is rejected and prior persisted overrides are ignored. No credentials are forwarded across redirects. Custom origins require validation, DNS/SSRF policy, and explicit key re-entry when origin changes.
- Public provider errors are fixed safe messages with status metadata only; never return/log URL, API key, query, headers, response body, or raw exception text.
- Kronos runtime installer is disabled by default. If later explicitly enabled, it is operator-gated, managed-path-only, argv subprocess without shell, pinned source/ref, no pip self-upgrade, and sanitized bounded status.
- Kronos shared converter maximum is exactly 2,000 bars; enforce at UI request construction, HTTP model, and shared service before DataFrame construction. The frontend sends `bars.slice(-2000)` and a UI test proves no request exceeds 2,000. Allowed timestamp and OHLCV/amount aliases only; discard unknown metadata and reject conflicting aliases/invalid rows.
- Chat uses one Unicode/UTF-16 count contract for frontend and backend; reject oversize inbound request before provider connection; cap aggregate output and cancel upstream; never persist an incomplete stream as a successful completed assistant turn.
- No live/broker path is added or enabled. No new dependency, broker call, deploy, commit, or push.

## Review Focus

- `AUTH0_DOMAIN` set with empty/missing/whitespace audience must fail closed while local HS256 works unchanged.
- AllTick fake transport error containing a token-bearing URL must not leak through exception, logs, quote response, or provenance.
- Previously stored immutable provider URL and a custom URL origin change cannot cause an old/env credential to be sent to the new origin; redirects cannot forward auth headers.
- Oversize/malformed candle bodies are rejected before DataFrame allocation on both HTTP and local-server forecasting paths; accepted 2,000-row input still preserves canonical candles.
- Hostile nested/unmatched Markdown, long individual messages, aggregate context and streamed output hit deterministic caps without parser hangs, overrun, unsafe schemes or false successful persistence.

---

## File Map

- Modify `quant-app-v1/backend/app/auth.py`, `app/config.py`; Test `tests/test_auth0.py` and config subprocess tests.
- Modify `app/providers/alltick_provider.py`, `app/api/v1/news.py`, provenance/log handling; Test `tests/test_phase2_provider_safety.py` plus quote API tests.
- Modify `app/services/llm_providers.py`, `app/api/v1/llm.py`, and owner-scoped key storage from ownership plan; Test `tests/test_provider_ownership.py`, `tests/test_phase2_provider_safety.py`.
- Modify `app/api/v1/forecast.py`, `app/services/kronos_installer.py`, `app/services/kronos_service.py`, and `frontend/src/components/features/KronosForecast.tsx`; Test `tests/test_kronos_hardening.py` and frontend forecast E2E.
- Modify `frontend/src/lib/markdown.tsx`, `frontend/src/components/layout/AiHarness.tsx`, `app/api/v1/llm.py`; Test frontend `markdown.test.tsx` (existing test framework only if present; otherwise add focused Playwright spec) and backend chat tests.
- Modify `app/api/v1/llm.py`/service stream adapter for caps and cancellation; test fake provider iterator, disconnect, and tool argument bounds.

## Task 0: Close unauthenticated private route exposure (ship before ownership migration)

**Schedule:** This task ships with Tasks 1, 2, and 4 as the first security slice, before Foundations Task 0 and the identity migration. Auth0 audience, AllTick, and installer changes are independent of `principal_id` mapping.

**Files:** Modify `app/api/v1/portfolio.py`, `app/api/v1/strategies.py`, `app/api/v1/risk.py`, `app/api/v1/journal.py`, `app/api/v1/ai_trading.py`, `app/api/v1/settings.py`, and `app/api/v1/vault.py` as necessary; Test: `tests/test_exposure_stopgap.py`.

**Interfaces:**
- Add mandatory `user: CurrentUser` to every private handler in portfolio, strategy, risk, journal, and AI-trading routers; router-level `OptionalUser` does not authorize. All mutation handlers must depend directly on verified `get_current_user` before performing any DB/provider side effect. Where an authenticated request can still touch another account's shared data, return stable 503 unavailable until its ownership task ships rather than provide authenticated-but-global access.
- Extend the verified token result minimally to preserve `issuer` and `subject` without yet changing `CurrentUser.id` (it remains the verified raw subject in this stopgap). Implement the same strict `GATEWAY_OPERATOR_USER_IDS` JSON array of exact `{issuer,subject}` pairs in the current auth dependency, using only verified issuer values; missing/empty/malformed configuration denies. Ownership Task 1 later maps the same identity to opaque principal but does not change this allowlist format.
- Global market-data provider settings and global risk-policy/halt mutations require strict operator allowlist immediately; if an endpoint cannot enforce the check safely in this slice, return stable 503 rather than expose it.
- Journal `/sync-live` always returns stable 503 until owner-scoped provenance/reconciliation is approved. Authenticated global journal CRUD can be hidden behind 503 until Ownership Task 3 if safe owner scoping cannot be achieved in this slice.
- Preserve `CurrentUser` identity interface used today; do not introduce opaque principal assumptions before Foundations and Ownership Task 1.

- [ ] Inventory every private route in the five listed routers and test anonymous read/mutation requests; assert 401 before database, quote/provider, or mutation calls.
- [ ] Test global risk/provider configuration operations return stable 503 before an operator identity gate exists; test journal live sync returns 503.
- [ ] Add mandatory `CurrentUser` or stable 503 to each private handler; enforce strict issuer/subject operator check on global risk/provider settings; no database schema/ownership changes in this stopgap.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_exposure_stopgap.py` and relevant existing route/auth tests; assert zero side effects for anonymous requests and non-operator 403 on global config routes.

## First-slice execution order

1. Task 0 exposure stopgap.
2. Task 1 Auth0 audience and Task 2 AllTick exception/log redaction.
3. Task 3 immutable URL rejection, current-store operator check, and redirect disable against the existing store (no BYOK RPC required).
4. Task 4 disable Kronos installer by default (no identity dependency while disabled).
5. Foundations Task 0, then Ownership Task 1. Run Hardening Task 5 (2,000 bar service cap; UI bound can ship with slice) in parallel only if no owner identity dependency.
6. Ownership Tasks 2/3; journal may proceed independently. For BYOK, inspect deployed RPC definitions via approved read-only access, obtain separate migration approval, then apply/test the migration and deploy matching backend before enabling. Until then, shared-key LLM chat is unavailable, the old operator key stays quarantined, and UI clearly says “Add your key”/migration unavailable.
7. Ownership Task 4 and Risk Tasks 1–7 ship as one coordinated Trade release; until then Trade/order entry is explicitly unavailable in the UI and server.
8. Ownership Tasks 5/6; remaining Hardening Task 3 BYOK re-verification against migrated owner store, then Hardening Tasks 5–7 after dependencies. No shared-key fallback.



## Task 1: Require and verify Auth0 audience

**Files:** Modify `app/auth.py`, `app/config.py` if needed; Test `tests/test_auth0.py`.

**Interfaces:**
- `validate_auth_configuration(auth0_domain: str, audience: str | None) -> None` raises a sanitized `RuntimeError` if domain exists and audience is empty; run during auth config initialization.
- `_decode_auth0_token` always passes `audience=AUTH0_AUDIENCE` and never sets `verify_aud=False`; an absent audience rejects at config/decode boundary.

- [ ] Add `test_auth0_missing_audience_fails_closed`, `test_auth0_empty_audience_fails_closed`, `test_auth0_correct_wrong_and_missing_claim_audience`, and retain `test_local_token_works_with_auth0_enabled`.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_auth0.py`; confirm new missing-audience expectations fail.
- [ ] Implement sanitized config validation and unconditional audience verification without changing local token decoder.
- [ ] Rerun `tests/test_auth0.py` and `tests/test_supabase_auth.py`; all pass.

## Task 2: Redact provider failures end-to-end

**Files:** Modify `app/providers/alltick_provider.py`, `app/api/v1/news.py`, related provider logging/provenance; Test `tests/test_phase2_provider_safety.py` and quote API tests.

**Interfaces:**
- Adapter raises `ProviderUnavailableError('AllTick request failed')` with optional numeric `status_code` metadata only; do not attach or log raw request exception/URL/query/body. Silence or redact `httpx` request/response logger namespaces for tokenized AllTick URLs; captured logger tests must verify no credential/query escapes.
- Public quote error contract is fixed `{error: 'Quote provider unavailable', provider: <safe canonical name>, status_code: <int|null>}`. Provenance failure uses same safe failure code/message and no raw exception property.

- [ ] Add fake HTTP 401 and timeout tests with `ALLTICK_API_KEY=fake-secret` in request URL; assert exception string, caplog (including `httpx` logger), response JSON and provenance contain no fake token, full URL, query, or response body.
- [ ] Run focused tests red.
- [ ] Implement exception translation and fixed API serialization; audit AllTick logs for raw exception formatting.
- [ ] Rerun provider and quote tests; retain status code only when numeric and safe.

## Task 3: Harden provider destination and credential boundary on the current store

**Sequencing:** This is the independent stopgap and ships before Ownership Task 1/BYOK migration. Do not await or assume owner-scoped Supabase RPCs for these protections.

**Files:** Modify `app/services/llm_providers.py`, `app/providers/registry.py`, `app/api/v1/llm.py`, `app/api/v1/settings.py`, and any shared httpx construction in provider adapters; Test `tests/test_provider_ownership.py`, `tests/test_phase2_provider_safety.py`, and `tests/test_exposure_stopgap.py`.

**Later BYOK migration:** After ownership Task 2's separate Supabase migration approval, application, test, and backend deployment, rerun the same destination/key-binding suite against the owner-scoped key store before BYOK is enabled.

**Interfaces:**
- Current-store phase preserves existing public function signatures only temporarily; it enforces canonical catalog destination in existing service and prevents sending any credential unless destination's normalized origin matches the credential's stored approved origin. No new shared-key fallback is allowed. After migration, change to the exact owner-scoped signatures from Ownership Task 2 and rerun these tests.
- Immutable catalogue entry ignores any historical override at resolution, while writes differing from catalogue URL return stable validation error. The current shared key store's global `/settings/providers` routes are operator-only now; key/value reads, tests and status are not left public/private-by-login only.
- Reject immutable catalogue URL changes and ignore any historical persisted override for non-editable providers, including on reads and tests. Treat existing market-data `/settings/providers` administration as global and require strict `require_operator` on list/status/test/store/delete now; if that dependency is not yet available, return stable 503 rather than exposing global key state.
- Custom URL validator rejects malformed/unsupported schemes and URL userinfo; block loopback/private/link-local/metadata destinations except explicit local custom config. Store credential's normalized approved origin. Origin change without freshly provided nonempty key deletes/invalidates the old origin binding and rejects network access.
- Disable redirects on all authenticated provider HTTP clients. With existing httpx resolver behavior, do not claim DNS pinning: validate DNS answers immediately before opening the connection and document the remaining DNS-rebinding TOCTOU race. If no safe resolver pinning path is available with the installed httpx transport, keep this residual race explicit and retain private/metadata address blocks plus redirects disabled. Never use shared environment key as BYOK fallback.

- [ ] Write tests for immutable URL rejection/legacy override ignored, route operator/503 gate, URL userinfo/scheme/private destinations, DNS recheck documented race, explicit key re-entry on origin change, and redirects disabled with a fake local redirect endpoint asserting no Authorization is forwarded.
- [ ] Run tests red; inspect current key store, registry, provider HTTP clients, and catalog metadata.
- [ ] Implement current-store protections without changing storage ownership; do not forward keys to a changed origin. Add a code comment/security doc for the residual DNS validation-to-connect race.
- [ ] Rerun focused tests; after BYOK migration deploy, repeat the same suite for cross-owner key isolation and shared/env fallback denial.

## Task 4: Disable unsafe runtime Kronos installation and sanitize status

**Files:** Modify `app/api/v1/forecast.py`, `app/services/kronos_installer.py`; Test `tests/test_kronos_hardening.py`.

**Interfaces:**
- `KRONOS_RUNTIME_INSTALL_ENABLED` defaults false. POST install returns stable 503 unavailable while false, regardless of force/path; no principal/identity implementation is needed to ship the disabled state. Any future enabling requires completed Ownership Task 1's strict `require_operator` and a separate deploy-time choice.
- Model weight loading uses `KronosTokenizer.from_pretrained` and `Kronos.from_pretrained`; pin each Hugging Face model to a full immutable commit revision, separately pin the Kronos source checkout/ref, and require a checksum manifest for local weights. Approved Hub models use `model.safetensors`; if `.bin` fallback is kept, only `weights_only=True` plus checksum-verified artifacts are permitted. Do not dynamically execute model-repository Python or use floating `main` revisions.
- Prefer deployment-installed dependency. If retaining optional operator install, use `subprocess.Popen([executable, ...], shell=False)`, fixed allowlisted repository URL/ref, fixed managed checkout directory; reject caller path/force mutation. No `pip install --upgrade pip`.
- `status()` exposes only booleans, enum-like state, bounded last N lines (max 40 × 500 characters), fixed timestamps/status; omit `repo_path`, host path and raw environment data.

- [ ] Add anonymous/disabled/ordinary-user/allowlisted-operator tests, `force`/path ignored or rejected tests, and static assertions for no `shell=True`, pip self-upgrade or caller path interpolation.
- [ ] Run tests red; inspect frontend installer expectation and provide stable unavailable UI/API behavior.
- [ ] Implement default-disabled guard and sanitization; if no deployment use case requires optional install, remove execution route path and preserve status as stable disabled.
- [ ] Rerun tests; prove status contains no filesystem path and response logs are size-capped.

## Task 5: Bound and validate Kronos candle conversion

**Files:** Modify `app/services/kronos_service.py`, `app/api/v1/forecast.py`; Test `tests/test_kronos_hardening.py`.

**Interfaces:**
- Define `MAX_KRONOS_BARS = 2000` and allow keys exactly `time`, `timestamp`, `datetime`, `date`, `open`, `high`, `low`, `close`, `volume`, `amount`, case-insensitive; OHLC required, timestamp required by current contract unless existing canonical chart path explicitly synthesizes dates. Frontend sends `bars.slice(-2000)` before JSON serialization and UI test asserts no request exceeds limit.
- `bars_to_kronos_frame(bars: list[Mapping[str, Any]]) -> tuple[pd.DataFrame, pd.Series]` validates list and count before pandas, projects each mapping to allowlisted keys, discards unrelated vendor metadata, rejects alias collisions, invalid/overflow numeric values and malformed timestamps before creating a DataFrame.
- HTTP request model rejects non-list/object shape and `len(bars)>2000`; shared converter repeats bounds for local/server callers before allocation.

- [ ] Add tests for 0, 1, 2,000, 2,001 bars; non-list/non-mapping; unknown metadata discard; alias conflict; numeric overflow/nonfinite; malformed/missing timestamp; shared local-server converter path; assert DataFrame constructor is not called for 2,001. Add loader tests for immutable revisions, local checksum manifest, and no unsafe pickle fallback.
- [ ] Add frontend test sending 2,001+ visible bars and assert request payload contains at most 2,000 rows, preserving the most recent bars; verify the actual forecast UI/transport never serializes more than 2,000. Add backend tests for all request paths.
- [ ] Run tests red and verify current service materializes first.
- [ ] Implement frontend slice, pre-allocation validation/projector and bounded API model.
- [ ] Rerun tests and any existing Kronos tests; verify valid canonical bars unchanged and UI/backend both enforce the same limit.

## Task 6: Linear Markdown tokenizer and render cap

**Files:** Modify `frontend/src/lib/markdown.tsx`; Test `frontend/e2e/markdown-hardening.spec.ts` or existing frontend unit test setup after confirming available tools.

**Interfaces:**
- Add `MAX_MARKDOWN_CHARS = 20000` counted in JavaScript UTF-16 code units. `Markdown` handles content longer than cap as escaped React plain text with a stable visible truncation marker, never invokes block/inline parsers on it.
- Replace regex rescanning loop with a left-to-right tokenizer over the original string, guaranteed to advance by at least one code unit; preserve current supported inline forms and safe link scheme set `http:`, `https:`, `/`, `#`, `mailto:`.

- [ ] Add cases for unmatched/nested brackets, delimiter nesting, Unicode surrogate pairs, unsafe `javascript:` URL, exact cap and cap+1 plain fallback. Add a deterministic operation-count test or bounded tokenizer step count, not a wall-clock-only assertion.
- [ ] Run the test red; if no unit runner exists, use the repository's Playwright E2E without adding a framework.
- [ ] Implement tokenizer and fallback with no new package.
- [ ] Run markdown test and `npm run build`; inspect DOM text/hrefs through Playwright.

## Task 7: Aggregate inbound/output chat limits, cancellation, and tool bounds

**Files:** Modify `app/api/v1/llm.py`, `app/services/llm_providers.py`, `frontend/src/components/layout/AiHarness.tsx`; Test backend chat tests, `tests/test_phase2_provider_safety.py`, frontend E2E.

**Interfaces:**
- Contract counts UTF-16 code units across serialized message `content`, tool call names/IDs/arguments and context; `MAX_CHAT_INPUT_CHARS = 200000` total before opening provider connection. Per-owner concurrent chat/stream cap is exactly 2, enforced before provider connection with an atomic token/slot and released in a `finally` path, including cancellation/disconnect. Per-message 100,000 and max 80 messages remain existing caps. Bound each nested tool argument to 16,000 serialized characters, max 4 calls and one tool cycle.
- `MAX_CHAT_OUTPUT_CHARS = 100000` aggregate assistant text. Server stream tracks cumulative delta code units, emits one fixed `chat_output_limit` terminal error and cancels provider async iterator/HTTP response before overrun; client disconnect cancels upstream. Client independently stops reading/appending at same cap.
- A response over limit is error/incomplete, never emits `done` and never persists as completed assistant response. Partial text may remain visibly marked interrupted but must not be treated as successful session content.

- [ ] Add exact boundary tests for 200,000/200,001 input, tool payload depth/serialized cap/call count, output 100,000/100,001 across chunks/tool rounds, client disconnect cancellation and no successful persistence.
- [ ] Run backend and frontend focused tests red with fake streaming provider; no real API key/request.
- [ ] Implement preconnection aggregate validation, output accounting, async cancellation/close and matching UI cap/aborted state.
- [ ] Rerun backend tests, frontend Playwright and `npm run build`; assert output remains at/below cap and terminal semantics truthful.

## Task 8: Final hardening gate

- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_auth0.py tests/test_supabase_auth.py tests/test_phase2_provider_safety.py tests/test_provider_ownership.py tests/test_kronos_hardening.py`.
- [ ] Run `npm run build` and focused Playwright markdown/chat cases if frontend touched.
- [ ] Verify fake credentials/URLs absent in API bodies, logs and provenance; inspect redirect behavior with local test server and no third-party endpoint.
- [ ] Run `git diff --check`, read-only secret-pattern scan with matching lines suppressed, and record named results/blockers in plan ledger. No provider external calls with user credentials.

## Self-review / Dependency Gates

- Dependency sequence: Task 0 exposure stopgap and independent Tasks 1, 2, 3 (current-store-only protections), and 4 ship before shared Foundations Task 0 and Ownership Task 1. Task 3's immutable-URL rejection, strict operator gate for global current-store settings, approved-origin binding, and no-redirect policy do not await BYOK migration; DNS validation is immediately before connect and residual rebinding race remains documented unless a verified httpx pinning path exists. Auth0/AllTick/installer controls also ship first.
- Shared Foundations Task 0 is an explicit owned task in the ownership plan: real-connection SQLite transaction/concurrency helper, injectable UTC clock, versioned additive migration runner, append-only audit table and atomicity tests. Ownership Task 1 depends on it.
- After Ownership Task 1, Ownership Tasks 2 and 3 may proceed; journal work is independent. BYOK enablement is blocked until deployed RPC review, separate migration approval, application, contract tests and matching backend deployment. Until then LLM chat is unavailable to all users, the old operator shared key is quarantined with no fallback, and the UI shows “Add your key” plus migration/service-unavailable state.
- Ownership Task 4 and Risk Tasks 1–7 must ship together as one coordinated Trade release; until then UI and backend order paths remain explicitly unavailable. Ownership Tasks 5/6 and remaining Hardening Tasks 3, 5, 6, and 7 proceed only after their named dependencies.
- Hardening Task 5 enforces at most 2,000 bars in both the UI request (`bars.slice(-2000)`) and shared backend conversion path; task tests assert no request exceeds the cap. Verify Kronos weights use immutable revisions/safetensors or checksum-verified weights-only loading. Hardening Task 7 enforces per-owner concurrent streams cap 2 with atomic release on disconnect/error/cancel.
- All three plans use `GATEWAY_OPERATOR_USER_IDS` as strict JSON array of exact verified `{issuer,subject}` objects, never principal IDs or raw `user.id`. Ownership Task 7 performs repository-wide raw-subject/opaque-ID audit.


- Task 4 runtime Kronos installer remains disabled by default and can ship before identity work; if a future operator-enabled mode is introduced, it requires Ownership Task 1's operator dependency and separate deployment decision.
- Task 5 enforces the same 2,000-row cap at frontend, HTTP, and shared converter. Frontend truncates to the newest 2,000; tests assert UI request shape. If UI contract review finds canonical historical bars without timestamps, retain current deterministic synthetic index behavior only for those canonical internal bars and explicitly test distinction from caller-supplied missing timestamps.
- Model source and model weights are separate trust inputs. Pin source/ref and Hugging Face revisions independently; use safetensors; if legacy `.bin` is retained, require weights-only loading and checksum verification. No unrestricted pickle.
- Per-user stream concurrency cap is 2; release the slot on normal completion, provider error, disconnect/cancel, or generator close. A process-local cap may be used for single-instance local mode only; multi-worker production must use a shared atomic cap or return unavailable when such enforcement is not configured. Test simultaneous streams at 2 and 3, plus disconnect slot release.
- Tasks 6–7 use exact UTF-16 code-unit counting on both browser and Python (`len(text.encode('utf-16-le')) // 2`, reject invalid surrogate encoding safely) to avoid mismatched budgets. Tool JSON serialization uses compact UTF-8 JSON and counts encoded contract consistently; lock this with a shared fixture. Enforce a per-owner concurrent chat/stream cap of 2 open requests with atomic acquire/release and cancellation on disconnect; request-rate limits remain separately bounded.
- No service budget/rate/concurrency system is added for operator-managed shared keys because current provider policy is BYOK. Per-user API/provider request throttles remain defense-in-depth and must use verified owner IDs. Enforce per-owner chat concurrency cap of 2 active SSE streams using atomic acquire/release; cancellation/disconnect must release the slot.
- Broker-fill ingestion/reconciliation remains separately gated; no evidence or broker access is part of this plan.
