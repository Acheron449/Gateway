# API and Hostile-Input Hardening

**Date:** 2026-10-18  
**Status:** Draft for user review. No code changes authorized by this design alone.

## Goal

Close confirmed API and parser issues that expose credentials, disable authentication checks, allow request-controlled credential destinations, or permit unbounded input work. Preserve the current unavailable live-execution boundary and avoid adding new services/dependencies.

## Findings and root causes

- When `AUTH0_DOMAIN` is set without `AUTH0_AUDIENCE`, `auth.py` sets `verify_aud=False` and accepts a token for another resource.
- `alltick_provider.py` puts its API key in the query string. HTTP status errors include the full request URL; `news.py` returns raw `ProviderUnavailableError` text in a public quote response.
- `llm_providers.save_provider_settings` accepts caller `base_url` even for catalog entries with `base_url_editable=False`; `resolve_endpoint` applies persisted URL overrides and may reuse stored/environment credentials on that destination. Provider settings are shared but user-authenticated, not operator-authorized.
- Kronos installer route has no required identity and invokes a shell script that upgrades pip and mutates the running backend environment. Candle converter materializes a DataFrame from all keys before filtering and has no shared count bound. Kronos install path also reaches script interpolation, so path validation/security is within scope.
- Chat Markdown parser runs attacker-controlled text through overlapping inline regex without a size cap; frontend stream appends unlimited output. Backend request limits are per-field only, not total aggregate message size/stream size.

## Design

### Auth0 audience

- At configuration load, if Auth0 is enabled, require a non-empty `AUTH0_AUDIENCE`; otherwise fail startup with a sanitized configuration error. If configuration can change at runtime, reject every Auth0 token when it is missing.
- Always pass the expected audience to JWT verification with audience validation enabled. Remove the `verify_aud=False` branch. Keep issuer, signing algorithm, signature, expiry and not-before validation.
- Do not modify local HS256 verification behavior.

### Credential-safe provider failures

- At adapter boundary, wrap AllTick transport/status failures with a fixed provider-safe message and optional numeric status only; never interpolate the HTTP exception, URL, query, headers or response body.
- At the public quote API, return a fixed message (e.g. “Quote provider unavailable”) and safe provider/status fields; do not expose exception text even if a future provider regresses. Provenance failure messages use the same safe text.
- Audit relevant provider logs to ensure no exception containing token URL is logged. Keep token-in-query protocol limitation documented; avoid claiming transport-level elimination where upstream API requires query credentials.

### Provider endpoint and key binding

- Provider settings/key mutation is owner-scoped BYOK and requires authentication, not operator status. The configured operator allowlist does not grant automatic access to user BYOK secrets. Each owner’s stored key is encrypted and bound to that owner’s endpoint; never fall back to another owner’s key or a global environment key in BYOK mode.
- The later optional operator-managed shared-key mode is out of this scope. If added, it requires per-user budget/rate/concurrency checks before any provider call; record that as a separate future addition. Do not implement shared-key budgets as part of current BYOK work.
- For `base_url_editable=false`, save rejects a differing `base_url`; resolver always uses catalogue URL, ignoring/removing any previously persisted override. Catalogue-origin endpoint remains the only destination for a credential. In the first exposure-stopgap slice, apply these destination checks to the current store before BYOK migration; global current-store market-data settings are immediately operator-gated. BYOK provider settings/keys remain owner-scoped and unavailable until the separately approved durable-store migration is applied, contract-tested, and deployed.
- For editable/custom providers, validate allowed URL syntax/scheme/host, deny credentials in userinfo, and avoid silently inheriting a user's previously stored key when changing to a different origin. Require explicit confirmation/re-entry of that user's key for the new origin, and persist the key with its approved origin. Enforce redirect policy so Authorization credentials are not forwarded to a redirected host. Keep local loopback support only under existing explicit custom-provider configuration and policy.
- Do not send a credential to an origin until endpoint and credential origin binding are verified. Validate resolved DNS addresses immediately before connection; if the installed httpx transport cannot safely pin the validated result, explicitly document the residual DNS-rebinding TOCTOU race rather than claim DNS pinning.

### Runtime Kronos install

