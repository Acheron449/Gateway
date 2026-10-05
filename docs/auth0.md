# Auth0 authentication

Gateway supports two sign-in modes at the same time; either or both can be
active:

| Mode | Who verifies | Enabled by | Login UI |
| --- | --- | --- | --- |
| Local password | Backend HS256 (`app/auth.py`) | `JWT_SECRET_KEY` set | Email/password in the auth modal |
| Auth0 (RS256) | Backend against the tenant JWKS | `AUTH0_DOMAIN` set | "Continue with Auth0" in the auth modal |

A request carries one `Authorization: Bearer <jwt>` header either way. The
backend dispatches on the token's (unverified) `iss` claim: issuer matching
`https://$AUTH0_DOMAIN/` → RS256 verification against the tenant JWKS;
everything else → local HMAC verification. A forged issuer still fails the
signature check, so the two paths cannot be confused.

## 1. Auth0 tenant setup

1. Create an **API** (e.g. identifier `https://gateway-api`), RS256 — this is
   the *audience*. Auth0 issues **opaque** (non-JWT) access tokens without an
   audience, which the backend cannot verify, so this step is mandatory.
2. Create a **Single Page Application** (type: SPA), and add to its
   Allowed Callback/Logout URLs the origins you run on, e.g.
   `http://localhost:5173` and your production origin.
3. Note the tenant domain, SPA Client ID, and API identifier.

## 2. Environment variables

Backend (FastAPI):

```bash
AUTH0_DOMAIN=dev-abc123.us.auth0.com     # tenant domain, no https://
AUTH0_AUDIENCE=https://gateway-api        # optional but recommended
JWT_SECRET_KEY=...                       # keep set unless Auth0-only
```

Frontend (Vite — build time, `VITE_` prefix):

```bash
VITE_AUTH0_DOMAIN=dev-abc123.us.auth0.com
VITE_AUTH0_CLIENT_ID=AbC123...
VITE_AUTH0_AUDIENCE=https://gateway-api   # must match AUTH0_AUDIENCE
```

All three `VITE_AUTH0_*` values are required for the "Continue with Auth0"
button to appear; missing values keep the app on password auth only.

- **Local dev**: put the backend vars in your shell (or `.env`), the frontend
  vars in `quant-app-v1/frontend/.env.local`.
- **Docker**: put `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_AUDIENCE` in
  `.env` next to `docker-compose.yml` — compose forwards them to the backend
  environment and as build args for the SPA.
- **Vercel / Cloudflare Pages**: set the three `VITE_AUTH0_*` variables in
  the project settings (they are baked in at build time) and the backend vars
  in the API host's environment.

## 3. Behaviour

- Auth0 users need **no row in the local database**: `/auth/me`,
  preferences and every `CurrentUser` route work off the signed token claims
  (`sub`, `email`/`preferred_username`, `name`).
- The SPA adopts the Auth0 access token by validating it against `/auth/me`,
  so a frontend/backend mismatch (wrong audience, missing `AUTH0_DOMAIN`)
  fails loudly instead of leaving a half-signed-in UI. Tokens are silently
  renewed every 30 minutes (`offline_access` + refresh tokens, cached in
  localStorage).
- Signing out ends both sessions: the app's `logout()` also calls Auth0's
  `/v2/logout` when an Auth0 session exists.
- With **Auth0 only** (`AUTH0_DOMAIN` set, `JWT_SECRET_KEY` unset):
  `/auth/register`, `/auth/login` and `/auth/refresh` return `503`; token
  verification still works. With neither variable set, the backend refuses
  to start (fail-closed).
- WebSockets (`/ws/trading`, portfolio stream) accept Auth0 tokens via
  `?token=` the same way they accept local ones.

## 4. Verification

- Backend: `tests/test_auth0.py` covers issuer/audience/expiry/signature
  rejection, JWKS key rotation and stale-cache fallback, local-token
  regression, and fail-closed startup (no network — `_download_jwks` is
  stubbed).
- Frontend: `tsc --noEmit` plus the auth modal rendering the Auth0 button
  only when the three `VITE_AUTH0_*` values are present.
