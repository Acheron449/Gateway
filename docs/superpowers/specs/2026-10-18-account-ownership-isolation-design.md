# Account Ownership and Private-Data Isolation

**Date:** 2026-10-18  
**Status:** Draft for user review. No code changes authorized by this design alone.

## Goal

Prevent one authenticated account or anonymous visitor from reading or changing another account's secrets, journal, strategies, AI trading configuration, or simulated portfolio. Ownership always comes from a canonical principal resolved from the verified token issuer and subject, never a request-supplied owner or a hard-coded shared ID. Auth0, local HS256, and configured Supabase Auth accounts with the same `sub` are distinct principals.

## Existing behavior

- `vault.py` requires authentication but delegates to a name-keyed global encrypted JSON store (`secrets_vault.py`). Any account can list/reveal/replace/delete any named credential.
- `journal.py` is mounted publicly. Routes use a shared SQLite `journal_entries` table without owner columns; `/sync-live` retrieves account activity through a global provider. `ai_trading.journal_memory()` aggregates every closed record.
- Strategy routes mutate/list global strategy IDs without user ownership.
- `portfolio.py` uses `paper_default` for HTTP calls and some control routes without a user dependency. Other multi-portfolio routes use hard-coded `default_user`; membership service imports are stubs.
- AI-trading config uses a shared settings file and unowned background state; its router is mounted with an optional-user dependency (which permits anonymous access).
- `CurrentUser` currently exposes `id`, `email`, optional name but not issuer. Local HS256 tokens omit `iss`; Auth0 includes an issuer; Supabase Auth is verified by GoTrue introspection. Owner identity must preserve verified issuer plus subject before mapping to the Gateway principal key; do not use email to merge providers.
- There is no existing role/tenant database. Operator privileges remain a separate configured allowlist, not an account role.

## Design

### Identity and ownership

1. Add an `auth_identities` mapping keyed by `(issuer, subject)` with a stable opaque `principal_id`; local HS256 maps existing user rows to a fixed `gateway:local` issuer, Auth0 uses the verified Auth0 issuer, and Supabase uses the configured GoTrue issuer after introspection. Never merge on email. Add nullable `owner_principal_id` columns to journal and strategy records and ownership to per-user portfolio/config records. Use additive migrations; existing records stay `NULL`. After verifying that existing `portfolios.user_id` will store principal IDs for new records, use a partial unique index `UNIQUE(user_id) WHERE user_id IS NOT NULL`; legacy NULL owners and duplicate legacy rows remain quarantined and do not abort migration.
2. Resolve the identity mapping inside mandatory auth dependency after token verification. Every read/mutation scopes by `owner_principal_id = current_user.id`; payloads cannot set/transfer owner. Conditional SQL updates/deletes include owner in the statement. Return 404 for foreign/unowned IDs.
3. New records use the mapped principal ID. Create a distinct simulated portfolio per principal. Never select `paper_default` for SaaS users. Trade UI and backend order acceptance remain explicitly unavailable until Ownership Task 4 and Risk Tasks 1–7 are released together; no interim form targets a disabled route.
4. Admin/global operations use a separate dependency checking `GATEWAY_OPERATOR_USER_IDS`, a strict JSON array of exact `{issuer,subject}` pairs from the verified token identity. Missing/empty/malformed or duplicate/ambiguous entries deny. This representation stays stable when `CurrentUser.id` becomes an opaque principal; never compare raw `user.id` alone or put opaque principal IDs in the env allowlist. No email privilege or self-service role.

### Vault

- Key encrypted entries by `(owner_principal_id, normalized_name)`. List/reveal/upsert/delete accept the principal ID from the verified dependency and never from payload.
- BYOK applies now to LLM providers: each owner has independent encrypted key and provider/model settings. A BYOK key must never fall back to another owner's stored key or a shared environment key. A keyless provider may operate only when its configuration is explicitly owner-scoped.
- Keep provider catalogue metadata global/read-only; user settings and key mutation are owner-scoped. Existing global provider settings are not copied to every user; operator-owned global settings remain quarantined for the deferred shared-key mode.
- Old global name-keyed vault entries remain in a legacy namespace inaccessible to user-scoped handlers until an operator performs a separately reviewed, explicit per-secret ownership migration. Never copy automatically to the first account.
- Preserve Fernet encryption and 0600/atomic file storage. Do not disclose raw cipher/decryption exceptions to clients.