- Default the runtime installer to disabled. The UI/API return a stable unavailable response unless explicit deployment setting enables it and a configured operator is authenticated. This disable-only guard ships in the independent exposure slice without waiting for identity mapping; enabling remains gated on verified operator identity.
- Prefer dependencies installed during build/deployment. If retaining optional operator install, do not run arbitrary shell interpolation or `pip install --upgrade pip`; constrain checkout path to an approved managed directory, invoke argument-array subprocesses without a shell, and allowlist the repository source/ref. No anonymous force/path request.
- Status may be publicly or authenticatedly read only if it does not leak filesystem paths or host information; expose a sanitized state and bounded logs.

### Kronos candle conversion

- Define one hard maximum candle count of exactly 2,000 and a small allowlist of expected keys: `time`/`timestamp`/`datetime`/`date` and OHLCV/amount aliases. Frontend sends only `bars.slice(-2000)` before JSON serialization; enforce the same limit in HTTP validation and shared conversion before DataFrame allocation.
- Before DataFrame construction: require `bars` as a list of mappings, enforce the count, project each mapping to allowed keys, reject conflicting aliases and unknown columns (or discard them consistently at the shared boundary; chosen default: discard unknown vendor metadata while reject empty/invalid rows). Convert numeric fields and timestamps with bounded validation. This method is shared by HTTP and local-server paths.
- API model validation also caps body field shape; the service validates independently so non-HTTP callers receive the same limits.

### Chat response/parser limits

- Replace `INLINE_RE.exec(rest)` with a single left-to-right tokenizer that advances at least one character per iteration and never retries from nested unmatched opening brackets. Preserve existing supported inline elements and safe-link policy.
- Cap per-message Markdown rendering; over-limit text renders as escaped/plain React text with a clear truncated/oversized indication rather than parsing. Use a single explicit UTF-16/Unicode character-count contract.
- Set a conservative aggregate outbound chat context limit in the backend (request-level sum across all messages and tool payload structures) before opening provider connections. Set aggregate assistant streamed output maximum in frontend and backend SSE production; abort/cancel upstream once limit is reached and return a safe terminal error. Do not truncate a provider result and persist it as complete.
- Bound individual nested tool arguments and tool cycles; preserve existing explicit tool confirmation for backtests.

## Failure behavior

Missing Auth0 audience prevents Auth0 authentication, not bypasses audience checks. Any provider config inconsistency prevents credentialed requests. Installer remains unavailable absent explicit secure operator configuration. Oversize or malformed candles/chat are rejected before expensive allocation/provider calls. The UI remains responsive and renders plain text if output exceeds Markdown capacity. No user-controlled exception data is returned for provider failures.

## Regression tests

- Auth0 enabled with absent/empty audience fails startup/config and token verification; correct audience accepted; wrong/missing audience rejected; local JWT path unchanged.
- AllTick transport/HTTP exception contains a fake token in URL but neither public body nor logs/provenance include it; status code remains safe.
- Immutable catalogue provider old saved override ignored; update attempt rejected; custom-origin changes cannot reuse prior/environment credential; redirect not followed with authorization.
- Anonymous runtime install rejected; disabled mode stable unavailable; no `shell=True`, no interpolated path command, forced install operator-checked; status/log size capped.
- Kronos converter accepts canonical candles, ignores/rejects unknown keys as designed, rejects oversized count before DataFrame construction, rejects malformed rows/conflicting aliases/numeric overflow; shared local-server path uses same method.
- Malformed bracket stress cases verify tokenizer correctness, plain text fallback limit, safe URL schemes, and linear growth on representative hostile inputs.
- Aggregate inbound/outbound caps reject at boundary; stream aborts before exceeding cap and no completion is persisted as complete; tool call budget stays bounded. Per-owner concurrent chat/stream limit is exactly two active requests, acquired atomically before provider connection and released on completion/error/disconnect/cancel; multi-worker deployments without a shared atomic limiter fail unavailable rather than silently use process-local enforcement.

## Non-goals

- This work does not create new LLM provider credentials or third-party services; keep existing integrations.
- It does not implement user ownership itself (see ownership design) or enable live/broker execution.
- Performance improvement claims require representative measurements after implementation; this design does not claim a measured speedup.
