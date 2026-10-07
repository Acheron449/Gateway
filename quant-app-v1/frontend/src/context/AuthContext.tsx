import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from "react";
import { API_BASE } from "../lib/constants";
import { auth0Enabled } from "../lib/auth0";
import { supabase, supabaseEnabled } from "../lib/supabase";

interface User {
  id: string;
  email: string;
  name?: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  isAuthenticated: boolean;
  /** True when VITE_AUTH0_* is configured (Auth0 sign-in available). */
  auth0Enabled: boolean;
  /** Adopt an Auth0-issued access token as the app session (used by Auth0Bridge).
   *  Validates the token against /auth/me and throws if the API rejects it. */
  adoptSession: (token: string) => Promise<void>;
  /** Drop the local session without touching an external (Auth0) session. */
  clearSession: () => void;
  /** Called by Auth0Bridge so logout() can also end the Auth0 session. */
  registerExternalLogout: (fn: (() => void) | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = "gateway_auth_token";
const USER_KEY = "gateway_user";

async function apiGetMe(token: string): Promise<User | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return { id: data.id, email: data.email, name: data.name };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  /** Validate an access token against the API and adopt it as the session.
   *  Shared by every sign-in path so a token the API rejects never yields a
   *  half-signed-in UI where every data call 401s. */
  const adoptToken = useCallback(async (accessToken: string) => {
    const me = await apiGetMe(accessToken);
    if (!me) {
      throw new Error(
        "The API rejected this sign-in token — check SUPABASE_URL / SUPABASE_KEY on the backend",
      );
    }
    setToken(accessToken);
    setUser(me);
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(USER_KEY, JSON.stringify(me));
  }, []);

  useEffect(() => {
    let cancelled = false;

    if (supabaseEnabled && supabase) {
      // Supabase Auth is the session authority: it persists the session in
      // localStorage, refreshes access tokens itself, and emits changes we
      // mirror into this context.
      const sb = supabase; // narrowed copy: `supabase` is a nullable module const
      sb.auth
        .getSession()
        .then(({ data }) => {
          if (cancelled) return;
          const accessToken = data.session?.access_token;
          if (accessToken) {
            return adoptToken(accessToken).catch(() => {
              if (!cancelled) sb.auth.signOut().catch(() => undefined);
            });
          }
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false);
        });

      const { data: { subscription } } = sb.auth.onAuthStateChange((_event, session) => {
        if (cancelled) return;
        const accessToken = session?.access_token ?? null;
        if (accessToken) {
          setToken(accessToken);
          // Mirror the refreshed token into storage too: WebSocket clients
          // (and anything else re-reading the stored token after a refresh)
          // must not keep retrying with a stale one.
          localStorage.setItem(TOKEN_KEY, accessToken);
          // Keep profile data fresh (sign-in, token refresh, metadata edits).
          apiGetMe(accessToken).then((me) => {
            if (!cancelled && me) {
              setUser(me);
              localStorage.setItem(USER_KEY, JSON.stringify(me));
            }
          });
        } else {
          setToken(null);
          setUser(null);
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
        }
      });

      return () => {
        cancelled = true;
        subscription.unsubscribe();
      };
    }

    // No Supabase config (local dev): fall back to the backend's own
    // register/login endpoints and the token this app stored itself.
    const storedToken = localStorage.getItem(TOKEN_KEY);
    if (storedToken) {
      setToken(storedToken);
      apiGetMe(storedToken).then((u) => {
        if (u) {
          setUser(u);
          localStorage.setItem(USER_KEY, JSON.stringify(u));
        } else {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
        }
      });
    }
    setIsLoading(false);
  }, [adoptToken]);

  const login = useCallback(async (email: string, password: string) => {
    if (supabaseEnabled && supabase) {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
      const accessToken = data.session?.access_token;
      if (!accessToken) throw new Error("Sign-in failed");
      // adoptToken validates against /auth/me before the UI turns signed-in;
      // onAuthStateChange keeps the token fresh afterwards.
      await adoptToken(accessToken);
      return;
    }
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail || "Login failed");
    }
    const { access_token } = await res.json();
    await adoptToken(access_token);
  }, [adoptToken]);

  const register = useCallback(async (email: string, password: string, name?: string) => {
    if (supabaseEnabled && supabase) {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { name } },
      });
      if (error) throw new Error(error.message);
      const accessToken = data.session?.access_token;
      if (accessToken) {
        await adoptToken(accessToken);
        return;
      }
      // Confirm-email is enabled on the project: no session until the link
      // in the confirmation email has been clicked.
      throw new Error("Account created — check your email to confirm it, then sign in.");
    }
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(error.detail || "Registration failed");
    }
    const { access_token } = await res.json();
    await adoptToken(access_token);
  }, [adoptToken]);

  const externalLogoutRef = useRef<(() => void) | null>(null);

  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    if (supabaseEnabled && supabase) {
      // Ends the Supabase session (and its refresh token); the state change
      // also comes back through onAuthStateChange, which is idempotent here.
      supabase.auth.signOut().catch(() => undefined);
    }
    try {
      // Auth0 bridge registers this; must never block local sign-out.
      externalLogoutRef.current?.();
    } catch {
      /* external logout failed — local session is already gone */
    }
  }, [clearSession]);

  const adoptSession = useCallback(async (newToken: string) => {
    // Validate against the API first: a frontend/backend Auth0 mismatch
    // (missing AUTH0_DOMAIN, wrong audience) must fail loudly, not leave a
    // half-signed-in UI where every data call 401s.
    const me = await apiGetMe(newToken);
    if (!me) {
      throw new Error(
        "The API rejected the Auth0 token — check AUTH0_DOMAIN / AUTH0_AUDIENCE on the backend",
      );
    }
    setToken(newToken);
    setUser(me);
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(me));
  }, []);

  const registerExternalLogout = useCallback((fn: (() => void) | null) => {
    externalLogoutRef.current = fn;
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    const me = await apiGetMe(token);
    if (!me) {
      logout();
    } else {
      setUser(me);
      localStorage.setItem(USER_KEY, JSON.stringify(me));
    }
  }, [token, logout]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        register,
        logout,
        refresh,
        isAuthenticated: !!token && !!user,
        auth0Enabled,
        adoptSession,
        clearSession,
        registerExternalLogout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
