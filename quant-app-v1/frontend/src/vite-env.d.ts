/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Auth0 tenant domain, e.g. "dev-abc123.us.auth0.com" (enables Auth0 sign-in). */
  readonly VITE_AUTH0_DOMAIN?: string;
  /** Auth0 SPA application Client ID. */
  readonly VITE_AUTH0_CLIENT_ID?: string;
  /** Auth0 API identifier — required: without an audience Auth0 issues opaque (non-JWT) tokens. */
  readonly VITE_AUTH0_AUDIENCE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
