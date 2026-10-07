# Deploying Gateway — Vercel, Cloudflare, Supabase

Gateway is two pieces:

| Piece          | Tech                                | Where it runs                          |
| -------------- | ----------------------------------- | -------------------------------------- |
| Frontend       | Vite + React (`quant-app-v1/frontend`) | Vercel **or** Cloudflare Pages      |
| Backend        | FastAPI (`quant-app-v1/backend`)    | Vercel Python function (Services model); container still works |
| Database       | SQLite locally; users + preferences in Supabase Postgres | Supabase (see §3) |

The frontend finds the backend through `VITE_API_BASE` (build-time env var).
If it is not set, a non-localhost build assumes same-origin reverse proxying
(`src/lib/constants.ts`).

## 1. Vercel — frontend and backend on one project

Repo-root [vercel.json](../vercel.json) uses the Vercel **Services** model:
two services in one project, routed by top-level `rewrites`.

| Service | `root` | build | output / entrypoint |
| --- | --- | --- | --- |
| `frontend` | `quant-app-v1/frontend/` | `npm ci` → `npm run build` (tsc + vite) | `dist` + SPA rewrite to `index.html` |
| `backend` | `quant-app-v1/backend/` | Python 3.12, installs the service `requirements.txt` | `app.main:app` |

```bash
npx vercel deploy          # preview
npx vercel deploy --prod   # aliases https://gateway-gules-ten.vercel.app
```

- **Routing**: ~35 API prefixes (`/auth`, `/history`, `/quotes`, `/ws`, …)
  each as an exact + `:path*` pair rewrite to `{"service": "backend"}`;
  the final `/(.*)` catch-all goes to the frontend, whose internal rewrite
  serves `index.html` for SPA routes (`/app/overview`, …). Rewrites are
  evaluated in order and routing into a service is final — a new backend
  path prefix needs an entry added to the list.
- **`VITE_API_BASE` is intentionally unset**: with no value on a
  non-localhost host, `src/lib/constants.ts` resolves `API_BASE` to `""`
  (same origin), which is exactly what the Services routing gives us.
  `WS_BASE` derives `wss://` from the page host.
- **500 MB uncompressed function-bundle limit** (no tree-shaking). Two
  guards keep us under it:
  - [.vercelignore](../.vercelignore) excludes `models/` (405 MB),
    `vendor/` (31 MB), `tests/`, `data/event_logs`, `app/data/`,
    `app/settings/`, `.env*`, `node_modules/` from the upload.
    `data/instruments/catalogue_v1.json` (8.7 KB) must stay **included**:
    `/stocks/{ticker}/metadata` and `/stocks/search` read it at runtime, and
    excluding `data/` wholesale made those routes fail on Vercel (the
    uploader also does not appear to honor `!` negations, so exclude the
    state file explicitly rather than the directory).
  - [quant-app-v1/backend/requirements.txt](../quant-app-v1/backend/requirements.txt)
    is a **trimmed Vercel-only subset** of the root `requirements.txt`
    (Docker/CI remain the source of truth there): scikit-learn, skfolio,
    ccxt, Flask/flask_session, psycopg2, redis, textblob, vaderSentiment,
    beautifulsoup4, finnhub-python, fastapi-utils and pytest are dropped
    because `app/` never imports them or guards the import. The pandas-ta →
    numba → scipy/llvmlite chain stays — `pandas_ta` imports numba at
    module import time.
  - Deployed bundle: **≈ 474 MB** (Vercel reports “exceeds the standard
    size; optimizing dependencies”). The pre-trim build failed at 840 MB.
- Vercel's Python requirements parser rejects `-r` includes and inline `#`
  comments after a pin — keep every comment on its own line in both files.
- **The function filesystem is read-only** (only `/tmp` is writable). Code
  that writes next to its own module must fall back to `GATEWAY_DATA_DIR`
  (set to `/tmp`) or it raises `OSError: [Errno 30] Read-only file system`
  and 500s every affected route — that is exactly what
  `app/providers/registry.py` used to do on each `get_provider()` call
  (news, calendar and quote routes). It now relocates its provider-key
  settings dir to `$GATEWAY_DATA_DIR/provider_settings` on EROFS, and reads
  degrade to "no stored keys" (routes answer 503 instead of 500).
  `app/services/llm_providers.py` follows the same pattern — without it
  `GET /llm/providers` 500'd with *"internal server error for llm provider
  retrieval"* — and a failed settings write now surfaces as a clear 400/503
  (`LlmError`) instead of a bare 500.
  Consequence: **provider API keys saved from the UI on Vercel live in
  per-instance `/tmp`** and vanish when the instance recycles — set them as
  Vercel env vars (`FINNHUB_API_KEY`, …) for durability.
