# Deploying Gateway

Gateway is three pieces:

| Piece | Tech | Runs on |
| --- | --- | --- |
| Frontend | Vite + React (`quant-app-v1/frontend`) | **Cloudflare Pages** |
| API | FastAPI (`quant-app-v1/backend`) | A container, behind Cloudflare's proxy |
| Database + Auth | Supabase (GoTrue + Postgres) | Supabase |

> Requirements are normative in [`SRS.md`](SRS.md) §3. This page is the how-to.
> Vercel is no longer used: Cloudflare Pages serves static assets only and
> cannot execute Python, so the API has its own host.

The frontend finds the API through `VITE_API_BASE`, baked in at build time. When
it is unset, a non-localhost build assumes same-origin proxying
(`src/lib/constants.ts`).

## 1. Frontend — Cloudflare Pages

Create a Pages project connected to `Acheron449/Gateway`:

| Setting | Value |
| --- | --- |
| Root directory | `quant-app-v1/frontend` |
| Build command | `npm ci && npm run build` |
| Output directory | `dist` |
| Node version | `20` (set `NODE_VERSION=20` if the default differs) |

Build-time environment variables (Pages → Settings → Environment variables):

| Variable | Value |
| --- | --- |
| `VITE_API_BASE` | `https://api.<your-domain>` |
| `VITE_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | the publishable anon key (public by design) |

**SPA fallback** is configured by `quant-app-v1/frontend/public/_redirects`, which Vite copies into `dist/`:

```
/*    /index.html   200
```

**Workers Builds is retired.** `wrangler.toml` was removed in phase P1, so Pages is the single hosting path (SRS AR-2). Unknown paths return `index.html` with HTTP 200 instead of 404.

Reference numbers from a local run (2026-11-07): `npm ci && npm run build`
finishes in ~6 s, emitting 1.01 MB JS (287 KB gzip) and 157 KB CSS. The SRS
budget is 2 minutes and 5 MB gzip (AR-8, AR-9).

## 2. API — container

`quant-app-v1/backend/Dockerfile` builds the service; `PYTHONPATH=.` and
`uvicorn app.main:app` are the contract.

```bash
docker build -t gateway-api quant-app-v1/backend
docker run --rm -p 8000:8000 --env-file .env gateway-api
curl -s localhost:8000/health
```

| Requirement | Note |
| --- | --- |
| HTTP + WebSocket | `/ws/trading` and `/portfolio/stream` need an upgrade-capable host |
| Image ≤ 600 MB | SRS AR-10 — the 405 MB `models/` tree and `vendor/` must stay out of the build context |
| Writable path | `GATEWAY_DATA_DIR` (no read-only-filesystem assumptions) |

Attach the custom domain `api.<your-domain>` **proxied** through Cloudflare so
TLS, WAF and WebSockets are handled at the edge. CORS on the API must allow the
Pages origin exactly (SRS AR-6) — wildcard origins are rejected.

**The container host is an open decision** (SRS §10 O-1). Cloudflare cannot run
Python; any host that satisfies the table above works. Nothing in the codebase
should assume a specific vendor.

## 3. Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. Apply [`supabase/schema.sql`](../supabase/schema.sql) in the SQL editor (or
   `supabase db push`).
3. Put `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` in
   the API environment and the two `VITE_SUPABASE_*` values in the Pages build.

### Sign-in (the only identity provider)

- **Frontend** (`src/lib/supabase.ts`, `context/AuthContext.tsx`) signs in with
  `signInWithPassword` / `signUp`. The access token becomes the app session,
  sent as `Bearer` on API calls and as `?token=` on WebSocket URLs, and is
  validated against `/auth/me` before the UI turns signed-in.
- **Backend** (`app/auth.py`) verifies the token by introspection:
  `GET {SUPABASE_URL}/auth/v1/user` with the publishable key. GoTrue only
  answers 200 for tokens it accepts, so no JWT secret leaves the dashboard.
  Verified results are cached 60 s (rejected tokens 10 s).
- **Provisioning**: on first sight of a Supabase user, `ensure_user()` creates
  the local `gateway_users` row so preferences and `/auth/me` work. Email
  confirmation is controlled in the Supabase dashboard — GoTrue rejects
  non-deliverable domains (`.test`, `example.com`) and rate-limits sends.
- **Local password auth** (`/auth/register`, `/auth/login`) is for
  `GATEWAY_ENV=local` development and tests only (SRS FR-A7).
- **Auth0 is removed** (SRS FR-A6). No Auth0 code, dependency or environment
  variable remains: `app/auth.py` verifies Supabase tokens and nothing else.

### Access pattern

Tables are RLS-enabled with ownership policies (SRS §7), not open reads. The
existing auth-state surface uses SECURITY DEFINER RPCs gated by
`_gw_check(<SUPABASE_RPC_SECRET>)`: `gw_create_user`, `gw_get_user_by_email`,
`gw_get_user_by_id`, `gw_get_preferences`, `gw_upsert_preferences`. Provider API
keys use the same shape (`gateway_provider_keys`, Fernet ciphertext only,
RPCs `gw_list_provider_keys` / `gw_upsert_provider_key` / `gw_delete_provider_key`).

`app/services/database.py` switches at call time: all three of `SUPABASE_URL` /
`SUPABASE_KEY` / `SUPABASE_RPC_SECRET` set ⇒ Supabase (transport errors raise —
no silent fallback); otherwise local SQLite on `GATEWAY_DATA_DIR`.

## 4. Environment variables

| Variable | Side | Purpose |
| --- | --- | --- |
| `GATEWAY_ENV` | API | `local` \| `test` \| `paper` \| `production` |
| `GATEWAY_EXECUTION_MODE` | API | must be `paper`; anything else refuses to boot |
| `JWT_SECRET_KEY` | API | local session signing |
| `GATEWAY_DATA_DIR` | API | writable path for SQLite / job scratch |
| `GATEWAY_OPERATOR_IDS` | API | comma-separated ids allowed global actions; empty ⇒ deny |
| `GATEWAY_PROVIDER_KEY` | API | Fernet key for stored provider keys and the vault |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | API | auth introspection, server-side writes |
| `SUPABASE_RPC_SECRET` | API | guards the SECURITY DEFINER RPCs |
| `VITE_API_BASE` | Pages build | API origin |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Pages build | Supabase client |
| `GATEWAY_QUOTES_TTL` / `GATEWAY_PRICE_TTL` | API | quote and fill-price cache seconds (default 10) |

There are no `VITE_AUTH0_*` or Vercel-specific variables any more.

## 5. Post-deploy smoke test

```bash
API=https://api.<your-domain>
SITE=https://app.<your-domain>

curl -s "$API/health" | head -c 200          # {"status":"ok",...}
curl -sI "$SITE/" | head -1                  # 200
curl -sI "$SITE/app/overview" | head -1      # 200 — SPA fallback, not 404

EMAIL="smoke-$(date +%s)@local.test"
REG=$(curl -s "$API/auth/register" -X POST \
        -H 'content-type: application/json' \
        -d "{\"email\":\"$EMAIL\",\"password\":\"Sup3rSecret!\",\"name\":\"S\"}")
TOKEN=$(printf '%s' "$REG" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s "$API/auth/me" -H "authorization: Bearer $TOKEN"

# Isolation gate (SRS P2): a second account must not see the first's rows.
# Foreign-origin mutation gate (SRS P6): expect 403.
curl -s -o /dev/null -w '%{http_code}\n' "$API/portfolio/orders" -X POST \
  -H 'origin: https://evil.example' -H 'content-type: application/json' -d '{}'
```

Then confirm rows landed in Supabase, not SQLite:

```sql
select u.email, p.theme, p.watchlists
from gateway_preferences p join gateway_users u on u.id = p.user_id
order by u.created_at desc limit 5;
```

## 6. Gates

```bash
cd quant-app-v1/frontend && npx tsc --noEmit && npm run build
cd ../backend && PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q
```

Deployment is done when both pass **and** the SRS phase gate (§9) for the
work being shipped is met.
