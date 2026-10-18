# Account Ownership and Private-Data Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Execute task-by-task only after the user approves this plan. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Scope secrets, provider settings, journal, strategies, AI-trading loops, simulated portfolios, WebSockets, and chat sessions to a verified issuer-qualified principal without exposing legacy ownerless data.

**Architecture:** Add additive SQLite ownership mapping and transaction primitives, derive a stable opaque Gateway principal from verified issuer plus subject, then thread that principal through each repository/service and route. Keep legacy rows ownerless and inaccessible. Provider catalogue remains public metadata while provider credentials/config become per-principal BYOK; paper risk policy and operator administration remain separate concerns.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest/httpx, React 18, TypeScript, Vite, Playwright; existing Fernet and provider key-store code. No new dependency.

**Spec:** [Account Ownership and Private-Data Isolation](../specs/2026-10-18-account-ownership-isolation-design.md)

## Global Constraints

- Principal identity is `(verified issuer, verified subject)`; never merge on email. Local HS256 issuer is exactly `gateway:local`; Auth0 uses the verified tenant issuer; Supabase uses the issuer returned in verified introspection claims, checked against the configured project GoTrue issuer (do not derive identity only from the request's unverified `iss`).
- Operator allowlist `GATEWAY_OPERATOR_USER_IDS` is a JSON array of objects with exact `issuer` and `subject` strings, compared with verified token identity; absent, empty, malformed, or duplicate/ambiguous entries deny privileged changes. This single format is used across all plans; it is not a list of opaque `principal_id` values.
- Existing ownerless records remain `NULL`, quarantined, and inaccessible; never auto-assign to the first user.
- New private rows use the stable opaque `principal_id`; request payloads cannot set or transfer ownership. Foreign and ownerless record IDs return 404.
- Vault and BYOK secrets remain Fernet-encrypted, files remain atomically written with mode 0600, and raw keys/cipher/decrypt errors never appear in API responses or logs.
- BYOK is user-owned and does not require operator status. No fallback to another user's key or shared environment key in BYOK mode. Shared operator-key budgets are deferred.
- Execution remains paper-only; `/live` remains unmounted and broker placement remains disabled. No broker requests, orders, deploy, commit, or push.
- Verification uses `PYTHONPATH=. ./.venv/bin/pytest` from `quant-app-v1/backend`; frontend checks run in `quant-app-v1/frontend`.

## Review Focus

- Same `sub` from local, Auth0, and Supabase must resolve to three distinct principals; expired/unverified tokens must not resolve.
- Opaque principal migration must not break local login/profile/preferences: map local profile row IDs through `auth_identities` while keeping `/auth/me` and local refresh able to recover the raw provider subject for issuing a new signed token; include registration/login/me/preferences regression coverage.
- Legacy rows with NULL ownership must stay hidden even on same-name/same-ID lookup; migrations do not infer owners from emails.
- Concurrent user creation and first-time identity mapping must yield exactly one stable principal without attaching another identity.
- Provider custom-origin change cannot reuse a stored key; global environment keys cannot silently satisfy BYOK configuration.
- User changes/logout during chat streaming must abort the stream and prevent an old account's transcript/proposal/context from appearing or being persisted under the new identity.

---

## File Map

- Modify `quant-app-v1/backend/app/auth.py`: preserve verified issuer/subject in `TokenData`; `CurrentUser.id` becomes opaque `principal_id`, and immutable `CurrentUser.issuer`/`.subject` remain available to audit and local token refresh.
- Modify `quant-app-v1/backend/app/services/database.py`: additive `auth_identities` and `principal_profiles` tables, preferences owner migration, resource owner columns/indexes, owner-scoped query helpers, and use the transaction/clock/migration/audit contracts delivered by Foundations Task 0. Keep `users.id` as the local password-auth subject; link local identity rows to that ID instead of replacing it with `principal_id`. Existing ambiguous foreign-provider rows remain quarantined.
- Modify `quant-app-v1/backend/app/services/secrets_vault.py` and `app/api/v1/vault.py`: owner-keyed encrypted namespace and mandatory owner argument.
- Modify `quant-app-v1/backend/app/services/llm_providers.py`, `app/services/key_store.py`, and `app/api/v1/llm.py`: owner-scoped LLM settings/keys only, as selected for BYOK; public catalogue metadata stays global. Do not migrate the separate market-data provider key registry in this plan. Treat every existing global `/settings/providers` route—including status/test reads—as operator-only administration; missing/invalid operator configuration denies access, and ordinary users get no access to those global credentials or settings.
- Add a versioned migration under `supabase/migrations/` for owner-scoped durable LLM BYOK storage with owner authorization/RLS, and update `supabase/schema.sql` only as the repository's documented schema snapshot requires. The deployed `gw_list_provider_keys`, `gw_upsert_provider_key`, and `gw_delete_provider_key` definitions are not present in the tracked source found during plan review; inspect the deployment through an approved read-only path before migration, and no remote migration is authorized by this plan.
- Modify `app/services/journal_log.py`, `app/api/v1/journal.py`, `app/services/ai_trading.py`: owner and trusted source provenance on journal entries/fill logs and owner-filtered memory.
- Modify `app/api/v1/strategies.py` and strategy schema helpers: owner-filtered CRUD, versions, and backtests; preserve existing canonical StrategySpec hash contract.
- Modify `app/services/database.py`, `app/api/v1/portfolio.py`, `app/services/paper_portfolio.py`, `app/services/fill_simulator.py`: one portfolio per owner, ownership-checked repository operations, remove shared defaults, and owner-aware simulation. All order acceptance must remain disabled or return a stable unavailable response until the separate risk phase supplies its admitted service contract; no authenticated-but-unowned interim acceptance. Until that risk contract is implemented, existing order-submit routes must fail closed rather than report accepted orders.
- Modify `app/services/ai_trading.py` and `app/api/v1/ai_trading.py`: persisted per-owner config/log/state and isolated loop lifecycle; do not resume global legacy loop.
- Modify private route modules and `app/api/main.py`: require `CurrentUser` directly on every private handler (router-level `get_current_user_optional` only rejects invalid tokens and is not authorization), add explicit `require_operator` for global configuration routes, preserve public catalogue/news routes, and keep live router unmounted. `GET/PUT/DELETE /llm/providers` settings, model fetch/test, chat and context must all pass the verified owner ID; context portfolio section derives that owner's portfolio. Global market-data `/settings/providers` administration is separately `require_operator`-gated on all read and mutation routes. This plan's Task 1 is identity-independent only after the separate exposure stopgap has already protected private route mutations.
- Modify `quant-app-v1/frontend/src/context/AuthContext.tsx`, `components/layout/AiHarness.tsx`, and chat tests: react to identity transitions and namespace chat sessions.
- Tests: extend `tests/test_auth0.py`, `tests/test_supabase_auth.py`, `tests/test_auth_preferences.py`, `tests/test_journal_and_vault.py`, strategy and paper portfolio tests; add `tests/test_account_ownership.py`, `tests/test_provider_ownership.py`, `tests/test_ai_trading_ownership.py`, and focused frontend Playwright coverage.

---

## Task 0: Shared transaction, clock, migration, and audit foundations

**Files:** Modify `quant-app-v1/backend/app/services/database.py`; create `app/services/clock.py` only if the database module's existing conventions make a separate module clearer. Test: `tests/test_database_foundations.py`.

**Interfaces:**
- `immediate_transaction(*, db_path: str | Path | None = None, busy_timeout_ms: int = 5000) -> ContextManager[sqlite3.Connection]` opens a fresh connection, sets row factory and busy timeout, executes `BEGIN IMMEDIATE`, commits on normal exit, rolls back on any exception, always closes, and maps exhausted SQLITE_BUSY/locked to retryable `TransactionConflict`. It never silently retries application logic or nests connections.
- `Clock = Callable[[], datetime]`; `utc_now(clock: Clock = system_clock) -> datetime` requires an aware datetime and normalizes UTC. Services accept injected clocks explicitly; no global monkeypatch clock.
- `apply_migrations(migrations: Sequence[Migration], *, db_path: str | Path | None = None, clock: Clock = system_clock) -> None` records numbered migrations in `schema_migrations`; each migration and its version row commit atomically under a writer lock, and a failed migration rolls back wholly. Additive changes only; no assignment of ownerless rows.
- `append_audit_event(conn: sqlite3.Connection, *, actor_id: str | None, action: str, target_type: str, target_id: str | None, details: Mapping[str, object], occurred_at: datetime) -> str` writes non-secret structured JSON using the caller's transaction. `audit_events` has UPDATE and DELETE triggers that abort; audit detail contract forbids credential/token/ciphertext values.

- [ ] Add real-connection concurrency test with two independent sqlite connections/threads racing read-modify-write under `BEGIN IMMEDIATE`; assert no lost update and deterministic serialized result. Add bounded busy-timeout test showing caller receives `TransactionConflict`, not false success.
- [ ] Add transaction commit/rollback/connection-close tests; inject a failure between state change and audit append and assert neither commits.
- [ ] Add fake-clock timezone/UTC validation tests and deterministic expiry boundary tests.
- [ ] Add migration atomicity/order/duplicate-version/re-run tests using a temporary on-disk SQLite database, not an in-memory mock; assert failed migration leaves no version marker or partial DDL.
- [ ] Add audit append test and assert UPDATE/DELETE fail at the database boundary; assert secret-bearing field names are rejected by writer validation without recording values.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_database_foundations.py`; then implement helper and rerun against real temporary SQLite connections.

## Task 1: Issuer-qualified identity mapping and operator authorization

**Dependencies:** Task 0 and API hardening exposure stopgap/authentication baseline are complete. Risk foundations use Task 0's exact transaction, clock, migration, and audit helpers; do not implement parallel versions.

**Sequencing:** The API/input-hardening plan's Task 1 (exposure stopgap) and Task 2 (Auth0/AllTick/installer protections) must ship first. Risky private mutations are either authenticated by `CurrentUser` or return stable 503 unavailable, before this large migration starts. Shared Foundations Task 0 must also be complete before owner records are migrated.

**Files:** Modify `app/auth.py`, `app/services/database.py`, `app/api/v1/auth.py`; Test: `tests/test_account_ownership.py`, `tests/test_auth0.py`, `tests/test_supabase_auth.py`, `tests/test_auth_preferences.py`.

**Interfaces:**
- Add `TokenData.issuer: str` from verified token source and `TokenData.subject: str` retaining verified `sub`; local tokens map to `gateway:local`, Auth0 to `_auth0_issuer()`, Supabase to configured `SUPABASE_URL.rstrip('/') + '/auth/v1'` (accept only the expected verified GoTrue issuer).
- Add `resolve_principal_id(issuer: str, subject: str, *, local_user_id: str | None = None, email: str, name: str | None = None) -> str`. In one transaction, uniquely map `(issuer, subject)` to a random opaque principal and upsert `principal_profiles(principal_id,email,name)`; only the verified local issuer may set `local_user_id`, which links an existing `users.id=subject`. Existing profile/preferences rows are migrated only when that verified local link proves ownership; otherwise remain quarantined.
- `CurrentUser.id` is `principal_id`; `CurrentUser.issuer` and `.subject` retain server-verified values. `/auth/me` reads profile via principal and local password/profile operations use `user.subject`; `/auth/refresh` signs the raw verified subject, not the opaque ID. Preferences are keyed by principal ID.
- `GATEWAY_OPERATOR_USER_IDS` is a JSON array of exact issuer/subject pairs, e.g. `[{"issuer":"https://tenant.example/","subject":"auth0|abc"}]`; parse strictly, compare against `CurrentUser.issuer` and `.subject`, and return 403 for missing/empty/malformed config or no exact pair. This exact representation is shared by all plans; do not compare against opaque `principal_id`. Implement `require_operator(user: CurrentUser) -> CurrentUser`.

- [ ] Write tests `test_same_subject_different_issuers_resolve_distinct_principals`, `test_same_issuer_subject_resolves_stably`, `test_invalid_or_expired_token_never_creates_principal`, `test_operator_allowlist_missing_empty_malformed_and_match`, `test_local_profile_and_preferences_survive_principal_mapping`, `test_refresh_token_uses_verified_local_subject`.
- [ ] Run existing `tests/test_account_profile.py` and add the named profile/preferences tests to `tests/test_auth_preferences.py`; preserve the existing Auth0/Supabase test injection seams.
- [ ] Modify `_decode_auth0_token`/`_decode_supabase_token` to return issuer only after configured-provider verification; for Supabase derive canonical issuer from configured `SUPABASE_URL` after successful GoTrue introspection, not the token's unverified issuer claim. Local HS256 maps to constant `gateway:local`.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_account_ownership.py tests/test_auth0.py tests/test_supabase_auth.py tests/test_auth_preferences.py tests/test_account_profile.py`; confirm the new tests fail for the missing issuer mapping/guard.
- [ ] Implement issuer preservation without changing existing JWT signature/issuer/audience/expiry verification; add additive `auth_identities` table migration and atomic resolution.
- [ ] Rerun the named tests; pass only with distinct principals, stable mapping, local profile/preferences/refresh compatibility, and fail-closed operator behavior. Existing local HS256 and Auth0/Supabase authentication tests remain green.

## Task 2: Owner-scoped vault and encrypted BYOK provider settings

**Files:** Modify `app/services/secrets_vault.py`, `app/api/v1/vault.py`, `app/services/llm_providers.py`, `app/services/key_store.py`, `app/providers/registry.py`, `app/api/v1/llm.py`, `app/api/v1/settings.py`, and a versioned Supabase migration; Test: `tests/test_journal_and_vault.py`, `tests/test_provider_ownership.py`.

**Sequencing gate:** First inspect the deployed RPC definitions through approved read-only access. Then submit the exact versioned migration for separate operational approval. Only after migration approval, application, contract verification, and backend deployment may durable BYOK be enabled. Until that full chain succeeds, owner BYOK reads/writes and chat return a stable unavailable response. The operator's existing shared LLM key remains quarantined/orphaned (never silently reused); UI must explicitly show “Add your key” and the migration/service-unavailable state where relevant. Ship immutable URL rejection, origin binding, operator gate for global market-data provider settings, AllTick redaction, and no-redirect behavior against the current store in hardening tasks that do not depend on the BYOK migration.

**Interfaces:**
- Vault service functions become `list_secrets(owner_id: str)`, `get_secret(owner_id: str, name: str)`, `set_secret(owner_id: str, name: str, value: str, note: str = "")`, `delete_secret(owner_id: str, name: str)`. Stored key is `(owner_id, normalized_name)`; Fernet plaintext envelope is compact JSON `{owner_id,name,value,note,...}` and verifies owner/name after decrypt. Legacy global cipher entries remain in a separate inaccessible legacy namespace; filesystem/decrypt failures map to fixed public messages.
- Provider service public functions take mandatory keyword-only `owner_id: str`: `list_providers(*, owner_id: str)`, `default_provider(*, owner_id: str) -> str | None`, `resolve_endpoint(provider_id: str, *, owner_id: str)`, `save_provider_settings(provider_id: str, *, owner_id: str, base_url: str | None = None, api_key: str | None = None, models: list[str] | None = None, default_model: str | None = None)`, `delete_provider_key(provider_id: str, *, owner_id: str) -> bool`, `fetch_model_catalogue(provider_id: str, *, owner_id: str, use_cache: bool = True)`, `test_provider(provider_id: str, *, owner_id: str, model: str | None = None)`, `chat_once(provider_id: str, model: str, messages: list[dict[str, Any]], *, owner_id: str, ...)`, and `stream_chat(provider_id: str, model: str, messages: list[dict[str, Any]], *, owner_id: str, ...)`. Cache keys include owner ID; no credential-bearing model cache crosses principals.
- Provider key-store API takes `owner_id` and uses owner-qualified keys in Supabase and local dev. Add and test a versioned Supabase SQL/RPC/RLS migration from current global `(store,name)` keys; if that migration is not deployed, return unavailable for BYOK operations rather than falling back to shared/local global settings or environment key in BYOK mode. `supabase/schema.sql` currently has no provider-key RPC DDL and only a broad service-role policy; first inspect deployment metadata through an approved read-only path and record the exact definition source. If definitions are not tracked, add a reviewed additive SQL migration; applying it requires separate explicit operational approval and is not part of plan execution approval.
- Immutable catalog entry (`base_url_editable=false`) rejects a differing URL and resolver uses catalogue origin. Editable endpoint change requires explicit re-entry of that owner's key; redirects do not forward Authorization.

- [ ] Write `test_vault_same_name_isolated_between_users`, `test_owner_cannot_reveal_replace_or_delete_foreign_secret`, `test_provider_key_and_model_settings_are_owner_scoped`, `test_byok_never_falls_back_to_shared_env_key`, `test_custom_origin_change_requires_key_reentry`, `test_immutable_provider_rejects_override_and_ignores_legacy_override`, `test_provider_model_cache_isolated_by_owner`, and SQL/RPC contract tests proving owner is enforced at durable key-store boundary.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_journal_and_vault.py tests/test_provider_ownership.py tests/test_phase2_provider_safety.py`; verify tests fail on current global services.
- [ ] Implement additive owner storage while retaining inaccessible legacy vault/provider records in a separate legacy namespace; do not fan out or assign them.
- [ ] Rerun named tests and existing provider/chat tests; include redirect assertion that no credential reaches another origin.

## Task 3: Owner-scoped journal, trusted provenance, and memory

**Files:** Modify `app/services/journal_log.py`, `app/api/v1/journal.py`, `app/services/ai_trading.py`; Test: `tests/test_journal_and_vault.py`, `tests/test_account_ownership.py`.

**Interfaces:**
- Add nullable `owner_principal_id` and trusted `provenance_kind` to `journal_entries`; add owner to `journal_fill_log`; legacy rows default NULL.
- API route signatures require `user: CurrentUser`; list and stats add mandatory `owner_principal_id = user.id` to every query; read/update/delete predicates include both entry ID and owner and return 404 on foreign/NULL owner.
- Manual create ignores/rejects caller `source` claiming trusted actual provenance; manual records are stored as `source='manual'`, provenance `user_entered`.
- `journal_log.log_fill(..., *, owner_id: str, provenance_kind: Literal['simulated_fill'])` accepts simulator fills only in this plan. The future `'validated_broker_fill'` kind is not enabled until its separate ingestion design is approved and implemented.
- `journal_memory(symbol: str, *, owner_id: str)` aggregates only owner-scoped, closed, persisted canonical simulator fill records; manual and client-asserted `actual` rows never count.

- [ ] Write `test_journal_crud_list_stats_isolated`, `test_foreign_and_legacy_journal_ids_return_404`, `test_source_actual_cannot_be_forged_for_memory`, `test_fill_memory_is_owner_scoped_and_simulator_provenance_required`, `test_sync_live_remains_unavailable`.
- [ ] Run the focused journal tests and verify they expose shared queries and source trust.
- [ ] Add NULL-owner migration and owner-scoped SQL, pass owner from portfolio fill's verified owner, disable `/sync-live` behind stable unavailable until reconciliation ingestion is separately approved.
- [ ] Rerun focused tests plus existing journal/vault suite; assert old unowned rows remain untouched and invisible.

## Task 4: Owner-scoped strategies and paper portfolios

**Sequencing/UI gate:** Execute alongside the risk-plan admission release (risk Tasks 1–7) or preserve an explicit frontend “Orders unavailable while account/risk isolation is being enabled” state until both backend scope and admission are deployed together. Never leave Trade with a dead form and no explanation.
**Files:** Modify `app/api/v1/strategies.py`, `app/services/database.py`, `app/api/v1/portfolio.py`, `app/services/paper_portfolio.py`; Test: `tests/test_account_ownership.py`, `tests/test_strategy_content_hash.py`, `tests/test_phase4_paper_portfolio.py`.

**Interfaces:**
- Strategy CRUD, version, and backtest route signatures include mandatory `user: CurrentUser`. SQL uses owner-qualified strategy row selection and conditional `UPDATE/DELETE`; legacy ownerless strategy rows remain invisible. Preserve `canonical_strategy_payload(spec) -> bytes` and `compute_strategy_content_hash(spec) -> str`; do not use hashes to dedupe across owners. All existing references that treat `user.id` as raw provider `sub` must be audited when it becomes opaque; Task 7 owns repository-wide caller sweep and compatibility tests.
- Keep `portfolios.user_id` as the principal owner foreign key, with legacy shared portfolio rows left attached only to their legacy user and never selected for a verified account. Add partial unique index `CREATE UNIQUE INDEX ... ON portfolios(user_id) WHERE user_id IS NOT NULL` only after verifying that the column records principal ownership for new rows; do not apply a full-table unique constraint or rewrite legacy duplicate rows. Repository uses `user_id` column (not `owner_principal_id`); tests verify the matching partial index definition. `get_or_create_owned_portfolio(owner_id: str) -> PortfolioRecord` atomically returns a dedicated portfolio; no route, stream, or worker may call `_get_default_portfolio()`/`paper_default` for a user.
- All HTTP portfolio data routes require `CurrentUser`, derive portfolio from `user.id`, and owner-check foreign IDs before operation. Membership/group routes stay disabled/unavailable (501) until real membership authorization exists.
- WebSocket removes the query-string-token path. It accepts only to receive a first-frame bearer authentication message, resolves verified identity before portfolio lookup or stream data, then rechecks expiry and closes expired sessions. The frontend sends that first-frame auth message.

- [ ] Write two-principal matrices for strategy create/list/version/backtest/update/delete and portfolio read/history/order/fill/report/reconciliation; anonymous HTTP and WebSocket fail before portfolio lookup; legacy `paper_default` remains inaccessible.
- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_account_ownership.py tests/test_strategy_content_hash.py tests/test_phase4_paper_portfolio.py`; observe failure for unscoped routes and fixed default.
- [ ] Implement nullable migrations, owner-indexed accessors, conditional SQL updates/deletes, per-owner creation, and route derivation; keep shared controls behind operator authorization or unavailable.
- [ ] Run the same backend tests and assert all private actions remain paper-only; also run frontend E2E WebSocket ownership tests after implementing first-message auth.

## Task 5: Per-owner AI-trading configuration, logs, and loop lifecycle

**Files:** Modify `app/services/ai_trading.py`, `app/api/v1/ai_trading.py`, `app/api/main.py`; Test: `tests/test_ai_trading_ownership.py`.

**Interfaces:**
- Replace shared config functions with `get_config(owner_id: str)`, `save_config(owner_id: str, config: dict[str, Any])`, `run_cycle(owner_id: str)`, `start(owner_id: str)`, `stop(owner_id: str)`, `status(owner_id: str)`, `recent_log(owner_id: str, limit: int = 50)`.
- Persist config and log rows with owner principal. Loop registry is keyed by `owner_id`; startup does not resume old global config/loop. Each cycle calls owner-scoped portfolio, memory, risk admission when available; no path can create `paper_default`.
- `ai_trading.py` paper order path calls the same admitted per-owner service specified by the risk plan; until that dependent contract ships, no background order acceptance is enabled. `place_live_order_async` remains disabled.

- [ ] Write `test_ai_trader_config_and_logs_are_owner_scoped`, `test_start_stop_only_affects_own_loop`, `test_startup_does_not_resume_legacy_shared_config`, and `test_per_owner_cycle_never_uses_default_portfolio`.
- [ ] Run focused tests red, then implement tables/API dependency and owner-keyed loop registry.
- [ ] Rerun focused tests and paper-safety regressions; assert no broker execution path.

## Task 6: Frontend chat isolation on login, logout, and account switch

**Files:** Modify `frontend/src/context/AuthContext.tsx`, `frontend/src/components/layout/AiHarness.tsx`; Test: `frontend/e2e/chat-ownership.spec.ts`.

**Interfaces:**
- Session storage key is exactly `gateway_chat_sessions:<principalId>`; selection/model key is `gateway_llm_selection:<principalId>`. Load/save only after verified `user.id` exists. Delete old global keys without adopting their chat contents.
- Identity transition aborts `abortRef.current`, clears messages, active session/proposal/context and switches namespaced storage. Logout and Auth0/Supabase/local account changes share the same transition path.

- [ ] Write E2E tests signing in as user A, creating session, switching to user B, asserting no A content/proposals/context and B storage separate; log out and assert current state cleared; assert old global key is deleted and not imported.
- [ ] Run `npm run test:e2e -- --grep 'chat account isolation'` and confirm red.
- [ ] Implement user-keyed persistence and centralized identity transition handling; do not modify unrelated device-only chart/UI preferences.
- [ ] Run the E2E test and `npm run build`; preserve existing Playwright setup and report fixture limitations.

## Task 7: Opaque-ID compatibility sweep and cross-resource verification

**Files:** all backend/frontend references to `CurrentUser.id`/`user.id` plus relevant tests and `docs/status.md`.

- [ ] Search the entire repository for `CurrentUser.id`, `user.id`, `user_id`, `current_user.id`, and local auth subject assumptions; classify principal-owner usages versus raw provider subject/profile IDs. Add explicit compatibility tests for each raw-subject use (registration, login, `/auth/me`, refresh, preferences) and run the owner tests.
- [ ] Verify the partial unique index for owner portfolios is `UNIQUE(user_id) WHERE user_id IS NOT NULL` after confirming `user_id` holds principal IDs for new rows. This leaves pre-existing NULL-owner and duplicate legacy rows quarantined without causing additive migration failure. Do not rewrite legacy portfolio rows.

**Files:** Modify relevant ownership tests and `docs/status.md`; Test all files in this plan.

- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_account_ownership.py tests/test_auth0.py tests/test_supabase_auth.py tests/test_journal_and_vault.py tests/test_provider_ownership.py tests/test_strategy_content_hash.py tests/test_phase4_paper_portfolio.py tests/test_ai_trading_ownership.py`.
- [ ] Verify frontend with `npm run build` and `npm run test:e2e -- --grep 'chat account isolation'`; verify no network request uses broker endpoints.
- [ ] Inspect all owner-scoped SQL for ID+owner predicates; run two-user matrix and NULL-owner quarantine tests against a real temporary SQLite DB.
- [ ] Run secret-pattern scan with matched lines suppressed and `git diff --check`; report scan result, named test commands, full-suite blockers, and legacy inaccessible data. Do not read or print secret values.
- [ ] Record the exact migration version, changed schema, tests/evidence in the active security-plan ledger; do not migrate ownership for historical records.

## Self-review / Dependency Gates

- Sequence: Hardening Task 0 exposure stopgap and independent hardening Tasks 1, 2, 3 (current-store protections), and 4 first; then this plan's Foundations Task 0; then Ownership Task 1; then ownership Tasks 2/3 (journal independent, BYOK only after separately approved migration/application/contract-test/backend deployment); then Ownership Task 4 with Risk Tasks 1–7 as one coordinated release; then ownership Tasks 5/6/7 and remaining hardening Tasks 3, 5–7 when dependencies permit. Trade UI/server order paths stay unavailable until that joint release. Each plan retains its own final gate.
- Provider-key persistence is a hard prerequisite to multi-user BYOK: do not claim isolation by merely adding an owner parameter to Python. Explicit sequence is (1) inspect deployed RPC definitions through approved read-only access, (2) request and receive separate migration approval, (3) apply and test the versioned SQL/RPC/RLS migration, (4) deploy matching backend, then enable BYOK. Until then BYOK/chat are unavailable to all users and prior shared key stays quarantined. UI must show “Add your key” and migration/service-unavailable state. The shared local JSON file is not multi-user isolation. `supabase/schema.sql` has no provider-key RPC DDL; never overwrite unknown remote schema.
- Do not update or remove the `.gitignore` rule for `ROADMAP.md` in any task; tracked roadmap copies remain under `docs/`.
- The current `strategies.id` is a global primary key. Keep it global (UUID IDs already isolate namespaces), add nullable `owner_principal_id` and an owner index; scope every version/backtest query through the parent strategy owner. Preserve `UNIQUE(strategy_id, version)`. Legacy ownerless strategies remain unowned; do not use content hash for cross-owner identity.
- Because `CurrentUser.id` changes from raw verified subject to opaque principal, Task 1 migrates preferences to principal ownership and keeps local password-auth `users.id` as raw local subject. Add `principal_profiles` keyed by principal; only verified local mappings link to old local profile rows. Other legacy foreign-provider profile/preferences rows remain quarantined unless issuer-specific ownership is provable. Preserve raw `(issuer, subject)` only in `auth_identities`; tests prove local profile/preferences/refresh behavior and cross-issuer isolation.
- Paper risk admission is a separate approved plan and must provide `PaperOrderAdmissionService.submit_order(owner_id: str, portfolio_id: str, order: Order, market_context: MarketContext) -> AdmissionResult` before AI or manual orders are re-enabled. If a session source is approved, the risk plan proposes using verified Alpaca calendar sessions and latest eligible close ± adverse 2% collar, reserving collar notional, executing only during the next session, and expiring at that session's exact close. Quote source timestamp (not fetch time) must be non-delayed and ≤15 seconds; delayed Yahoo/IEX data are rejected, not widened based on fetch time. Simulated shorts require operator allowlist and explicit eligibility, segregated proceeds, and additional settled-cash collateral equal to 100% short notional; the 200% gross cap is only a ceiling, with no borrowed buying power. The per-position loss cap is 2% session-opening equity, with daily/drawdown triggers at 5%; persist session-open baselines and last trusted source-time marks and halt when a held position lacks an eligible mark, never zero-substitute. Cancellations always work during any halt; strictly risk-reducing closes may bypass per-user but not global halt, require a fresh quote, and cannot cross zero. Frontend ticket idempotency keys survive retries and rotate for changed intent. Trade UI/server orders stay unavailable until Ownership Task 4 and Risk Tasks 1–7 ship together.
- This plan never implements broker-fill ingestion or declares reconciliation evidence complete; that remains separately gated by the reconciliation design and explicit future approval.
