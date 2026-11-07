/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Supabase project URL, e.g. "https://<ref>.supabase.co" (the only identity provider). */
  readonly VITE_SUPABASE_URL?: string;
  /** Supabase publishable/anon key — public by design, it ships to the browser. */
  readonly VITE_SUPABASE_ANON_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