### Journal and AI memory

- Add owner scope to manual rows and logged fills. All journal API routes including sync/import use `CurrentUser` and owner filters. Automated fill logging receives owner identity from its owning portfolio/fill, not from user request data.
- Existing rows without owner remain quarantined; authenticated users cannot list/modify them.
- `source='actual'` is not proof of a broker fill. Add trusted provenance to fill-derived rows, and derive AI memory only from canonical persisted simulator fill records or, after the separate reconciliation subsystem is approved, validated broker-origin fill records. Manually entered rows and user-supplied `source` values never train trusted memory.
- Keep broker sync unavailable while `/live` is unmounted and no reviewed account-ownership/ingestion mechanism exists.

### Strategies and provider settings

- Store strategy owner principal ID; list/get/update/backtest/delete are owner-filtered and atomically scoped. Legacy ownerless strategies stay unavailable until explicit migration.
- BYOK provider settings are private owner-scoped resources, not shared administration. Operator allowlist is used only for truly global config (global emergency stop, default risk policy, shortable-symbol eligibility, and a future operator-managed shared-key mode). Do not let an ordinary account alter another owner’s endpoint/key.
- Chat remains authentication-required. Session persistence is client-side but strictly account-namespaced; only load/save when `user.id` is known. On logout or account change, abort any stream, clear current transcript/proposals/context and remove old account-scoped storage. Do not copy the old global chat key into an account namespace.

### Simulated portfolio APIs

- Require `CurrentUser` on all portfolio HTTP APIs, including state/history/order/fill/report/reconciliation/kill-switch/membership/group routes. WebSocket authenticates token subject before accepting and uses that subject's portfolio.
- Derive portfolio ID from verified user ownership. Do not accept arbitrary portfolio IDs unless the actual membership store is implemented and checks READ/TRADE/ADMIN permissions in the same owner-scoped service.
- Existing multi-portfolio service stubs must not be treated as authorization; endpoints relying on them should return unavailable/501 or remain unmounted until a real owner/member store exists.
- Restrict reset/global risk control operations to the operator allowlist. A user-specific paper portfolio halt may be exposed only if defined by the per-user authoritative-risk design and is enforced for all submitters.

## Data flow and failure policy

Authentication fails with 401 before a data operation. Ownership mismatch/unowned legacy records return 404. Missing operator configuration or non-operator is denied (403) for privileged routes. Database/owner-check failures never fall back to a shared/default user. A partial migration produces no access to ownerless rows. Stream/account changes abort in-flight frontend operations and clear transient data to avoid stale display after identity transitions.

## Regression tests

- Identity mapping for the same `sub` from local HS256, Auth0 and Supabase resolves to distinct principals; repeat tokens for one issuer/sub resolve to the same principal.
- Two-user matrix for vault list/reveal/replace/delete, per-user provider config/key isolation, and same-name collisions.
- Two-user journal CRUD/list/stats and owner-scoped fills; `/sync-live` unauthenticated and blocked while broker source not enabled.
- Manual fake `source='actual'` row does not influence AI memory; only canonical fill-backed rows do.
- Two-user strategy CRUD/backtest access; cross-owner IDs return 404.
- Two-user portfolio state/order isolation; anonymous HTTP and WebSocket rejected before portfolio lookup; no use of `paper_default` for a user.
- Legacy ownerless records are invisible and are not automatically assigned.
- Operator allowlist absent/empty, non-operator, operator, malformed config; global risk policy and shortability admin endpoints enforce it. BYOK provider CRUD is owner-scoped without requiring operator status.
- Frontend session load/save namespace and logout/account-switch clearing; no global-key restoration.

## Consequences / migration

The design changes user-visible behavior from a shared demo portfolio to independent portfolios and may hide existing data that has no proven owner. That is intentional to avoid data disclosure and unsafe assignment. A separate administrative migration can be designed only after each legacy record's owner is established from trustworthy evidence. The migration must be reversible/auditable and is not part of this design.
