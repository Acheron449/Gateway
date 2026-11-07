/**
 * User-scoped browser storage.
 *
 * Anything that belongs to a signed-in person is written under the prefix
 * `gw_user_` so a sign-out can clear exactly that state and leave device-level
 * preferences (panel widths, chart theme) alone. Nothing private is ever left
 * behind for the next account that signs in on the same browser.
 */

const USER_PREFIX = "gw_user_";

/** Legacy, browser-wide keys written before scoping existed. Purged on sign-out. */
const LEGACY_USER_KEYS = ["gateway_chat_sessions", "gateway_llm_selection"];

/** Namespaced key for a signed-in user's data. */
export function scopedKey(userId: string, key: string): string {
  return `${USER_PREFIX}${userId}_${key}`;
}

/**
 * Remove every user-scoped key. Call on sign-out and on identity transitions.
 * Device-level preferences outside the prefix are intentionally preserved.
 */
export function clearUserScopedStorage(): void {
  try {
    const stale: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && key.startsWith(USER_PREFIX)) stale.push(key);
    }
    for (const key of [...stale, ...LEGACY_USER_KEYS]) {
      localStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable (private mode / SSR) — nothing to clear */
  }
}
