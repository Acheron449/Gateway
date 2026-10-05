# Deploying Gateway — Vercel, Cloudflare, Supabase

Gateway is two pieces:

| Piece          | Tech                                | Where it runs                          |
| -------------- | ----------------------------------- | -------------------------------------- |
| Frontend       | Vite + React (`quant-app-v1/frontend`) | Vercel **or** Cloudflare Pages      |
| Backend        | FastAPI (`quant-app-v1/backend`)    | Container / PaaS / Cloudflare Worker   |
| Database       | SQLite (local file)                 | Hostable on Supabase (see below)       |

The frontend finds the backend through `VITE_API_BASE` (build-time env var).
If it is not set, a non-localhost build assumes same-origin reverse proxying
(`src/lib/constants.ts`).

## 1. Vercel (frontend)

Repo-root [vercel.json](../vercel.json) wires the monorepo build — the
previous config ran `npm run build` at the repo root (there is no root
package.json), which failed every deploy:

```bash
# Import the repo in Vercel, or:
npx vercel login   # CLI is per-machine; deploys from git need no CLI
npx vercel --prod
```

- `package-lock.json` must stay in sync with `package.json` (`npm ci`
  refuses a drifted lockfile — keep both committed).

- Build: `cd quant-app-v1/frontend && npm ci && npm run build`
- Output: `quant-app-v1/frontend/dist`
- SPA fallback redirect to `index.html` is configured.
- Set `VITE_API_BASE` in the project env to your backend's public URL
  (e.g. `https://api.yourdomain.com`).

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
4. Export rows with `POST /journal` data or point your sync job at
   `journal_entries` — the `source` column (`paper` / `actual` / `manual`)
   is what makes actual-vs-paper comparison queries work:

```sql
select * from journal_performance_by_source;  -- paper vs actual side by side
```

## 4. Environment variables

All of these belong in the backend environment (see [.env.example](../.env.example)):

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET_KEY` | Session signing — required, the API refuses to boot without it |
| `GATEWAY_PROVIDER_KEY` | Fernet key encrypting provider keys **and** the secrets vault |
| `GATEWAY_QUOTES_TTL` | Seconds before batch quotes refetch (default 10) |
| `GATEWAY_PRICE_TTL` | Seconds before the fill/risk price cache refetches (default 10) |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Live trading section (Alpaca) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | Hosted Postgres connection |
| `VITE_API_BASE` | Frontend build-time backend URL |

## 5. Post-deploy smoke test

```bash
curl -fsS $API/healthz || curl -fsS $API/
curl -fsS $API/news/sources
# then open the app → Markets → chart loads → paper order fills →
# Journal shows the auto-logged paper trade.
```
