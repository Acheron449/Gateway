const raw = typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE;

const isBrowser = typeof window !== "undefined" && typeof window.location !== "undefined";
const isLocalhostPage =
  isBrowser && /^(localhost|127\.0\.0\.1)(:\d+)?$/.test(window.location.hostname);

export const API_BASE =
  typeof raw === "string" && raw.length > 0
    ? raw.replace(/\/$/, "")
    : // Localhost dev: the API runs as a sibling service (default :8000), and
      // the backend now sends CORS headers for localhost origins.
      isLocalhostPage || !isBrowser
      ? "http://127.0.0.1:8000"
      : // Non-localhost deployment: assume a reverse proxy forwards same-origin
        // requests to the API. A baked-in loopback URL can never work there.
        "";

// A relative WebSocket URL is invalid (`new WebSocket("/ws/...")` throws), so
// derive an absolute one: from API_BASE when set, otherwise the current host.
export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, "ws")
  : isBrowser
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
    : "ws://127.0.0.1:8000";