- **WebSockets work** (Vercel public beta; Python/ASGI support shipped
  2026-07-23 — FastAPI needs no Vercel-specific upgrade code, just a WS
  implementation such as `websockets`/`uvicorn[standard]`, both already in
  the requirements). Verified on production: `/ws/trading` and
  `/portfolio/stream` complete the 101 handshake through the `/ws` +
  `/portfolio` service rewrites, speak their protocols, and accept
  Supabase-issued tokens via `?token=`. Two platform rules apply:
  - A connection **closes at the function max duration** (default 300s) —
    clients must reconnect and resubscribe. `src/lib/tradingSocket.ts`
    implements this with capped backoff; `/portfolio/stream` does the same.
  - Connections are **pinned to one function instance**, so state shared
    across clients (rooms, presence) must live in an external store — the
    app's per-instance broadcast is fine as long as each instance runs its
    own feed.
  - Unauthenticated upgrades are rejected at handshake time (HTTP 403 /
    close 4001), which is the app's own auth check, not a platform block.
- Deployment Protection (Vercel Authentication) is on, so plain `curl`
  gets the login wall — use `npx vercel curl <url> -- …` (everything after
  `--` is passed to curl, e.g. `--request POST --data '{…}'`).

## 2. Cloudflare (frontend on Workers static assets)

The repo is connected to Cloudflare **Workers Builds** (Worker `gateway`,
GitHub repo `Acheron449/Gateway`). [wrangler.toml](../wrangler.toml) is an
assets-only Worker config serving `quant-app-v1/frontend/dist` with SPA
fallback — without it every build failed with *“Missing entry-point to
Worker script or to assets directory”*.

Pipeline settings (Workers & Builds → Build triggers):
| Trigger | Branch | Build command | Deploy command |
| --- | --- | --- | --- |
| production | `main` | `cd quant-app-v1/frontend && npm ci && npm run build` | `npx wrangler deploy` |
| non-production | everything else | `cd quant-app-v1/frontend && npm ci && npm run build` | `npx wrangler versions upload` |

The deploy commands are already configured; the **build command must be set
dashboard-side** on both triggers (the API token used for automation is
read-only for that endpoint).

```bash
# Local equivalent:
cd quant-app-v1/frontend && npm ci && npm run build
cd ../.. && npx wrangler deploy
```

- The FastAPI backend runs anywhere that speaks HTTP (container, Fly.io,
  Render). Point the frontend at it with `VITE_API_BASE` at build time.
