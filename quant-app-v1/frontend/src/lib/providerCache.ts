/**
 * Device-side cache for provider configuration lists.
 *
 * Why localStorage rather than cookies (the request allowed a better
 * approach): an httpOnly cookie cannot be read from JavaScript at all, so
 * the site could never "retrieve" it; a readable cookie is capped at ~4KB,
 * is attached to every request (waste + leak surface), and is the wrong
 * container for JSON blobs. localStorage is already this app's
 * device-persistence pattern (chartPrefs, useWorkspace, scanner presets,
 * AiHarness provider selection), survives browser restarts, and is exactly
 * "cached on the user's device, retrievable by the website".
 *
 * What is cached: provider *configuration* only — ids, labels, base URLs,
 * has_key/configured flags, model lists. NEVER API keys or tokens:
 * secrets stay server-side (Fernet-encrypted in Supabase). A cache hit
 * lets the Providers pages paint instantly (stale-while-revalidate) and
 * keeps the last-known configuration visible when the API is unreachable.
 */

const PREFIX = "gw_providers_v1_";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // one week

export function readProviderCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { t?: unknown; data?: T };
    if (!parsed || typeof parsed.t !== "number") return null;
    if (Date.now() - parsed.t > MAX_AGE_MS) {
      localStorage.removeItem(PREFIX + key);
      return null;
    }
    return (parsed.data ?? null) as T | null;
  } catch {
    return null; // corrupt entry, disabled storage, SSR — never break the page
  }
}

export function writeProviderCache<T>(key: string, data: T): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ t: Date.now(), data }));
  } catch {
    // Quota exceeded / private mode — the cache is an optimization only.
  }
}
