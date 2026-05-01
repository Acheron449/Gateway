const raw = typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE;
export const API_BASE =
  typeof raw === "string" && raw.length > 0 ? raw.replace(/\/$/, "") : "http://127.0.0.1:8000";

export const WS_BASE = API_BASE.replace(/^http/, "ws");