- WebSockets (`/ws/portfolio/stream`, `/ws/trading`) need the backend
  origin directly (Workers assets don't proxy them by default).
- Merge the dev branch into `main` for production deploys; pushes to other
  branches only upload preview versions (`wrangler versions upload`).

## 3. Supabase (hosted Postgres for trade data)

The app writes SQLite locally. To analyse trades in Supabase (or sync them):

1. Create a project at [supabase.com](https://supabase.com).
2. Apply [supabase/schema.sql](../supabase/schema.sql) in the SQL editor
   (or `supabase db push`).
3. Copy the project URL + anon key into env: `SUPABASE_URL`,
   `SUPABASE_ANON_KEY` (both are already declared in `vercel.json` and
   `.env.example`).

Auth state uses a second, migration-managed surface (already applied to
the project — `gateway_users_preferences_rpcs`):

- Tables `public.gateway_users` (email unique, bcrypt hash) and
  `public.gateway_preferences` (FK → users, `ON DELETE CASCADE`) with
  **RLS enabled and no policies** — direct table reads return `[]`.
- Access goes through SECURITY DEFINER RPCs (`gw_create_user`,
  `gw_get_user_by_email`, `gw_get_user_by_id`, `gw_get_preferences`,
  `gw_upsert_preferences`), gated by `_gw_check(<SUPABASE_RPC_SECRET>)`.
- `app/services/database.py` switches modes from the environment at call
  time: all three of `SUPABASE_URL` / `SUPABASE_KEY` /
  `SUPABASE_RPC_SECRET` ⇒ Supabase (transport errors raise — no silent
  fallback); otherwise the local SQLite file.
4. Export rows with `POST /journal` data or point your sync job at
   `journal_entries` — the `source` column (`paper` / `actual` / `manual`)
   is what makes actual-vs-paper comparison queries work:

```sql
select * from journal_performance_by_source;  -- paper vs actual side by side
```

### Sign-in with Supabase Auth (active)

The app's identity provider is **Supabase Auth** (GoTrue), not Auth0:

- **Frontend** (`src/lib/supabase.ts`, `context/AuthContext.tsx`) creates a
  Supabase client from `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` and
  signs in with `signInWithPassword` / `signUp`. The resulting access token
  becomes the app session: it is stored as `gateway_auth_token`, sent as
  `Bearer` on every API call and as `?token=` on the WebSocket URLs, then
  validated against `/auth/me` before the UI turns signed-in. With the VITE
  vars unset (local dev) the context falls back to the backend's own
  `/auth/register` + `/auth/login` endpoints.
- **Backend** (`app/auth.py`) treats the Supabase token as a third token
  flavour (alongside local HS256 and Auth0 RS256) and verifies it by
  **introspection**: `GET {SUPABASE_URL}/auth/v1/user` with the publishable
  key — GoTrue only answers 200 for tokens it accepts, so no JWT secret has
  to leave the dashboard. Verified results are cached 60s (rejected tokens
  10s) so an endpoint pays one outbound call per token, not per request.
- **Provisioning**: on first sight of a Supabase user, `ensure_user()`
  creates the `gateway_users` row (name copied from `user_metadata`,
  `hashed_password` NULL — hence the migration that dropped NOT NULL) so the
  `gateway_preferences` foreign key and `/auth/me` work.
- **Email confirmation**: when the project requires confirmation, signup
  returns no session and the UI reports "check your email to confirm it,
  then sign in". GoTrue rejects non-deliverable domains (`.test`,
  `example.com`) and rate-limits sends (`over_email_send_rate_limit`), so
  raise the send quota or enable auto-confirm in the Supabase dashboard for
  smoother sign-ups.
- Local password auth keeps working alongside it (`/auth/register`,
  `/auth/login`) — useful for API clients, tests and dev without Supabase.

## 4. Environment variables

All of these belong in the backend environment (see [.env.example](../.env.example)):

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET_KEY` | Session signing — required, the API refuses to boot without it |
| `GATEWAY_PROVIDER_KEY` | Fernet key encrypting provider keys **and** the secrets vault — without it `POST /settings/providers/{name}/key` answers 503 and `PUT /llm/providers/{id}` answers 400 with *"… is not set"*. Set for Production **and** Preview (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` \| `npx vercel env add GATEWAY_PROVIDER_KEY production`); Production is set, Preview still needs it (the CLI's branch prompt blocks non-interactive adds) |
| `GATEWAY_QUOTES_TTL` | Seconds before batch quotes refetch (default 10) |
| `GATEWAY_PRICE_TTL` | Seconds before the fill/risk price cache refetches (default 10) |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Live trading section (Alpaca) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | Hosted Postgres connection |
| `SUPABASE_URL` + `SUPABASE_KEY` + `SUPABASE_RPC_SECRET` | All three set ⇒ auth state (users, preferences) is read/written through the SECURITY DEFINER RPCs in Supabase; any one missing ⇒ SQLite on `GATEWAY_DATA_DIR` |
| `GATEWAY_DATA_DIR` | Only writable path on Vercel is `/tmp` — the SQLite fallback DB is created at import time, so this must point there |
| `VITE_AUTH0_DOMAIN` / `VITE_AUTH0_CLIENT_ID` / `VITE_AUTH0_AUDIENCE` | Auth0 SPA config (dormant — the Auth0 button only mounts when all three are set) |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Frontend Supabase Auth client — **the active sign-in path**. Baked in at build time, so set them in the scope you deploy to (Production *and* Preview) before `vercel deploy`. The anon key is public by design, but Vercel requires an explicit `--type config` when adding it under a `VITE_` name |
| `VITE_API_BASE` | Legacy frontend build-time backend URL — **leave unset on Vercel** (same-origin routing) |

## 5. Post-deploy smoke test

```bash
API=https://gateway-gules-ten.vercel.app
vc() { npx vercel curl "$1" -- "${@:2}"; }   # deployment protection bypass

vc "$API/health" | head -c 200     # {"status":"ok",...}
vc "$API/" | head -c 100           # SPA index.html (frontend service)
vc "$API/app/overview" | head -c 60  # same index.html — SPA fallback

EMAIL="smoke-$(date +%s)@local.test"
REG=$(vc "$API/auth/register" --request POST \
        --header 'content-type: application/json' \
        --data "{\"email\":\"$EMAIL\",\"password\":\"Sup3rSecret!\",\"name\":\"S\"}")
TOKEN=$(printf '%s' "$REG" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
vc "$API/auth/me" --header "authorization: Bearer $TOKEN"
vc "$API/auth/preferences" --request PATCH \
   --header "authorization: Bearer $TOKEN" \
   --header 'content-type: application/json' \
   --data '{"theme":"light","watchlists":[{"id":"wl1","name":"Main","symbols":["MSFT"]}],"saved_layouts":{}}'
```

Then confirm the row actually landed in Supabase (not SQLite):

```sql
select u.email, p.theme, p.watchlists
from gateway_preferences p join gateway_users u on u.id = p.user_id
order by u.created_at desc limit 5;
```

Frontend gate: `cd quant-app-v1/frontend && npx tsc --noEmit`.
Backend gate: `cd quant-app-v1/backend && PYTHONPATH=. JWT_SECRET_KEY=… \
  GATEWAY_DATA_DIR=/tmp/gateway-ui-data ../../.venv/bin/python -m pytest tests/ -q`
