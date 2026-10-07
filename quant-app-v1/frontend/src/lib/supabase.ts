/**
 * Supabase Auth client, configured from Vite build-time env vars.
 *
 * Supabase sign-in is opt-in per environment: when either value is missing
 * the app falls back to the backend's own email/password endpoints, so local
 * development keeps working without any Supabase config.
 *
 *   VITE_SUPABASE_URL      https://<project-ref>.supabase.co
 *   VITE_SUPABASE_ANON_KEY <publishable/anon key — safe to expose>
 *
 * The backend mirrors SUPABASE_URL / SUPABASE_KEY and verifies the access
 * tokens this client produces by introspecting them at GoTrue, so the same
 * token works for REST calls and the /ws/* WebSocket query param.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const supabaseUrl = import.meta.env.VITE_SUPABASE_URL ?? "";
export const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";

/** True only when both values needed to talk to GoTrue are present. */
export const supabaseEnabled = Boolean(supabaseUrl && supabaseAnonKey);

export const supabase: SupabaseClient | null = supabaseEnabled
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null;
