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

Both of these Pages configurations are supported and produce the same SPA
output. Use whichever root the project already has.

| Setting | Repository root | Frontend directory |
| --- | --- | --- |
| Root directory | blank or `.` | `quant-app-v1/frontend` |
| Build command | `npm run build` | `npm ci && npm run build` |
| Output directory | `dist` | `dist` |
| Node version | `20` (`NODE_VERSION=20`) | `20` (`NODE_VERSION=20`) |

The repository-root `package.json` is deliberately a thin Pages entry: it
installs the frontend lockfile, runs the frontend's `tsc && vite build`, and
writes the result to root `dist/`. The Python manifests now live at
`quant-app-v1/backend/requirements-full.txt` and
`quant-app-v1/backend/requirements-dev.txt`; the repository root contains no
`requirements.txt`, so Pages does not detect a Python project or run `pip`.

Create a Pages project connected to `Acheron449/Gateway`, save the settings
above, and use **Retry deployment** (or push a new commit). A correct log
installs Node dependencies from `quant-app-v1/frontend/package-lock.json`, runs
`tsc && vite build`, and uploads `dist`. It never mentions `pip` or
`requirements.txt`.

> If a Pages log still shows `Installing project dependencies: pip install -r
> requirements.txt`, the deployment is using an old commit or a different
> Pages project; the current repository root has no Python requirement file.
> Pages has no Python runtime, and the API (`quant-app-v1/backend`) still
> builds and runs separately as the container in §2.

Build-time environment variables (Pages → Settings → Environment variables):

| Variable | Value |
| --- | --- |
| `VITE_API_BASE` | `https://api.<your-domain>` — **required**; Pages serves static files only and does not proxy the API |
| `VITE_SITE_URL` | canonical Pages origin, e.g. `https://<project>.pages.dev` or `https://app.<your-domain>` — used to generate `robots.txt` and `sitemap.xml` |
| `VITE_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | the publishable anon key (public by design) |

**SPA fallback** is configured by `quant-app-v1/frontend/public/_redirects`, which Vite copies into `dist/`:

```
/*    /index.html   200
```

`robots.txt` and `sitemap.xml` are generated into `dist/` at build time from
`VITE_SITE_URL` (see `vite.config.ts`); unset builds fall back to the local
dev origin, so a production build must set it. There is no repository-path
disallow and no placeholder host.

**Workers Builds is retired.** `wrangler.toml` was removed in phase P1, so Pages is the single hosting path (SRS AR-2). Unknown paths return `index.html` with HTTP 200 instead of 404.

Reference numbers from the repository-root run (2026-11-07): `npm run build`
finishes in ~2 s after dependency install, emitting 816 KB JS (233 KB gzip) and
171 KB CSS. The SRS budget is 2 minutes and 5 MB gzip (AR-8, AR-9).

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
`gw_get_user_by_id`, `gw_get_preferences`, `gw_upsert_preferences`,
`gw_get_notice_acceptance`, `gw_accept_notice`. Provider API keys use the same
shape (`gateway_provider_keys`, Fernet ciphertext only, RPCs
`gw_list_provider_keys` / `gw_upsert_provider_key` / `gw_delete_provider_key`).
`notice_acceptances` is owner-scoped under RLS and mirrors local SQLite NFR-29
acceptance.

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
| `OPENROUTER_API_KEY` (or another provider's `*_API_KEY`) | API | optional live LLM credential; stored keys are encrypted with `GATEWAY_PROVIDER_KEY`. Without one, chat requests report a provider error and the live smoke test cannot run. |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | API | auth introspection, server-side writes |
| `SUPABASE_RPC_SECRET` | API | guards the SECURITY DEFINER RPCs |
| `VITE_API_BASE` | Pages build | API origin |
| `VITE_SITE_URL` | Pages build | canonical public origin for robots.txt and sitemap.xml |
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

### Live chat SSE smoke test

The offline suite mocks the provider. To confirm real streaming and the NFR-15
aggregate cap, set one provider key on the API host (or in the repo-root `.env`
for a local run) and execute:

```bash
cd quant-app-v1/backend
PYTHONPATH=. ../../.venv/bin/python scripts/smoke_chat_stream.py \
  --provider openrouter --model <model> --max-chars 400
```

The script mounts the chat router with the private-data gate bypassed, streams a
real completion, and exits 0 only when the response is `text/event-stream`, real
deltas arrive, and the stream ends with exactly `--max-chars` characters plus
the aggregate-limit error. Exit 2 means no usable provider key; exit 1 means the
provider errored or produced less than the cap (retry with a longer prompt). It
is deliberately not part of CI.

## 6. Gates

```bash
cd quant-app-v1/frontend && npx tsc --noEmit && npm run build
cd ../backend && PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q
```

Deployment is done when both pass **and** the SRS phase gate (§9) for the
work being shipped is met.
