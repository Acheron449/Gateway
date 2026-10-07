/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Auth0 tenant domain, e.g. "dev-abc123.us.auth0.com" (enables Auth0 sign-in). */
  readonly VITE_AUTH0_DOMAIN?: string;
  /** Auth0 SPA application Client ID. */
  readonly VITE_AUTH0_CLIENT_ID?: string;
  /** Auth0 API identifier — required: without an audience Auth0 issues opaque (non-JWT) tokens. */
  readonly VITE_AUTH0_AUDIENCE?: string;
  /** Supabase project URL, e.g. "https://<ref>.supabase.co" (enables Supabase Auth sign-in). */
  readonly VITE_SUPABASE_URL?: string;
  /** Supabase publishable/anon key — public by design, it ships to the browser. */
  readonly VITE_SUPABASE_ANON_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
